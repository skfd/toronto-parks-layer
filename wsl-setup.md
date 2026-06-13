# WSL2 + tippecanoe setup (one time)

The vector tile step (`python run.py vector`) builds Mapbox Vector Tiles with
**tippecanoe**, which has no native Windows build. It runs inside WSL2 / Ubuntu.
This is a one-time setup; after it, the daily build drives WSL automatically.

## 1. Install WSL2 (skip if already installed)

Check first -- in PowerShell, `wsl --list --verbose`. If an `Ubuntu` distro is
listed, skip to step 2.

Otherwise, in an **Administrator** PowerShell (needs elevation + a reboot):

```powershell
wsl --install -d Ubuntu
```

Reboot when prompted; on the first launch of Ubuntu, choose a UNIX username and
password.

## 2. Install tippecanoe

Ubuntu 24.04 ships tippecanoe (and `tile-join`) as a package, so this is one
command. From a Windows terminal:

```powershell
wsl -d Ubuntu -u root -- bash -lc "apt-get update && apt-get install -y tippecanoe"
```

`wsl -u root` runs as root without a password, so no `sudo` prompt.

## 3. Verify

```powershell
wsl -d Ubuntu -- bash -lc "tippecanoe --version"
```

It should print a version (2.49 or newer). The build can now run
`python run.py vector`.

## Alternative: build tippecanoe from source

Only needed if the packaged version is unavailable or too old. Inside Ubuntu:

```bash
sudo apt-get install -y build-essential libsqlite3-dev zlib1g-dev git
git clone https://github.com/felt/tippecanoe.git ~/tippecanoe
cd ~/tippecanoe && make -j && sudo make install
```
