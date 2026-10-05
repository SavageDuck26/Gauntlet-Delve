#!/usr/bin/env python3
"""
Stingray .texture resource tools — DDS ↔ PNG ↔ Engine binary.

The .texture file IS a DDS file (standard DirectX texture format).
No custom header or wrapper — just raw DDS data.

Supported DDS formats:
  DXT1  (BC1)  — opaque/1-bit alpha, 4 bpp
  DXT5  (BC3)  — RGBA 8 bpp
  ATI2  (BC5)  — 2-channel normal maps (R+G)
  uncompressed BGRA / RGBA

Blender round-trip:
  .texture → .png   : dds_to_png()   (decode, universal)
  .texture → .dds   : just copy the file (already DDS)
  .png → .texture   : png_to_dds()   (encode — requires either texconv or
                                       wand/imageio-freeimage for DXT compression)
  .dds → .texture   : just copy the file

ATI2 normal maps: exported as RGBA where R=X, G=Y, B=reconstructed Z (for Blender).

Usage:
  python texture_tools.py selftest
  python texture_tools.py decode   <file.texture>  [out.png]
  python texture_tools.py encode   <file.png>       [out.texture]   [--format dxt1|dxt5|ati2]
  python texture_tools.py info     <file.texture>
"""

from __future__ import annotations
import io, json, os, struct, sys
from typing import Any, Dict, Optional
from PIL import Image

# ── DDS constants ──────────────────────────────────────────────────────────────

DDS_MAGIC = b'DDS '
DDS_HEADER_SIZE = 124

DDSCAPS2_CUBEMAP       = 0x200
DDSCAPS2_CUBEMAP_FACES = 0xFC00  # all 6 faces

FOURCC = {
    b'DXT1': 'DXT1',
    b'DXT3': 'DXT3',
    b'DXT5': 'DXT5',
    b'ATI1': 'ATI1',
    b'ATI2': 'ATI2',
    b'BC4U': 'ATI1',
    b'BC5U': 'ATI2',
    b'DX10': 'DX10',
}

# DXGI formats for DX10 extended header
DXGI_FORMAT = {
    71: 'BC1_UNORM',   # DXT1
    72: 'BC1_UNORM_SRGB',
    74: 'BC2_UNORM',   # DXT3
    77: 'BC3_UNORM',   # DXT5
    80: 'BC4_UNORM',   # ATI1
    83: 'BC5_UNORM',   # ATI2
    86: 'BC6H_UF16',
    87: 'BC6H_SF16',
    98: 'BC7_UNORM',
    99: 'BC7_UNORM_SRGB',
    87: 'R8G8B8A8_UNORM',
}


# ── DDS info ───────────────────────────────────────────────────────────────────

def dds_info(blob: bytes) -> Dict[str, Any]:
    """Parse DDS header and return metadata dict."""
    if blob[:4] != DDS_MAGIC:
        raise ValueError("Not a DDS file (bad magic)")

    (
        size, flags, height, width,
        pitch_or_linear, depth, mip_count
    ) = struct.unpack_from('<7I', blob, 4)

    # Pixel format at offset 76
    pf_size, pf_flags, fourcc_bytes, rgb_bit_count = struct.unpack_from('<4I', blob, 76)
    fourcc_str = fourcc_bytes.to_bytes(4, 'little').decode('latin1')

    fmt = FOURCC.get(fourcc_bytes.to_bytes(4, 'little'), fourcc_str.strip('\x00'))

    caps2 = struct.unpack_from('<I', blob, 112)[0]
    is_cubemap = bool(caps2 & DDSCAPS2_CUBEMAP)

    info = {
        'width': width,
        'height': height,
        'mip_count': mip_count,
        'format': fmt,
        'fourcc': fourcc_str.strip('\x00'),
        'is_cubemap': is_cubemap,
        'file_size': len(blob),
    }

    if fmt == 'DX10':
        # DX10 extended header at offset 128
        dxgi_fmt = struct.unpack_from('<I', blob, 128)[0]
        info['dxgi_format'] = DXGI_FORMAT.get(dxgi_fmt, f'DXGI_{dxgi_fmt}')
        info['format'] = info['dxgi_format']

    return info


# ── DDS → PNG ──────────────────────────────────────────────────────────────────

