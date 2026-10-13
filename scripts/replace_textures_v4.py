"""
Replace Textures in Gauntlet Bundles (Version 4 - Complete)

This tool handles all bundle types and automatically resizes textures to match
the original dimensions and format.

Features:
- Auto-detects bundle type (simple vs complex with scattered resources)
- Resizes replacement textures to match original format/dimensions
- Supports both full rebuild (simple bundles) and in-place (complex bundles)
- Preserves all bundle structure including gaps and streaming data

Usage:
    python replace_textures_v4.py <bundle_path> <texture_folder> [--force-inplace]
    
The texture_folder should contain DDS files named with the resource hash:
    <name_hash>.dds  (e.g., 0cb6ec86ddc5c5f7.dds)
"""

# cd <this repo>/scripts
# python replace_textures_v4.py "C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\contents\BundleName" "my_textures\BundleName"

# Temp: python replace_textures_v4.py "C:\Program Files (x86)\Steam\steamapps\common\Gauntlet\contents\ec181385e7000cf1" "my_textures\ec181385e7000cf1"

import struct
import zlib
import os
import sys
from pathlib import Path

TEXTURE_TYPE_HASH = 0xCD4238C6A0C69E32

# ============================================================================
# Bundle Compression/Decompression
# ============================================================================

def decompress_bundle(packed_data):
    """Decompress a zlib-compressed bundle."""
    signature, unzipped_size, padding = struct.unpack('<III', packed_data[:12])
    
    if signature != 0xF0000004:
        raise ValueError(f"Unknown signature: 0x{signature:08x}")
    
    result = bytearray()
    pos = 12
    
    while pos < len(packed_data):
        if pos + 4 > len(packed_data):
            break
        chunk_size = struct.unpack('<I', packed_data[pos:pos+4])[0]
        pos += 4
        
        if chunk_size == 0:
            break
            
        chunk_data = packed_data[pos:pos + chunk_size]
        pos += chunk_size
        
        try:
            decompressed = zlib.decompress(chunk_data)
            result.extend(decompressed)
        except zlib.error as e:
            print(f"Decompression error at offset 0x{pos:x}: {e}")
            break
    
    return bytes(result)


def compress_bundle(data):
    """Compress data into bundle format."""
    CHUNK_SIZE = 65536
    chunks = []
    
    for i in range(0, len(data), CHUNK_SIZE):
        chunk = data[i:i+CHUNK_SIZE]
        compressed = zlib.compress(chunk, level=6)
        chunks.append(compressed)
    
    result = bytearray()
    result.extend(struct.pack('<III', 0xF0000004, len(data), 0))
    
    for chunk in chunks:
        result.extend(struct.pack('<I', len(chunk)))
        result.extend(chunk)
    
    return bytes(result)


# ============================================================================
# Bundle Parsing
# ============================================================================

def parse_bundle(data):
    """Parse bundle structure.
    
    Returns:
        resources: List of resource dicts with offset, type_hash, name_hash, etc.
        entry_table: List of (type_hash, name_hash) in entry table order
        count: Resource count
        is_simple: True if resources are in entry table order
    """
    count = struct.unpack('<I', data[:4])[0]
    header_table_end = 0x104 + count * 16
    
    # Read entry table
    entry_table = []
    entry_set = set()
    for i in range(count):
        pos = 0x104 + i * 16
        type_hash, name_hash = struct.unpack('<QQ', data[pos:pos+16])
        entry_table.append((type_hash, name_hash))
        entry_set.add((type_hash, name_hash))
    
    # Parse resources by scanning for valid headers
    resources = []
    pos = header_table_end
    
    while pos + 36 <= len(data) and len(resources) < count:
        type_hash, name_hash = struct.unpack('<QQ', data[pos:pos+16])
        
        if (type_hash, name_hash) in entry_set:
            flags, stream_size, main_size, unk = struct.unpack('<IQII', data[pos+16:pos+36])
            
            # Validate header
            if flags <= 7 and main_size < 200000000:
                resources.append({
                    'offset': pos,
                    'type_hash': type_hash,
                    'name_hash': name_hash,
                    'flags': flags,
                    'stream_size': stream_size,
                    'main_size': main_size,
                    'unk': unk,
                    'data': data[pos+36:pos+36+main_size],
                })
                pos += 36 + main_size
                continue
        
        pos += 1
    
    # Check if resources are in entry table order (simple bundle)
    is_simple = True
    resources_by_offset = sorted(resources, key=lambda r: r['offset'])
    
    # Check for gaps between resources
    for i in range(1, len(resources_by_offset)):
        prev = resources_by_offset[i-1]
        curr = resources_by_offset[i]
        prev_end = prev['offset'] + 36 + len(prev['data'])
        if curr['offset'] != prev_end:
            is_simple = False
            break
    
    # Also check if order matches entry table
    if is_simple:
        for i, res in enumerate(resources_by_offset):
            if (res['type_hash'], res['name_hash']) != entry_table[i]:
                is_simple = False
                break
    
    return resources, entry_table, count, is_simple


