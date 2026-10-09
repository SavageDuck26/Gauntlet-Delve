//! Optional GPU evaluation path (wgpu + WGSL).
//!
//! Each thread owns a contiguous run of candidate indices, decodes the
//! mixed-radix picks once, then walks its run with a cheap odometer,
//! assembling every candidate byte-by-byte straight into the MurmurHash64A
//! accumulator (no string is ever materialised) and probing a hash table of
//! the target hashes.
//!
//! Design notes:
//!   * MurmurHash64A needs 64-bit multiplies -> requires
//!     `wgpu::Features::SHADER_INT64` (available on the RX 6600 XT / Vulkan).
//!   * Dispatches are kept short (~0.3 s): amdgpu's scheduler watchdog kills
//!     long-running dispatches (same batching trick as Duckomp-v5).
//!   * The GPU reports MATCHING INDICES only; the host rebuilds the name with
//!     the trusted CPU emitter and re-hashes it before recording, so a GPU
//!     arithmetic bug can never write a wrong name.
//!   * If anything is unavailable the caller keeps using the CPU path.

use crate::murmur::hash_bytes;
use crate::pattern::{Compiled, Part};
use anyhow::{anyhow, Result};

/// Slots per candidate (must match `pattern::Compiled`'s fixed decode array).
const MAX_SLOTS: usize = 8;
/// Match indices one batch may report.
const MAX_RESULTS: u32 = 4096;
/// Threads per workgroup (must match `@workgroup_size`).
const WG_SIZE: u32 = 256;
/// Workgroups per dispatch -> 2.1 M threads.
const WORKGROUPS: u32 = 8192;
/// Target seconds of GPU work per dispatch (watchdog margin).
const TARGET_BATCH_SECS: f64 = 0.30;

/// Uniform block; layout must match the WGSL `Params` struct exactly.
#[repr(C)]
#[derive(Clone, Copy, bytemuck::Pod, bytemuck::Zeroable)]
struct Params {
    base: u64,
    total: u64,
    iters: u32,
    nslots: u32,
    tmask: u32,
    _pad: u32,
}

/// GPU context: device, queue, pipeline and the bind group layout.
pub struct Gpu {
    device: wgpu::Device,
    queue: wgpu::Queue,
    pipeline: wgpu::ComputePipeline,
    layout: wgpu::BindGroupLayout,
    info: String,
}

fn table_slot(h: u64, mask: usize) -> usize {
    (h.wrapping_mul(0x9E37_79B9_7F4A_7C15) >> 40) as usize & mask
}

const SHADER_SRC: &str = r#"
struct Params {
    base: u64,
    total: u64,
    iters: u32,
    nslots: u32,
    tmask: u32,
    pad: u32,
};

@group(0) @binding(0) var<uniform> P: Params;
// mdat = [ lens[nslots] ][ ops: 4 x u32 per op ], op = (kind, x, y, z)
//   kind 0: literal -> x = byte offset into blob, y = byte length
//   kind 1: slot    -> x = used-slot position,   y = first entry index
@group(0) @binding(1) var<storage, read> mdat: array<u32>;
@group(0) @binding(2) var<storage, read> blob: array<u32>;    // packed bytes
@group(0) @binding(3) var<storage, read> entries: array<u32>; // 2 per word: off,len
@group(0) @binding(4) var<storage, read> tab: array<u64>;     // 0 = empty slot
@group(0) @binding(5) var<storage, read_write> rc: array<atomic<u32>>;
@group(0) @binding(6) var<storage, read_write> ridx: array<u64>;

// naga cannot hold u64 literals above i64::MAX, so store the bit patterns as i64
const MB: i64 = -4132994306676758123;
const KB: i64 = -7046029254386353131;
const R: u32 = 47u;

fn byte_at(i: u32) -> u32 {
    return (blob[i >> 2u] >> ((i & 3u) * 8u)) & 0xffu;
}

fn bump(picks: ptr<function, array<u64, 8>>, nslots: u32) -> bool {
    for (var s = 0u; s < nslots; s = s + 1u) {
        (*picks)[s] = (*picks)[s] + u64(1u);
        if ((*picks)[s] < u64(mdat[s])) { return true; }
        (*picks)[s] = u64(0u);
    }
    return false;
}

