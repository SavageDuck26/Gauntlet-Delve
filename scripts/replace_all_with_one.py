#!/usr/bin/env python3
"""
Replace ALL textures in a Gauntlet bundle with a SINGLE source texture.

Usage:
    python replace_all_with_one.py <bundle_path> <source_texture.dds>
    python replace_all_with_one.py <bundle_path> <source_texture.dds> --dry-run

Examples:
    python replace_all_with_one.py "C:\...\contents\0164ad48615ba9ed" purple.dds
    python replace_all_with_one.py "C:\...\contents\07c9b8511b5aff2e" my_texture.dds --dry-run

The tool will:
  1. Parse the bundle to find all texture hashes
  2. Create a temp folder with copies of your texture named by hash
  3. Run replace_textures_v4.py to replace them all
  4. Clean up the temp folder

Your source texture can be ANY size/format - the v4 tool auto-resizes!
"""

import sys
import os
import shutil
import tempfile
import subprocess

def get_texture_hashes(bundle_path):
    """Run list_textures.py and parse the output to get texture hashes."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    list_script = os.path.join(script_dir, "list_textures.py")
    
    result = subprocess.run(
        [sys.executable, list_script, bundle_path],
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        print(f"Error running list_textures.py:")
        print(result.stderr)
        return []
    
    hashes = []
    for line in result.stdout.split('\n'):
        line = line.strip()
        # Look for lines that start with a 16-char hex hash
        if len(line) >= 16 and all(c in '0123456789abcdef' for c in line[:16]):
            texture_hash = line[:16]
            hashes.append(texture_hash)
    
    return hashes

def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    
    bundle_path = sys.argv[1]
    source_texture = sys.argv[2]
    dry_run = "--dry-run" in sys.argv
    
    # Validate inputs
    if not os.path.exists(bundle_path):
        print(f"Error: Bundle not found: {bundle_path}")
        sys.exit(1)
    
    if not os.path.exists(source_texture):
        print(f"Error: Source texture not found: {source_texture}")
        sys.exit(1)
    
    if not source_texture.lower().endswith('.dds'):
        print(f"Warning: Source texture should be a .dds file")
    
    print(f"Bundle: {bundle_path}")
    print(f"Source texture: {source_texture}")
    print()
    
    # Get all texture hashes from the bundle
    print("Scanning bundle for textures...")
    hashes = get_texture_hashes(bundle_path)
    
    if not hashes:
        print("No textures found in bundle!")
        sys.exit(1)
    
    print(f"Found {len(hashes)} textures to replace")
    print()
    
    if dry_run:
        print("DRY RUN - Would replace these textures:")
        for h in hashes[:10]:
            print(f"  {h}.dds")
        if len(hashes) > 10:
            print(f"  ... and {len(hashes) - 10} more")
        print()
        print("Run without --dry-run to apply changes.")
        return
    
    # Create temp directory with copies of the source texture
    temp_dir = tempfile.mkdtemp(prefix="gauntlet_textures_")
    print(f"Creating temp texture folder: {temp_dir}")
    
    try:
        # Copy source texture with each hash name
        print(f"Copying source texture {len(hashes)} times...")
        for texture_hash in hashes:
            dest_path = os.path.join(temp_dir, f"{texture_hash}.dds")
            shutil.copy2(source_texture, dest_path)
        
        print(f"Created {len(hashes)} texture files")
        print()
        
        # Run replace_textures_v4.py
        script_dir = os.path.dirname(os.path.abspath(__file__))
        replace_script = os.path.join(script_dir, "replace_textures_v4.py")
        
        print("Running replace_textures_v4.py...")
        print("=" * 60)
        
        result = subprocess.run(
            [sys.executable, replace_script, bundle_path, temp_dir],
            cwd=script_dir
        )
        
        print("=" * 60)
        
        if result.returncode == 0:
            print()
            print("SUCCESS! All textures replaced.")
            print(f"Backup saved as: {bundle_path}.backup")
        else:
            print()
            print("Error during replacement - check output above")
            
    finally:
        # Clean up temp directory
        print()
        print(f"Cleaning up temp folder...")
        shutil.rmtree(temp_dir, ignore_errors=True)

if __name__ == "__main__":
    main()