# ============================================================================
# DDS Texture Handling
# ============================================================================

class DDSHeader:
    """Parse and manipulate DDS texture headers."""
    
    # DDS pixel format flags
    DDPF_ALPHAPIXELS = 0x1
    DDPF_FOURCC = 0x4
    DDPF_RGB = 0x40
    
    def __init__(self, data):
        if data[:4] != b'DDS ':
            raise ValueError("Not a valid DDS file")
        
        self.raw_header = data[:128]
        
        # Parse header
        (self.size, self.flags, self.height, self.width,
         self.pitch_or_linear_size, self.depth, self.mip_count) = struct.unpack(
            '<IIIIIII', data[4:32])
        
        # Pixel format at offset 76
        (self.pf_size, self.pf_flags, self.fourcc,
         self.rgb_bit_count, self.r_mask, self.g_mask,
         self.b_mask, self.a_mask) = struct.unpack('<II4sIIIII', data[76:108])
        
        self.fourcc = self.fourcc.rstrip(b'\x00')
    
    @property
    def is_compressed(self):
        return bool(self.pf_flags & self.DDPF_FOURCC)
    
    @property
    def format_name(self):
        if self.is_compressed:
            return self.fourcc.decode('ascii', errors='replace')
        return f"RGB{self.rgb_bit_count}"
    
    def calculate_size(self):
        """Calculate expected data size based on format and dimensions."""
        if self.fourcc in (b'DXT1', b'BC1'):
            block_size = 8
        elif self.fourcc in (b'DXT3', b'DXT5', b'BC2', b'BC3', b'ATI2', b'BC5'):
            block_size = 16
        else:
            # Uncompressed
            return self.width * self.height * (self.rgb_bit_count // 8)
        
        # Calculate size with mipmaps
        total_size = 0
        w, h = self.width, self.height
        for _ in range(max(1, self.mip_count)):
            blocks_w = max(1, (w + 3) // 4)
            blocks_h = max(1, (h + 3) // 4)
            total_size += blocks_w * blocks_h * block_size
            w = max(1, w // 2)
            h = max(1, h // 2)
        
        return total_size


def create_solid_dds(width, height, format_fourcc, mip_count, color_rgb565):
    """Create a solid color DDS texture matching the specified format.
    
    Args:
        width, height: Texture dimensions
        format_fourcc: b'DXT1', b'DXT5', etc.
        mip_count: Number of mipmap levels
        color_rgb565: Color as RGB565 value (e.g., 0xF800 for red)
    
    Returns:
        Complete DDS file as bytes
    """
    # Build DDS header
    header = bytearray(128)
    header[0:4] = b'DDS '
    
    # DDS_HEADER
    struct.pack_into('<I', header, 4, 124)  # size
    struct.pack_into('<I', header, 8, 0x000A1007)  # flags: CAPS|HEIGHT|WIDTH|PIXELFORMAT|MIPMAPCOUNT|LINEARSIZE
    struct.pack_into('<I', header, 12, height)
    struct.pack_into('<I', header, 16, width)
    
    # Calculate pitch/linear size
    if format_fourcc == b'DXT1':
        block_size = 8
    else:
        block_size = 16
    
    blocks_w = max(1, (width + 3) // 4)
    linear_size = blocks_w * block_size
    struct.pack_into('<I', header, 20, linear_size)
    
    struct.pack_into('<I', header, 24, 0)  # depth
    struct.pack_into('<I', header, 28, mip_count)
    
    # DDS_PIXELFORMAT at offset 76
    struct.pack_into('<I', header, 76, 32)  # size
    struct.pack_into('<I', header, 80, 0x4)  # flags: FOURCC
    header[84:88] = format_fourcc.ljust(4, b'\x00')
    
    # Caps
    struct.pack_into('<I', header, 108, 0x401008)  # TEXTURE | MIPMAP | COMPLEX
    
    # Generate pixel data
    pixel_data = bytearray()
    w, h = width, height
    
    for mip in range(max(1, mip_count)):
        blocks_w = max(1, (w + 3) // 4)
        blocks_h = max(1, (h + 3) // 4)
        
        for _ in range(blocks_w * blocks_h):
            if format_fourcc == b'DXT1':
                # DXT1: 2 colors (4 bytes) + 4 bytes indices
                block = struct.pack('<HH', color_rgb565, color_rgb565) + b'\x00\x00\x00\x00'
            else:
                # DXT5: 8 bytes alpha + 8 bytes color (same as DXT1 color block)
                alpha_block = b'\xff\xff\x00\x00\x00\x00\x00\x00'  # Solid alpha
                color_block = struct.pack('<HH', color_rgb565, color_rgb565) + b'\x00\x00\x00\x00'
                block = alpha_block + color_block
            pixel_data.extend(block)
        
        w = max(1, w // 2)
        h = max(1, h // 2)
    
    return bytes(header) + bytes(pixel_data)


def rgb888_to_rgb565(r, g, b):
    """Convert 8-bit RGB to RGB565."""
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def rgb565_to_rgb888(c):
    """Convert RGB565 to 8-bit RGB tuple."""
    r = ((c >> 11) & 0x1F) * 255 // 31
    g = ((c >> 5) & 0x3F) * 255 // 63
    b = (c & 0x1F) * 255 // 31
    return (r, g, b)


def color_distance_sq(c1, c2):
    """Squared distance between two RGB tuples."""
    return (c1[0]-c2[0])**2 + (c1[1]-c2[1])**2 + (c1[2]-c2[2])**2


def compress_dxt1_block(pixels):
    """Compress a 4x4 block of RGB pixels to DXT1 format.
    
    Args:
        pixels: List of 16 (r, g, b) tuples in row-major order
        
    Returns:
        8 bytes of DXT1 compressed data
    """
    # Find min/max colors (simple bounding box method)
    min_r = min_g = min_b = 255
    max_r = max_g = max_b = 0
    
    for r, g, b in pixels:
        min_r, min_g, min_b = min(min_r, r), min(min_g, g), min(min_b, b)
        max_r, max_g, max_b = max(max_r, r), max(max_g, g), max(max_b, b)
    
    # Convert to RGB565
    color0 = rgb888_to_rgb565(max_r, max_g, max_b)
    color1 = rgb888_to_rgb565(min_r, min_g, min_b)
    
    # Ensure color0 > color1 for 4-color mode (no alpha)
    if color0 < color1:
        color0, color1 = color1, color0
    elif color0 == color1:
        # Solid color block
        return struct.pack('<HHI', color0, color1, 0)
    
    # Generate palette
    c0 = rgb565_to_rgb888(color0)
    c1 = rgb565_to_rgb888(color1)
    palette = [
        c0,
        c1,
        ((2*c0[0] + c1[0])//3, (2*c0[1] + c1[1])//3, (2*c0[2] + c1[2])//3),
        ((c0[0] + 2*c1[0])//3, (c0[1] + 2*c1[1])//3, (c0[2] + 2*c1[2])//3),
    ]
    
    # Find best index for each pixel
    indices = 0
    for i, pixel in enumerate(pixels):
        best_idx = 0
        best_dist = color_distance_sq(pixel, palette[0])
        for idx in range(1, 4):
            dist = color_distance_sq(pixel, palette[idx])
            if dist < best_dist:
                best_dist = dist
                best_idx = idx
        indices |= (best_idx << (i * 2))
    
    return struct.pack('<HHI', color0, color1, indices)


# ---------------------------
# DXT1 / DXT5 helpers
# ---------------------------

def decode_dxt1_block(block):
    """Decode an 8-byte DXT1 block into 16 (r,g,b,a) pixels."""
    color0, color1, indices = struct.unpack('<HHI', block)
    c0 = rgb565_to_rgb888(color0)
    c1 = rgb565_to_rgb888(color1)

    palette = [c0, c1]
    if color0 > color1:
        palette.append(((2*c0[0] + c1[0]) // 3, (2*c0[1] + c1[1]) // 3, (2*c0[2] + c1[2]) // 3))
        palette.append(((c0[0] + 2*c1[0]) // 3, (c0[1] + 2*c1[1]) // 3, (c0[2] + 2*c1[2]) // 3))
    else:
        # 3-color + 1 transparent
        palette.append(((c0[0] + c1[0]) // 2, (c0[1] + c1[1]) // 2, (c0[2] + c1[2]) // 2))
        palette.append((0, 0, 0))

    pixels = []
    for i in range(16):
        idx = (indices >> (2 * i)) & 3
        r, g, b = palette[idx]
        if idx == 3 and color0 <= color1:
            a = 0
        else:
            a = 255
        pixels.append((r, g, b, a))
    return pixels


def decode_dxt5_alpha_block(block):
    """Decode the 8-byte alpha block of DXT5 into 16 alpha values."""
    a0 = block[0]
    a1 = block[1]
    bits = int.from_bytes(block[2:8], 'little')

    alphas = [a0, a1]
    if a0 > a1:
        # 6 interpolated values
        for i in range(1, 7):
            alphas.append((( (7 - i) * a0 + i * a1 ) // 7))
    else:
        # 4 interpolated values, then 0 and 255
        for i in range(1, 5):
            alphas.append((( (5 - i) * a0 + i * a1 ) // 5))
        alphas += [0, 255]

    result = []
    for i in range(16):
        idx = (bits >> (3 * i)) & 0x7
        result.append(alphas[idx])
    return result


def decode_dxt5_block(block):
    """Decode 16-byte DXT5 block into 16 (r,g,b,a) pixels."""
    alpha_block = block[:8]
    color_block = block[8:16]
    alphas = decode_dxt5_alpha_block(alpha_block)
    colors = decode_dxt1_block(color_block)

    pixels = []
    for i in range(16):
        r, g, b, _ = colors[i]
        a = alphas[i]
        pixels.append((r, g, b, a))
    return pixels


def compress_dxt5_alpha_block(alphas):
    """Encode 16 alpha values to an 8-byte DXT5 alpha block."""
    a0 = max(alphas)
    a1 = min(alphas)

    # Build palette
    if a0 > a1:
        palette = [a0, a1]
        for i in range(1, 7):
            palette.append((( (7 - i) * a0 + i * a1 ) // 7))
    else:
        palette = [a0, a1]
        for i in range(1, 5):
            palette.append((( (5 - i) * a0 + i * a1 ) // 5))
        palette += [0, 255]

    idx_bits = 0
    for i, a in enumerate(alphas):
        # Choose best index
        best_idx = 0
        best_err = abs(a - palette[0])
        for j in range(1, 8):
            err = abs(a - palette[j])
            if err < best_err:
                best_err = err
                best_idx = j
        idx_bits |= (best_idx & 0x7) << (3 * i)

    return bytes([a0, a1]) + idx_bits.to_bytes(6, 'little')


def compress_dxt5_block(pixels):
    """Compress 4x4 RGBA pixels to a 16-byte DXT5 block."""
    # Alpha block
    alphas = [p[3] for p in pixels]
    alpha_block = compress_dxt5_alpha_block(alphas)

    # Color block uses DXT1 compression for color portion
    color_pixels = [(p[0], p[1], p[2]) for p in pixels]
    color_block = compress_dxt1_block(color_pixels)

    return alpha_block + color_block


def compress_rgba_to_dxt5(pixels, width, height, mip_count):
    """Compress RGBA pixel data to DXT5 with mipmaps."""
    result = bytearray()
    current_pixels = pixels
    current_width = width
    current_height = height

    for mip in range(mip_count):
        blocks_w = max(1, (current_width + 3) // 4)
        blocks_h = max(1, (current_height + 3) // 4)

        for by in range(blocks_h):
            for bx in range(blocks_w):
                block_pixels = []
                for py in range(4):
                    for px in range(4):
                        x = min(bx * 4 + px, current_width - 1)
                        y = min(by * 4 + py, current_height - 1)
                        rgba = current_pixels[y * current_width + x]
                        block_pixels.append(rgba)

                result.extend(compress_dxt5_block(block_pixels))

        if mip < mip_count - 1:
            current_pixels, current_width, current_height = downsample_mipmap(
                current_pixels, current_width, current_height
            )

    return bytes(result)


def convert_to_dxt5(replacement_dds, orig_header):
    """Convert any DDS (compressed/uncompressed) to DXT5 matching original."""
    repl_header = DDSHeader(replacement_dds)

    # Extract pixels from replacement
    pixels = extract_rgba_pixels(replacement_dds, repl_header)

    # Resize if needed (nearest neighbor)
    if repl_header.width != orig_header.width or repl_header.height != orig_header.height:
        src_w, src_h = repl_header.width, repl_header.height
        dst_w, dst_h = orig_header.width, orig_header.height

        new_pixels = []
        for y in range(dst_h):
            for x in range(dst_w):
                sx = int(x * src_w / dst_w)
                sy = int(y * src_h / dst_h)
                sx = min(sx, src_w - 1)
                sy = min(sy, src_h - 1)
                new_pixels.append(pixels[sy * src_w + sx])
        pixels = new_pixels

    # Ensure we have correct number of top-level pixels
    if len(pixels) != orig_header.width * orig_header.height:
        # Fallback fill with magenta
        pixels = [(255, 0, 255, 255)] * (orig_header.width * orig_header.height)

    compressed = compress_rgba_to_dxt5(
        pixels,
        orig_header.width,
        orig_header.height,
        max(1, orig_header.mip_count)
    )

    # Build DDS header matching original
    header = bytearray(128)
    header[0:4] = b'DDS '

    struct.pack_into('<I', header, 4, 124)  # size
    struct.pack_into('<I', header, 8, 0x000A1007)  # flags
    struct.pack_into('<I', header, 12, orig_header.height)
    struct.pack_into('<I', header, 16, orig_header.width)

    blocks_w = max(1, (orig_header.width + 3) // 4)
    linear_size = blocks_w * 16  # 16 bytes per DXT5 block
    struct.pack_into('<I', header, 20, linear_size)

    struct.pack_into('<I', header, 24, 0)  # depth
    struct.pack_into('<I', header, 28, orig_header.mip_count)

    # Pixel format
    struct.pack_into('<I', header, 76, 32)  # pf size
    struct.pack_into('<I', header, 80, 0x4)  # pf flags: FOURCC
    header[84:88] = b'DXT5'

    # Caps
    struct.pack_into('<I', header, 108, 0x401008)

    return bytes(header) + compressed


# ---------------------------
# Extract pixels (supports uncompressed, DXT1, DXT5)
# ---------------------------

def extract_rgba_pixels(dds_data, header):
    """Extract RGBA pixels from a DDS file.

    Returns list of (r, g, b, a) tuples in row-major order for the top mip level.
    """
    pixel_data = dds_data[128:]
    width, height = header.width, header.height

    # Compressed formats (DXT1, DXT5)
    if header.is_compressed:
        fourcc = header.fourcc
        if fourcc in (b'DXT1', b'BC1'):
            block_size = 8
            blocks_w = max(1, (width + 3) // 4)
            blocks_h = max(1, (height + 3) // 4)
            expected = blocks_w * blocks_h * block_size
            data0 = pixel_data[:expected]

            pixels = [(0, 0, 0, 255)] * (width * height)
            pos = 0
            for by in range(blocks_h):
                for bx in range(blocks_w):
                    block = data0[pos:pos+8]
                    pos += 8
                    decoded = decode_dxt1_block(block)
                    for py in range(4):
                        for px in range(4):
                            x = bx * 4 + px
                            y = by * 4 + py
                            if x < width and y < height:
                                pixels[y * width + x] = decoded[py * 4 + px]
            return pixels

        if fourcc == b'DXT5':
            block_size = 16
            blocks_w = max(1, (width + 3) // 4)
            blocks_h = max(1, (height + 3) // 4)
            expected = blocks_w * blocks_h * block_size
            data0 = pixel_data[:expected]

            pixels = [(0, 0, 0, 255)] * (width * height)
            pos = 0
            for by in range(blocks_h):
                for bx in range(blocks_w):
                    block = data0[pos:pos+16]
                    pos += 16
                    decoded = decode_dxt5_block(block)
                    for py in range(4):
                        for px in range(4):
                            x = bx * 4 + px
                            y = by * 4 + py
                            if x < width and y < height:
                                pixels[y * width + x] = decoded[py * 4 + px]
            return pixels

    # Uncompressed formats
    pixels = []
    if header.rgb_bit_count == 32:  # BGRA8888
        for y in range(height):
            for x in range(width):
                offset = (y * width + x) * 4
                if offset + 4 <= len(pixel_data):
                    b, g, r, a = struct.unpack('BBBB', pixel_data[offset:offset+4])
                    pixels.append((r, g, b, a))
                else:
                    pixels.append((0, 0, 0, 255))
        return pixels

    if header.rgb_bit_count == 24:  # BGR888
        for y in range(height):
            for x in range(width):
                offset = (y * width + x) * 3
                if offset + 3 <= len(pixel_data):
                    b, g, r = struct.unpack('BBB', pixel_data[offset:offset+3])
                    pixels.append((r, g, b, 255))
                else:
                    pixels.append((0, 0, 0, 255))
        return pixels

    # Fallback - fill with magenta (error color)
    return [(255, 0, 255, 255)] * (width * height)


def downsample_mipmap(pixels, width, height):
    """Generate next mipmap level by averaging 2x2 blocks.
    
    Returns (new_pixels, new_width, new_height)
    """
    new_width = max(1, width // 2)
    new_height = max(1, height // 2)
    new_pixels = []
    
    for y in range(new_height):
        for x in range(new_width):
            # Sample 2x2 block
            samples = []
            for dy in range(2):
                for dx in range(2):
                    sx = min(x * 2 + dx, width - 1)
                    sy = min(y * 2 + dy, height - 1)
                    samples.append(pixels[sy * width + sx])
            
            # Average
            r = sum(s[0] for s in samples) // 4
            g = sum(s[1] for s in samples) // 4
            b = sum(s[2] for s in samples) // 4
            a = sum(s[3] for s in samples) // 4
            new_pixels.append((r, g, b, a))
    
    return new_pixels, new_width, new_height


def compress_rgba_to_dxt1(pixels, width, height, mip_count):
    """Compress RGBA pixel data to DXT1 with mipmaps.
    
    Returns compressed pixel data (no header).
    """
    result = bytearray()
    current_pixels = pixels
    current_width = width
    current_height = height
    
    for mip in range(mip_count):
        # Compress this mip level
        blocks_w = max(1, (current_width + 3) // 4)
        blocks_h = max(1, (current_height + 3) // 4)
        
        for by in range(blocks_h):
            for bx in range(blocks_w):
                # Extract 4x4 block
                block_pixels = []
                for py in range(4):
                    for px in range(4):
                        x = min(bx * 4 + px, current_width - 1)
                        y = min(by * 4 + py, current_height - 1)
                        rgba = current_pixels[y * current_width + x]
                        block_pixels.append((rgba[0], rgba[1], rgba[2]))
                
                result.extend(compress_dxt1_block(block_pixels))
        
        # Generate next mip level
        if mip < mip_count - 1:
            current_pixels, current_width, current_height = downsample_mipmap(
                current_pixels, current_width, current_height
            )
    
    return bytes(result)


def convert_to_dxt1(replacement_dds, orig_header):
    """Convert an uncompressed DDS to DXT1 matching original format.
    
    Args:
        replacement_dds: Raw bytes of replacement DDS file
        orig_header: DDSHeader of the original texture
        
    Returns:
        Complete DDS file as bytes matching original format/size
    """
    repl_header = DDSHeader(replacement_dds)
    
    # Extract pixels from replacement
    pixels = extract_rgba_pixels(replacement_dds, repl_header)
    
    # Handle dimension mismatch - resize if needed
    if repl_header.width != orig_header.width or repl_header.height != orig_header.height:
        # Simple resize using nearest neighbor
        src_w, src_h = repl_header.width, repl_header.height
        dst_w, dst_h = orig_header.width, orig_header.height
        
        new_pixels = []
        for y in range(dst_h):
            for x in range(dst_w):
                sx = int(x * src_w / dst_w)
                sy = int(y * src_h / dst_h)
                sx = min(sx, src_w - 1)
                sy = min(sy, src_h - 1)
                new_pixels.append(pixels[sy * src_w + sx])
        pixels = new_pixels
    
    # Compress to DXT1
    compressed = compress_rgba_to_dxt1(
        pixels, 
        orig_header.width, 
        orig_header.height,
        max(1, orig_header.mip_count)
    )
    
    # Build DDS header matching original
    header = bytearray(128)
    header[0:4] = b'DDS '
    
    struct.pack_into('<I', header, 4, 124)  # size
    struct.pack_into('<I', header, 8, 0x000A1007)  # flags
    struct.pack_into('<I', header, 12, orig_header.height)
    struct.pack_into('<I', header, 16, orig_header.width)
    
    blocks_w = max(1, (orig_header.width + 3) // 4)
    linear_size = blocks_w * 8  # 8 bytes per DXT1 block
    struct.pack_into('<I', header, 20, linear_size)
    
    struct.pack_into('<I', header, 24, 0)  # depth
    struct.pack_into('<I', header, 28, orig_header.mip_count)
    
    # Pixel format
    struct.pack_into('<I', header, 76, 32)  # pf size
    struct.pack_into('<I', header, 80, 0x4)  # pf flags: FOURCC
    header[84:88] = b'DXT1'
    
    # Caps
    struct.pack_into('<I', header, 108, 0x401008)
    
    return bytes(header) + compressed


def resize_dds_to_match(replacement_dds, original_dds):
    """Resize/reformat replacement DDS to match original format and size.
    
    Properly converts uncompressed textures to DXT1 with full detail.
    """
    try:
        orig_header = DDSHeader(original_dds)
        repl_header = DDSHeader(replacement_dds)
    except ValueError as e:
        print(f"  Warning: Invalid DDS - {e}")
        return None
    
    # Check if already matching exactly
    if (repl_header.width == orig_header.width and
        repl_header.height == orig_header.height and
        repl_header.fourcc == orig_header.fourcc and
        repl_header.mip_count == orig_header.mip_count and
        len(replacement_dds) == len(original_dds)):
        return replacement_dds
    
    repl_format = repl_header.format_name if repl_header.fourcc else f"RGBA{repl_header.rgb_bit_count}"
    orig_format = orig_header.format_name
    
    print(f"  Converting: {repl_header.width}x{repl_header.height} {repl_format} (mips:{repl_header.mip_count}) -> "
          f"{orig_header.width}x{orig_header.height} {orig_format} (mips:{orig_header.mip_count})")
    
    # Handle conversion to DXT1 (accept compressed or uncompressed replacements)
    if orig_header.fourcc == b'DXT1':
        try:
            new_dds = convert_to_dxt1(replacement_dds, orig_header)
        except Exception as e:
            print(f"  Warning: DXT1 conversion failed: {e}")
            new_dds = None

        if new_dds:
            # Ensure exact size match
            if len(new_dds) < len(original_dds):
                new_dds = new_dds + b'\x00' * (len(original_dds) - len(new_dds))
            elif len(new_dds) > len(original_dds):
                new_dds = new_dds[:len(original_dds)]

            print(f"  Compressed to DXT1: {len(new_dds)} bytes (target: {len(original_dds)})")
            return new_dds

    # Handle various -> DXT5 conversion with full detail
    if orig_header.fourcc == b'DXT5':
        try:
            new_dds = convert_to_dxt5(replacement_dds, orig_header)
        except Exception as e:
            print(f"  Warning: DXT5 conversion failed: {e}")
            new_dds = None

        if new_dds:
            if len(new_dds) < len(original_dds):
                new_dds = new_dds + b'\x00' * (len(original_dds) - len(new_dds))
            elif len(new_dds) > len(original_dds):
                new_dds = new_dds[:len(original_dds)]

            print(f"  Compressed to DXT5: {len(new_dds)} bytes (target: {len(original_dds)})")
            return new_dds
    
    # For other format mismatches, fall back to solid color
    print(f"  Warning: Format conversion from {repl_format} to {orig_format} not fully supported")
    print(f"  Creating solid color fallback...")
    
    # Extract a representative color
    if not repl_header.is_compressed and repl_header.rgb_bit_count == 32:
        pixels = extract_rgba_pixels(replacement_dds, repl_header)
        if pixels:
            # Average color
            r = sum(p[0] for p in pixels) // len(pixels)
            g = sum(p[1] for p in pixels) // len(pixels)
            b = sum(p[2] for p in pixels) // len(pixels)
            color_rgb565 = rgb888_to_rgb565(r, g, b)
        else:
            color_rgb565 = 0xFFFF
    else:
        color_rgb565 = 0xFFFF
    
    target_fourcc = orig_header.fourcc if orig_header.fourcc else b'DXT1'
    new_dds = create_solid_dds(
        orig_header.width,
        orig_header.height,
        target_fourcc,
        orig_header.mip_count,
        color_rgb565
    )
    
    if len(new_dds) < len(original_dds):
        new_dds = new_dds + b'\x00' * (len(original_dds) - len(new_dds))
    elif len(new_dds) > len(original_dds):
        new_dds = new_dds[:len(original_dds)]
    
    return new_dds


# ============================================================================
# Bundle Rebuilding
# ============================================================================

def rebuild_simple_bundle(resources, entry_table, original_header, original_trailing):
    """Rebuild a simple bundle where resources are in entry table order.
    
    This allows size changes since we're rebuilding the entire data section.
    """
    count = len(resources)
    result = bytearray()
    
    # Use original header (preserves hash table)
    result.extend(original_header[:0x104])
    struct.pack_into('<I', result, 0, count)
    
    # Entry table - in original order
    for type_hash, name_hash in entry_table:
        result.extend(struct.pack('<QQ', type_hash, name_hash))
    
    # Resource data - in entry table order
    entry_to_resource = {(r['type_hash'], r['name_hash']): r for r in resources}
    
    for type_hash, name_hash in entry_table:
        res = entry_to_resource.get((type_hash, name_hash))
        if res:
            result.extend(struct.pack('<QQ', res['type_hash'], res['name_hash']))
            result.extend(struct.pack('<I', res['flags']))
            result.extend(struct.pack('<Q', res['stream_size']))
            result.extend(struct.pack('<II', len(res['data']), res['unk']))
            result.extend(res['data'])
    
    # Add trailing data
    result.extend(original_trailing)
    
    return bytes(result)


def replace_inplace(data, resources, replacements):
    """Replace textures in-place within the bundle data.
    
    For complex bundles with gaps, we must preserve exact positions.
    Replacement textures are resized to match original size.
    """
    data = bytearray(data)
    replaced = 0
    
    for res in resources:
        if res['type_hash'] != TEXTURE_TYPE_HASH:
            continue
        if res['name_hash'] not in replacements:
            continue
        
        original_dds = res['data']
        replacement_dds = replacements[res['name_hash']]
        
        # Resize replacement to match original
        new_dds = resize_dds_to_match(replacement_dds, original_dds)
        if new_dds is None:
            print(f"  Skipping 0x{res['name_hash']:016x} - resize failed")
            continue
        
        # Ensure exact size match
        if len(new_dds) != len(original_dds):
            # Pad or truncate
            if len(new_dds) < len(original_dds):
                new_dds = new_dds + b'\x00' * (len(original_dds) - len(new_dds))
            else:
                new_dds = new_dds[:len(original_dds)]
        
        # Write in-place
        dds_start = res['offset'] + 36
        data[dds_start:dds_start + len(new_dds)] = new_dds
        
        print(f"  Replaced 0x{res['name_hash']:016x} at 0x{res['offset']:x}")
        replaced += 1
    
    return bytes(data), replaced


# ============================================================================
# Texture Loading
# ============================================================================

def load_replacement_textures(folder_path):
    """Load replacement textures from folder."""
    replacements = {}
    
    if not os.path.exists(folder_path):
        print(f"Texture folder not found: {folder_path}")
        return replacements
    
    for filename in os.listdir(folder_path):
        if filename.lower().endswith('.dds'):
            hash_str = filename[:-4].lower()
            try:
                name_hash = int(hash_str, 16)
                filepath = os.path.join(folder_path, filename)
                with open(filepath, 'rb') as f:
                    dds_data = f.read()
                
                # Validate DDS
                if dds_data[:4] == b'DDS ':
                    replacements[name_hash] = dds_data
                    try:
                        header = DDSHeader(dds_data)
                        print(f"  Loaded: {filename} ({header.width}x{header.height} {header.format_name})")
                    except:
                        print(f"  Loaded: {filename} ({len(dds_data)} bytes)")
                else:
                    print(f"  Skipping {filename} - not a valid DDS file")
            except ValueError:
                print(f"  Skipping {filename} - invalid hash in filename")
    
    return replacements


# ============================================================================
# Main
# ============================================================================

def main():
    if len(sys.argv) < 3:
        print("Gauntlet Texture Replacer v4")
        print()
        print("Usage: python replace_textures_v4.py <bundle_path> <texture_folder> [options]")
        print()
        print("Options:")
        print("  --force-inplace  Force in-place replacement even for simple bundles")
        print("  --dry-run        Show what would be replaced without modifying")
        print()
        print("The texture_folder should contain DDS files named with the resource hash:")
        print("  <name_hash>.dds  (e.g., 01f03948e18b4899.dds)")
        sys.exit(1)
    
    bundle_path = sys.argv[1]
    texture_folder = sys.argv[2]
    force_inplace = '--force-inplace' in sys.argv
    dry_run = '--dry-run' in sys.argv
    
    # Load bundle
    print(f"Loading bundle: {bundle_path}")
    with open(bundle_path, 'rb') as f:
        packed_data = f.read()
    
    print(f"  Compressed: {len(packed_data):,} bytes")
    
    # Check for stream file
    stream_path = bundle_path + '.stream'
    has_stream = os.path.exists(stream_path)
    if has_stream:
        print(f"  Has .stream file: {os.path.getsize(stream_path):,} bytes")
    
    # Decompress
    data = decompress_bundle(packed_data)
    print(f"  Decompressed: {len(data):,} bytes")
    
    # Parse bundle
    print("\nParsing bundle...")
    resources, entry_table, count, is_simple = parse_bundle(data)
    print(f"  Resources: {len(resources)} / {count}")
    print(f"  Bundle type: {'simple (ordered)' if is_simple else 'complex (scattered)'}")
    
    # Count textures
    texture_count = sum(1 for r in resources if r['type_hash'] == TEXTURE_TYPE_HASH)
    print(f"  Textures: {texture_count}")
    
    # Load replacements
    print("\nLoading replacement textures...")
    replacements = load_replacement_textures(texture_folder)
    
    if not replacements:
        print("\nNo valid replacement textures found!")
        sys.exit(1)
    
    print(f"\nLoaded {len(replacements)} replacement textures")
    
    # Find matching textures
    matches = []
    for res in resources:
        if res['type_hash'] == TEXTURE_TYPE_HASH and res['name_hash'] in replacements:
            matches.append(res)
    
    print(f"Found {len(matches)} textures to replace")
    
    if not matches:
        print("No matching textures found in bundle!")
        sys.exit(1)
    
    if dry_run:
        print("\nDry run - showing what would be replaced:")
        for res in matches:
            orig_size = len(res['data'])
            repl_size = len(replacements[res['name_hash']])
            print(f"  0x{res['name_hash']:016x}: {orig_size} -> {repl_size} bytes")
        return
    
    # Replace textures
    print("\nReplacing textures...")
    
    if is_simple and not force_inplace:
        # Simple bundle - can rebuild with size changes
        print("  Using full rebuild mode...")
        
        # Calculate trailing data
        resources_by_offset = sorted(resources, key=lambda r: r['offset'])
        last_res = resources_by_offset[-1]
        resource_end = last_res['offset'] + 36 + len(last_res['data'])
        original_trailing = data[resource_end:]
        
        # Replace texture data
        replaced = 0
        for res in resources:
            if res['type_hash'] != TEXTURE_TYPE_HASH:
                continue
            if res['name_hash'] not in replacements:
                continue
            
            original_dds = res['data']
            replacement_dds = replacements[res['name_hash']]
            
            # Resize if needed
            new_dds = resize_dds_to_match(replacement_dds, original_dds)
            if new_dds:
                res['data'] = new_dds
                print(f"  Replaced 0x{res['name_hash']:016x}")
                replaced += 1
        
        # Rebuild
        modified_data = rebuild_simple_bundle(resources, entry_table, data[:0x104], original_trailing)
        
    else:
        # Complex bundle - must use in-place replacement
        print("  Using in-place replacement mode...")
        modified_data, replaced = replace_inplace(data, resources, replacements)
    
    print(f"\nReplaced {replaced} textures")
    
    # Compress
    print("\nCompressing...")
    compressed = compress_bundle(modified_data)
    print(f"  New size: {len(compressed):,} bytes (was {len(packed_data):,})")
    
    # Backup
    backup_path = bundle_path + '.backup'
    if not os.path.exists(backup_path):
        print(f"\nCreating backup: {backup_path}")
        with open(backup_path, 'wb') as f:
            f.write(packed_data)
    
    # Save
    print(f"Writing modified bundle: {bundle_path}")
    with open(bundle_path, 'wb') as f:
        f.write(compressed)
    
    print("\nDone!")


if __name__ == '__main__':
    main()
