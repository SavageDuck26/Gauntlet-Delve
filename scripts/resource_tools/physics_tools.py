"""
Stingray .physics resource — NOT a standalone type in Gauntlet Slayer Edition.

After scanning all 77 Gauntlet bundle files, NO resources with the .physics type
hash (0x5F7203C8F280DAB8) were found as standalone resources.

Physics collision data in Gauntlet is handled in two ways:

  1. EMBEDDED IN UNIT FILES:
     Each .unit resource contains physics shape descriptors as part of its
     component data. The unit_tools.py decoder exports collision metadata
     embedded in the unit JSON.

  2. LARGE WORLD PHYSICS (type 0x99736BE1FFF739A4):
     An 8.5 MB resource of type 0x99736BE1FFF739A4 exists in level bundles.
     It begins with uint64=34 (likely a count), followed by a hash array.
     This is believed to be a pre-compiled physics world / navigation mesh.
     It cannot currently be decoded or re-encoded without more analysis.

For per-unit collision editing: use unit_tools.py → the 'physics_shapes' key
in the decoded unit JSON lists all collision shapes.

Standalone .physics tools are not needed for Gauntlet modding at this time.
"""

import sys

if __name__ == '__main__':
    print(
        "physics_tools: No standalone .physics resources exist in Gauntlet bundles.\n"
        "Physics data is embedded in .unit files — use unit_tools.py instead.\n"
        "See this file's module docstring for full details."
    )
    sys.exit(0)
