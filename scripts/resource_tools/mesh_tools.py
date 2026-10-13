"""
Stingray .mesh resource - NOT a standalone type in Gauntlet Slayer Edition.

After scanning all 77 Gauntlet bundle files, NO resources with the .mesh type
hash (0x48FF313713A997A1) were found as standalone resources.

Mesh geometry in Gauntlet is always embedded inside .unit resources.
A single .unit file packages:
  - The compiled LOD mesh data (vertices, indices, UVs, normals)
  - Skeleton/rig references
  - Material slot assignments
  - Physics collision shapes

For mesh extraction and editing, use unit_tools.py:

  python3 resource_tools/unit_tools.py decode  <file.unit>
      -> writes <file.json>   (header, LOD metadata, material refs)
      -> writes <file.obj>    (vertex/face mesh data for import into Blender/Maya)

  python3 resource_tools/unit_tools.py encode  <file.json>
      -> writes <file.unit>   (re-packed binary, byte-exact header)

For full round-trip mesh editing:
  1. Decode unit -> OBJ + JSON
  2. Edit geometry in Blender (import OBJ, modify, export OBJ)
  3. Re-encode: update raw mesh bytes in JSON with new OBJ vertex data
     (requires implementing the Stingray vertex buffer format - see FINDINGS.txt #8B)

Standalone .mesh tools are not needed for Gauntlet modding at this time.
"""

import sys

if __name__ == '__main__':
    print(
        "mesh_tools: No standalone .mesh resources exist in Gauntlet bundles.\n"
        "Mesh data is embedded in .unit files - use unit_tools.py instead.\n"
        "See this file's module docstring for full details."
    )
    sys.exit(0)