@compute @workgroup_size(256)
fn eval(@builtin(global_invocation_id) gid: vec3<u32>) {
    let nslots = P.nslots;
    let nops = mdat[8u];
    let M: u64 = bitcast<u64>(MB);
    let K: u64 = bitcast<u64>(KB);
    let start = P.base + u64(gid.x) * u64(P.iters);

    var picks: array<u64, 8>;
    var rem = start;
    for (var s = 0u; s < nslots; s = s + 1u) {
        picks[s] = rem % u64(mdat[s]);
        rem = rem / u64(mdat[s]);
    }

    for (var it = 0u; it < P.iters; it = it + 1u) {
        let idx = start + u64(it);
        if (idx >= P.total) { break; }

        // pass 1: total byte length (Murmur seeds with len * M)
        var total_len: u32 = 0u;
        for (var p = 0u; p < nops; p = p + 1u) {
            let o = 9u + p * 4u;
            if (mdat[o] == 0u) {
                total_len = total_len + mdat[o + 2u];
            } else {
                let e = mdat[o + 2u] + u32(picks[mdat[o + 1u]]);
                total_len = total_len + entries[e * 2u + 1u];
            }
        }

        // pass 2: feed bytes through the accumulator
        var h: u64 = u64(total_len) * M;
        var acc: u64 = u64(0u);
        var nb: u32 = 0u;
        for (var p = 0u; p < nops; p = p + 1u) {
            let o = 9u + p * 4u;
            var off: u32;
            var len: u32;
            if (mdat[o] == 0u) {
                off = mdat[o + 1u];
                len = mdat[o + 2u];
            } else {
                let e = mdat[o + 2u] + u32(picks[mdat[o + 1u]]);
                off = entries[e * 2u];
                len = entries[e * 2u + 1u];
            }
            for (var i = 0u; i < len; i = i + 1u) {
                acc = acc | (u64(byte_at(off + i)) << (nb * 8u));
                nb = nb + 1u;
                if (nb == 8u) {
                    var k = acc * M;
                    k = k ^ (k >> R);
                    k = k * M;
                    h = (h ^ k) * M;
                    acc = u64(0u);
                    nb = 0u;
                }
            }
        }
        if (nb > 0u) { h = (h ^ acc) * M; }
        h = h ^ (h >> R);
        h = h * M;
        h = h ^ (h >> R);

        // probe the target table (open addressing, 0 marks an empty slot)
        var i = u32((h * K) >> 40u) & P.tmask;
        loop {
            let t = tab[i];
            if (t == u64(0u)) { break; }
            if (t == h) {
                let slot = atomicAdd(&rc[0], 1u);
                if (slot < 4096u) { ridx[slot] = idx; }
                break;
            }
            i = (i + 1u) & P.tmask;
        }

        if (!bump(&picks, nslots)) { break; }
    }
}
"#;

fn bgl(binding: u32, ty: wgpu::BufferBindingType) -> wgpu::BindGroupLayoutEntry {
    wgpu::BindGroupLayoutEntry {
        binding,
        visibility: wgpu::ShaderStages::COMPUTE,
        ty: wgpu::BindingType::Buffer { ty, has_dynamic_offset: false, min_binding_size: None },
        count: None,
    }
}