def dds_to_png(src: str, dst: str | None = None) -> str:
    """
    Convert a .texture (DDS) file to PNG.

    ATI2 / BC5 normal maps are reconstructed: R=X, G=Y, B=sqrt(1-X²-Y²), A=255.
    Returns the output path.
    """
    blob = open(src, 'rb').read()
    info = dds_info(blob)
    fmt = info['format']

    if dst is None:
        dst = os.path.splitext(src)[0] + '.png'

    if fmt in ('ATI2', 'ATI1', 'BC5_UNORM', 'BC4_UNORM'):
        img = _decode_ati2_to_rgb(blob, info)
    else:
        try:
            img = Image.open(io.BytesIO(blob))
            # Ensure RGBA for transparency support
            if img.mode not in ('RGBA', 'RGB'):
                img = img.convert('RGBA')
        except Exception as e:
            raise RuntimeError(f"Pillow could not decode {fmt} DDS: {e}")

    img.save(dst, 'PNG')
    print(f"texture → PNG: {src}  →  {dst}  [{info['width']}×{info['height']} {fmt}]")
    return dst


def _decode_ati2_to_rgb(blob: bytes, info: dict) -> Image.Image:
    """
    Decode ATI2/BC5 normal map → RGB image.
    Pillow decodes ATI2 as 2-channel; we reconstruct Z and output RGBA.
    """
    try:
        raw = Image.open(io.BytesIO(blob))
        # Pillow gives us an RGB image for ATI2 where R=X, G=Y, B=0
        arr = list(raw.getdata())
        w, h = raw.size

        # Reconstruct Z channel
        import math
        pixels = []
        for r, g, b in arr:
            # Remap [0..255] → [-1..1]
            nx = (r / 127.5) - 1.0
            ny = (g / 127.5) - 1.0
            nz2 = 1.0 - nx * nx - ny * ny
            nz = math.sqrt(max(0.0, nz2))
            bz = int((nz + 1.0) * 127.5)
            pixels.append((r, g, bz, 255))

        out = Image.new('RGBA', (w, h))
        out.putdata(pixels)
        return out
    except Exception as e:
        # Fall back to plain Pillow decode
        raw = Image.open(io.BytesIO(blob))
        return raw.convert('RGBA')


# ── PNG → DDS (.texture) ──────────────────────────────────────────────────────

def png_to_dds(src: str, dst: str | None = None, fmt: str = 'dxt5',
               generate_mipmaps: bool = False) -> str:
    """
    Convert a PNG to a DDS file suitable for use as a .texture resource.

    Preferred method: texconv (DirectXTex, free Microsoft tool).
    Fallback: uncompressed BGRA (no quality loss but large file).

    fmt options: 'dxt1' (opaque), 'dxt5' (alpha), 'ati2' (normal map), 'rgba'
    """
    if dst is None:
        dst = os.path.splitext(src)[0] + '.dds'

    # Try texconv first (best quality DXT compression)
    texconv = _find_texconv()
    if texconv:
        return _texconv_encode(texconv, src, dst, fmt, generate_mipmaps)

    # Fallback: write uncompressed BGRA DDS
    print(f"  texconv not found — writing uncompressed BGRA DDS (install texconv for DXT compression)")
    return _write_uncompressed_dds(src, dst)


