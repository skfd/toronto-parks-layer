"""Build vector (MVT) tiles by driving tippecanoe inside WSL.

tippecanoe does not run natively on Windows, so this module shells out to
`wsl.exe`. See wsl-setup.md for the one-time WSL + tippecanoe install.
"""

import os
import shutil
import subprocess

from src import config

# tile-join writes thousands of small files; doing that on the WSL filesystem
# and copying the tree out afterwards is far faster than writing onto /mnt/c.
WSL_PBF_DIR = "/tmp/toronto-parks-vector-tiles"


def build_vector(slim_path=None):
    """Run tippecanoe + tile-join, producing build/site/tiles/vector/{z}/{x}/{y}.pbf.

    Returns the number of .pbf files produced.
    """
    slim_path = slim_path or config.LAYER_SLIM_PATH
    if not os.path.isfile(slim_path):
        raise RuntimeError(f"Slim GeoJSONL not found: {slim_path}. Run 'slim' first.")
    os.makedirs(config.BUILD_DIR, exist_ok=True)

    slim_wsl = win_to_wsl(slim_path)
    mbtiles_wsl = win_to_wsl(config.MBTILES_PATH)

    tippecanoe = (
        f"tippecanoe -o '{mbtiles_wsl}' "
        f"-Z{config.VECTOR_MINZOOM} -z{config.VECTOR_MAXZOOM} "
        f"--no-tile-size-limit --no-feature-limit "
        f"-l {config.VECTOR_LAYER_NAME} -n 'Toronto Parks (Green Spaces)' "
        f"-A '{config.ATTRIBUTION}' --force '{slim_wsl}'"
    )
    print("Running tippecanoe ...")
    stderr = _wsl(tippecanoe)
    dropped = [ln for ln in stderr.splitlines() if "dropping" in ln.lower()]
    if dropped:
        print("WARNING: tippecanoe reported dropped features:")
        for line in dropped:
            print(f"  {line}")

    # Clear the Windows output tree *before* exploding. Deleting a large tile tree
    # takes minutes, and WSL_PBF_DIR lives in the WSL2 VM, which shuts itself down
    # after ~60s idle (vmIdleTimeout) -- so doing it between tile-join and the copy
    # loses the tiles we just wrote. Nothing below leaves WSL idle for long.
    if os.path.isdir(config.VECTOR_TILE_DIR):
        shutil.rmtree(config.VECTOR_TILE_DIR)
    os.makedirs(config.VECTOR_TILE_DIR, exist_ok=True)

    print("Exploding mbtiles to a pbf directory ...")
    _wsl(
        f"rm -rf '{WSL_PBF_DIR}' && "
        f"tile-join -e '{WSL_PBF_DIR}' --no-tile-compression '{mbtiles_wsl}'"
    )

    print("Copying tiles from WSL to the build output ...")
    _wsl(f"cp -r '{WSL_PBF_DIR}/.' '{win_to_wsl(config.VECTOR_TILE_DIR)}/'")

    pbf_count = sum(
        1
        for _, _, files in os.walk(config.VECTOR_TILE_DIR)
        for name in files
        if name.endswith(".pbf")
    )
    print(f"Vector tiles: {pbf_count:,} .pbf files in {config.VECTOR_TILE_DIR}")
    if pbf_count == 0:
        raise RuntimeError("tippecanoe produced no vector tiles.")
    return pbf_count


def win_to_wsl(path):
    """Convert a Windows path to its /mnt/<drive> WSL equivalent."""
    drive, rest = os.path.splitdrive(os.path.abspath(path))
    return f"/mnt/{drive.rstrip(':').lower()}{rest.replace(chr(92), '/')}"


def _wsl(command):
    """Run a bash command inside WSL. Returns stderr; raises on failure."""
    result = subprocess.run(
        ["wsl", "-d", config.WSL_DISTRO, "bash", "-lc", command],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.stdout:
        print(result.stdout.rstrip())
    if result.returncode != 0:
        print(result.stderr.rstrip())
        raise RuntimeError(
            f"WSL command failed (exit {result.returncode}). "
            f"Is WSL set up? See wsl-setup.md."
        )
    return result.stderr or ""