impl Gpu {
    /// Build a GPU context, or explain why we can't (caller falls back to CPU).
    pub fn new() -> Result<Gpu> {
        let instance = wgpu::Instance::new(wgpu::InstanceDescriptor {
            backends: wgpu::Backends::VULKAN,
            ..Default::default()
        });
        let adapter = pollster::block_on(instance.request_adapter(&wgpu::RequestAdapterOptions {
            power_preference: wgpu::PowerPreference::HighPerformance,
            ..Default::default()
        }))
        .ok_or_else(|| anyhow!("no Vulkan adapter found"))?;

        let features = adapter.features();
        if !features.contains(wgpu::Features::SHADER_INT64) {
            return Err(anyhow!("adapter {} lacks SHADER_INT64", adapter.get_info().name));
        }
        let ai = adapter.get_info();
        let info = format!("{} ({:?}, {:?})", ai.name, ai.device_type, ai.backend);

        // Ask for what the adapter actually supports rather than wgpu's conservative
        // defaults: a sweep with a large word list (several million directory prefixes,
        // say) needs a storage binding well past the default 128 MiB, and silently
        // failing at create_bind_group is a bad way to find that out.
        let limits = adapter.limits();
        let (device, queue) = pollster::block_on(adapter.request_device(
            &wgpu::DeviceDescriptor {
                label: Some("hashcracker"),
                required_features: wgpu::Features::SHADER_INT64,
                required_limits: limits,
                ..Default::default()
            },
            None,
        ))?;

        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("hashcracker_eval"),
            source: wgpu::ShaderSource::Wgsl(SHADER_SRC.into()),
        });
        let ro = wgpu::BufferBindingType::Storage { read_only: true };
        let rw = wgpu::BufferBindingType::Storage { read_only: false };
        let layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: None,
            entries: &[
                bgl(0, wgpu::BufferBindingType::Uniform),
                bgl(1, ro),
                bgl(2, ro),
                bgl(3, ro),
                bgl(4, ro),
                bgl(5, rw),
                bgl(6, rw),
            ],
        });
        let pl = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: None,
            bind_group_layouts: &[&layout],
            push_constant_ranges: &[],
        });
        let pipeline = device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: None,
            layout: Some(&pl),
            module: &shader,
            entry_point: "eval",
            compilation_options: Default::default(),
            cache: None,
        });
        Ok(Gpu { device, queue, pipeline, layout, info })
    }

    pub fn info(&self) -> &str {
        &self.info
    }

    /// Evaluate every candidate of `pat` (capped at `limit`, 0 = all) on the
    /// GPU. `on_match(hash, name)` fires for confirmed targets only. Returns
    /// the number of candidates evaluated.
    pub fn eval_pattern(
        &self,
        pat: &Compiled,
        lists: &[Vec<Vec<u8>>],
        targets: &std::collections::HashSet<u64>,
        limit: u64,
        on_match: &mut dyn FnMut(u64, &[u8]),
    ) -> Result<u64> {
        use wgpu::util::DeviceExt;

        let total = if limit > 0 { pat.total().min(limit) } else { pat.total() };
        if total == 0 {
            return Ok(0);
        }
        let nslots = pat.slots();
        if nslots > MAX_SLOTS {
            return Err(anyhow!("{nslots} slots exceeds the GPU limit of {MAX_SLOTS}"));
        }
        if targets.contains(&0) {
            return Err(anyhow!("a target hash is 0, which marks empty table slots"));
        }

        // per-used-slot entry base (word entries are stored slot-major)
        let mut ebase = [0u32; MAX_SLOTS];
        let mut acc = 0u32;
        for p in 0..nslots {
            ebase[p] = acc;
            acc += pat.lens[p] as u32;
        }

        // meta = [8 x lens][nops][ops x 4]
        let mut meta: Vec<u32> = vec![0; 8];
        for p in 0..nslots {
            meta[p] = pat.lens[p] as u32;
        }
        let mut ops: Vec<u32> = Vec::new();
        let mut blob: Vec<u8> = Vec::new();
        for part in &pat.parts {
            match part {
                Part::Lit(b) => {
                    let off = blob.len() as u32;
                    ops.extend_from_slice(&[0, off, b.len() as u32, 0]);
                    blob.extend_from_slice(b);
                }
                Part::Slot(pos) => ops.extend_from_slice(&[1, *pos as u32, ebase[*pos], 0]),
            }
        }
        meta.push((ops.len() / 4) as u32); // nops lives at index 8
        meta.extend_from_slice(&ops);

        // word blob + (offset, len) entries, ordered by used-slot
        let mut entries: Vec<u32> = Vec::new();
        for p in 0..nslots {
            for w in &lists[pat.used[p]] {
                entries.push(blob.len() as u32);
                entries.push(w.len() as u32);
                blob.extend_from_slice(w);
            }
        }
        // pack bytes little-endian into u32 words (shader unpacks with shifts)
        let mut packed: Vec<u32> = Vec::with_capacity(blob.len() / 4 + 1);
        for chunk in blob.chunks(4) {
            let mut v = [0u8; 4];
            v[..chunk.len()].copy_from_slice(chunk);
            packed.push(u32::from_le_bytes(v));
        }
        if packed.is_empty() {
            packed.push(0);
        }

        // target hash table, same slot function as the CPU TargetSet
        let cap = (targets.len() * 2).next_power_of_two().max(16);
        let mask = cap - 1;
        let mut tab = vec![0u64; cap];
        for &h in targets {
            let mut i = table_slot(h, mask);
            while tab[i] != 0 {
                i = (i + 1) & mask;
            }
            tab[i] = h;
        }
        if entries.is_empty() {
            entries.push(0); // wgpu rejects zero-sized buffers
        }

        // ---- buffers ----
        let params_buf = self.device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("params"),
            size: std::mem::size_of::<Params>() as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let mk = |label: &str, bytes: &[u8]| {
            self.device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
                label: Some(label),
                contents: bytes,
                usage: wgpu::BufferUsages::STORAGE,
            })
        };
        let meta_buf = mk("meta", bytemuck::cast_slice(&meta));
        let blob_buf = mk("blob", bytemuck::cast_slice(&packed));
        let entries_buf = mk("entries", bytemuck::cast_slice(&entries));
        let tab_buf = mk("tab", bytemuck::cast_slice(&tab));
        let rc_buf = self.device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("rc"),
            size: 4,
            usage: wgpu::BufferUsages::STORAGE
                | wgpu::BufferUsages::COPY_DST
                | wgpu::BufferUsages::COPY_SRC,
            mapped_at_creation: false,
        });
        let ridx_size = (MAX_RESULTS as u64) * 8;
        let ridx_buf = self.device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("ridx"),
            size: ridx_size,
            usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_SRC,
            mapped_at_creation: false,
        });
        let stage = self.device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("stage"),
            size: 4 + ridx_size,
            usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let bind_group = self.device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: None,
            layout: &self.layout,
            entries: &[
                wgpu::BindGroupEntry { binding: 0, resource: params_buf.as_entire_binding() },
                wgpu::BindGroupEntry { binding: 1, resource: meta_buf.as_entire_binding() },
                wgpu::BindGroupEntry { binding: 2, resource: blob_buf.as_entire_binding() },
                wgpu::BindGroupEntry { binding: 3, resource: entries_buf.as_entire_binding() },
                wgpu::BindGroupEntry { binding: 4, resource: tab_buf.as_entire_binding() },
                wgpu::BindGroupEntry { binding: 5, resource: rc_buf.as_entire_binding() },
                wgpu::BindGroupEntry { binding: 6, resource: ridx_buf.as_entire_binding() },
            ],
        });

        // ---- batched dispatch loop (short batches dodge the AMD watchdog) ----
        let nthreads = (WORKGROUPS as u64) * (WG_SIZE as u64);
        let mut iters: u64 = 8;
        let mut base: u64 = 0;
        let mut buf: Vec<u8> = Vec::with_capacity(256);
        let mut slow_batches = 0u32;
        let mut raw_reported: u64 = 0;
        let mut confirmed: u64 = 0;
        let mut rehash_mismatch: u32 = 0;
        while base < total {
            let n = (iters * nthreads).min(total - base).max(1);
            let it = n.div_ceil(nthreads).max(1) as u32;
            let params = Params {
                base,
                total,
                iters: it,
                nslots: nslots as u32,
                tmask: mask as u32,
                _pad: 0,
            };
            self.queue.write_buffer(&params_buf, 0, bytemuck::bytes_of(&params));
            self.queue.write_buffer(&rc_buf, 0, &[0u8; 4]);

            let t_batch = std::time::Instant::now();
            let mut enc = self.device.create_command_encoder(&Default::default());
            {
                let mut pass = enc.begin_compute_pass(&wgpu::ComputePassDescriptor {
                    label: None,
                    timestamp_writes: None,
                });
                pass.set_pipeline(&self.pipeline);
                pass.set_bind_group(0, &bind_group, &[]);
                pass.dispatch_workgroups(WORKGROUPS, 1, 1);
            }
            enc.copy_buffer_to_buffer(&rc_buf, 0, &stage, 0, 4);
            enc.copy_buffer_to_buffer(&ridx_buf, 0, &stage, 4, ridx_size);
            self.queue.submit(Some(enc.finish()));

            let slice = stage.slice(..);
            slice.map_async(wgpu::MapMode::Read, |_| {});
            self.device.poll(wgpu::Maintain::Wait);
            {
                let data = slice.get_mapped_range();
                let count = u32::from_le_bytes([data[0], data[1], data[2], data[3]]) as usize;
                raw_reported += count as u64;
                for i in 0..count.min(MAX_RESULTS as usize) {
                    let idx = u64::from_le_bytes(data[4 + i * 8..12 + i * 8].try_into().unwrap());
                    if idx >= total {
                        continue;
                    }
                    // rebuild on the host and RE-HASH: the GPU can only ever
                    // surface an index, never a wrong name
                    pat.build(lists, idx, &mut buf);
                    let h = hash_bytes(&buf);
                    if targets.contains(&h) {
                        confirmed += 1;
                        on_match(h, &buf);
                    } else if rehash_mismatch < 5 {
                        rehash_mismatch += 1;
                        eprintln!("  (gpu: index {idx} rebuilt to {:?} hashing {h:016x} - not a target)",
                                  String::from_utf8_lossy(&buf));
                    }
                }
            }
            stage.unmap();

            let secs = t_batch.elapsed().as_secs_f64().max(1e-6);
            let rate = n as f64 / secs;
            iters = (((rate * TARGET_BATCH_SECS) / nthreads as f64) as u64).clamp(1, 1 << 20);
            if secs > TARGET_BATCH_SECS * 4.0 {
                slow_batches += 1;
            }
            base += n;
        }
        if slow_batches > 0 {
            eprintln!("  (gpu: {slow_batches} over-long batch(es) - watchdog margin thin)");
        }
        eprintln!("  (gpu diag: {} indices reported by the shader, {confirmed} confirmed by re-hash, \
                   {rehash_mismatch}+ rebuild mismatches)", raw_reported);
        Ok(total)
    }
}