def _find_texconv() -> Optional[str]:
    """Locate texconv binary."""
    import shutil
    for name in ['texconv', 'texconv.exe']:
        path = shutil.which(name)
        if path:
            return path
    # Common install locations
    candidates = [
        '/usr/local/bin/texconv',
        os.path.expanduser('~/bin/texconv'),
        os.path.join(os.path.dirname(__file__), '..', 'tools', 'texconv'),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def _texconv_encode(texconv: str, src: str, dst: str, fmt: str,
                    mipmaps: bool) -> str:
    """Use Microsoft texconv to compress PNG → DDS."""
    import subprocess
    fmt_map = {
        'dxt1': 'BC1_UNORM',
        'dxt5': 'BC3_UNORM',
        'ati2': 'BC5_UNORM',
        'rgba': 'R8G8B8A8_UNORM',
    }
    dxgi = fmt_map.get(fmt.lower(), 'BC3_UNORM')
    out_dir = os.path.dirname(dst) or '.'
    tmp_name = os.path.splitext(os.path.basename(src))[0] + '.dds'
    tmp_path = os.path.join(out_dir, tmp_name)

    cmd = [texconv, '-f', dxgi, '-o', out_dir]
    if not mipmaps:
        cmd += ['-m', '1']
    cmd.append(src)

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  texconv error: {result.stderr}")
        return _write_uncompressed_dds(src, dst)

    if tmp_path != dst and os.path.exists(tmp_path):
        os.rename(tmp_path, dst)
    print(f"PNG → DDS ({dxgi}): {src}  →  {dst}")
    return dst


def _write_uncompressed_dds(src: str, dst: str) -> str:
    """Write an uncompressed BGRA DDS (Pillow fallback, no DXT compression)."""
    img = Image.open(src).convert('RGBA')
    w, h = img.size

    # Convert RGBA → BGRA (DDS uses BGR byte order for uncompressed)
    r, g, b, a = img.split()
    bgra = Image.merge('RGBA', (b, g, r, a))
    raw_pixels = bgra.tobytes()

    # Build DDS header
    DDSD_CAPS        = 0x1
    DDSD_HEIGHT      = 0x2
    DDSD_WIDTH       = 0x4
    DDSD_PITCH       = 0x8
    DDSD_PIXELFORMAT = 0x1000
    DDPF_RGB         = 0x40
    DDPF_ALPHAPIXELS = 0x1
    DDSCAPS_TEXTURE  = 0x1000

    pitch = w * 4  # BGRA = 4 bytes per pixel
    flags = DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PITCH | DDSD_PIXELFORMAT

    pf = struct.pack('<8I',
        32,                        # dwSize
        DDPF_RGB | DDPF_ALPHAPIXELS,  # dwFlags
        0,                         # dwFourCC (none for uncompressed)
        32,                        # dwRGBBitCount
        0x00FF0000,                # dwRBitMask (B in BGRA)
        0x0000FF00,                # dwGBitMask
        0x000000FF,                # dwBBitMask (R in BGRA)
        0xFF000000,                # dwABitMask
    )

    caps = struct.pack('<4I', DDSCAPS_TEXTURE, 0, 0, 0)

    header = struct.pack('<7I', DDS_HEADER_SIZE, flags, h, w, pitch, 0, 1) + \
             b'\x00' * (11 * 4) + pf + caps + b'\x00' * 4

    with open(dst, 'wb') as f:
        f.write(DDS_MAGIC)
        f.write(header)
        f.write(raw_pixels)

    print(f"PNG → DDS (BGRA uncompressed): {src}  →  {dst}")
    return dst


# ── Batch helpers ──────────────────────────────────────────────────────────────

def decode_all_dds_in_dir(src_dir: str, out_dir: str | None = None) -> int:
    """Convert all .dds / .texture files in src_dir to PNG in out_dir."""
    if out_dir is None:
        out_dir = os.path.join(src_dir, 'png')
    os.makedirs(out_dir, exist_ok=True)
    count = 0
    for fname in sorted(os.listdir(src_dir)):
        if fname.lower().endswith(('.dds', '.texture')):
            try:
                dds_to_png(os.path.join(src_dir, fname),
                           os.path.join(out_dir, os.path.splitext(fname)[0] + '.png'))
                count += 1
            except Exception as e:
                print(f"  SKIP {fname}: {e}")
    return count


# ── selftest ──────────────────────────────────────────────────────────────────

def selftest():
    sample = os.path.join(os.path.dirname(__file__), '..', 'Exports', 'samples',
                          'texture_0922825050fea168.texture')
    if not os.path.exists(sample):
        print("texture_tools selftest: SKIP (sample not found)")
        return

    info = dds_info(open(sample, 'rb').read())
    print(f"texture_tools: {info['width']}×{info['height']} {info['format']}")

    tmp_png = '/tmp/_texture_tools_test.png'
    tmp_dds = '/tmp/_texture_tools_test.dds'

    dds_to_png(sample, tmp_png)
    assert os.path.exists(tmp_png), "PNG not created"
    img = Image.open(tmp_png)
    assert img.size == (info['width'], info['height']), f"Size mismatch: {img.size}"

    png_to_dds(tmp_png, tmp_dds, fmt='rgba')
    assert os.path.exists(tmp_dds), "DDS not created"

    for p in [tmp_png, tmp_dds]:
        try:
            os.unlink(p)
        except Exception:
            pass

    print("texture_tools selftest: PASS")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == 'selftest':
        selftest()

    elif cmd == 'decode':
        src = sys.argv[2]
        dst = sys.argv[3] if len(sys.argv) > 3 else None
        dds_to_png(src, dst)

    elif cmd == 'encode':
        src = sys.argv[2]
        dst = sys.argv[3] if len(sys.argv) > 3 else None
        fmt_arg = 'dxt5'
        if '--format' in sys.argv:
            fmt_arg = sys.argv[sys.argv.index('--format') + 1]
        png_to_dds(src, dst, fmt=fmt_arg)

    elif cmd == 'info':
        blob = open(sys.argv[2], 'rb').read()
        info = dds_info(blob)
        print(json.dumps(info, indent=2))

    elif cmd == 'batch':
        src_dir = sys.argv[2]
        out_dir = sys.argv[3] if len(sys.argv) > 3 else None
        n = decode_all_dds_in_dir(src_dir, out_dir)
        print(f"Converted {n} textures")

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
