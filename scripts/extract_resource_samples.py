#!/usr/bin/env python3
"""
Extract one raw sample of each Stingray resource type from game bundles.
Output: Exports/samples/<type_hash>_<name_hash>.<type>
"""
import struct, zlib, os, sys

GAME = os.path.expanduser('~/.local/share/Steam/steamapps/common/Gauntlet/contents/')
OUT  = 'Exports/samples/'

TYPES = {
    0xCD4238C6A0C69E32: 'texture',
    0xEAC0B497876ADEDF: 'material',
    0xA14E8DFA2CD117E2: 'lua',
    0xE0A48D0BE9A7453F: 'unit',
    0x18DEAD01056B72E9: 'bones',
    0xCCE8D5B5F5AE333F: 'shader',
    0x931E336D7646CC26: 'animation',
    0xAD9C6D9ED1E5E77A: 'package',
    0x2A690FD348FE9AC5: 'level',
    0x5F7203C8F280DAB8: 'physics',
    0x82645835E6B73232: 'config',
    0x9EFE0A916AAE7880: 'font',
    0x0D972BAB10B40FD3: 'strings',
    0xA8193123526FAD64: 'particles',
    0x27862FE24795319C: 'render_config',
    0x48FF313713A997A1: 'mesh',
}

def decomp(path):
    with open(path,'rb') as f: data = f.read()
    sig = struct.unpack_from('<I',data,0)[0]
    if sig not in (0xF0000004,0xF0000005,0xF0000006): return data
    pos, out = 12, b''
    while pos+4 <= len(data):
        cs = struct.unpack_from('<I',data,pos)[0]; pos += 4
        if cs == 0: break
        try:    out += zlib.decompress(data[pos:pos+cs])
        except: out += data[pos:pos+cs]
        pos += cs
    return out

def extract_samples(max_size=20_000_000):
    os.makedirs(OUT, exist_ok=True)
    found = {}
    bundles = sorted(f for f in os.listdir(GAME) if '.' not in f and os.path.isfile(GAME+f))
    # sort small ones first
    bundles.sort(key=lambda f: os.path.getsize(GAME+f))
    
    for bname in bundles:
        bpath = GAME + bname
        bsz = os.path.getsize(bpath)
        
        try:
            data = decomp(bpath)
            N = struct.unpack_from('<I',data,0)[0]
            if N > 10000 or N == 0: continue
            te = 0x104 + (N+1)*16
            
            # resource-0
            th, nh = struct.unpack_from('<QQ', data, 0x104)
            flags, _, dsz, ssz = struct.unpack_from('<IQII', data, te)
            if th in TYPES and th not in found and dsz > 0:
                tname = TYPES[th]
                blob = data[te+20:te+20+dsz]
                fname = f'{OUT}{tname}_{nh:016x}.{tname}'
                with open(fname,'wb') as f: f.write(blob)
                found[th] = fname
                print(f'  ✓ {tname:16s}  {dsz:10,d} bytes  from {bname}  ({bsz//1024}kB bundle)')
            
            # resources 1..N-1
            off = te + 20 + dsz
            for i in range(1, N):
                th, nh, flags, _, dsz, ssz = struct.unpack_from('<QQIQII', data, off)
                if th in TYPES and th not in found and dsz > 0:
                    tname = TYPES[th]
                    blob = data[off+36:off+36+dsz]
                    fname = f'{OUT}{tname}_{nh:016x}.{tname}'
                    with open(fname,'wb') as f: f.write(blob)
                    found[th] = fname
                    print(f'  ✓ {tname:16s}  {dsz:10,d} bytes  from {bname}  ({bsz//1024}kB bundle)')
                off += 36 + dsz
        except Exception as e:
            pass
        
        if len(found) >= len(TYPES): break
    
    print(f'\nFound {len(found)}/{len(TYPES)} types')
    missing = set(TYPES) - set(found)
    for th in missing:
        print(f'  MISSING: {TYPES[th]}  ({th:#018x})')

if __name__ == '__main__':
    print(f'Extracting resource samples...')
    extract_samples()
