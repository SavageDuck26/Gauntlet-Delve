"""Check hashes for known packages"""
from create_texture_package import murmur_hash64

packages = [
    "resource_packages/scripts_base",
    "resource_packages/menu",
    "resource_packages/base",
]

for pkg in packages:
    h = murmur_hash64(pkg)
    print(f"{pkg}: 0x{h:016X}")
