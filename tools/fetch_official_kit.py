from pathlib import Path, PurePosixPath
import shutil, tarfile, urllib.request

root = Path.cwd()
work = root / "work"
work.mkdir(exist_ok=True)
archive = work / "mechfight-kit.tar.gz"
dest = work / "official-kit"
url = "https://www.joinbuilders.org/buildathon/tracks/builders/files/mechfight-kit.tar.gz"
MAX_ARCHIVE = 200 * 1024 * 1024
MAX_EXPANDED = 2 * 1024 * 1024 * 1024
if dest.exists():
    raise SystemExit("Refusing to replace an existing work/official-kit directory.")
req = urllib.request.Request(url, method="HEAD")
with urllib.request.urlopen(req, timeout=40) as response:
    size = int(response.headers.get("Content-Length", "0") or 0)
if size > MAX_ARCHIVE:
    raise SystemExit(f"Archive is {size} bytes; cap is {MAX_ARCHIVE}.")
used = shutil.disk_usage(work).used
free = shutil.disk_usage(work).free
if free < 256 * 1024 * 1024:
    raise SystemExit(f"Less than 256 MiB free; stopping before download ({free} bytes free).")
req = urllib.request.Request(url)
written = 0
with urllib.request.urlopen(req, timeout=90) as response, archive.open("wb") as out:
    while True:
        chunk = response.read(1024 * 1024)
        if not chunk:
            break
        written += len(chunk)
        if written > MAX_ARCHIVE:
            raise SystemExit("Download crossed the 200 MiB archive cap.")
        out.write(chunk)
if size and written != size:
    raise SystemExit(f"Download size mismatch: expected {size}, got {written}.")
with tarfile.open(archive, "r:gz") as tar:
    members = tar.getmembers()
    if len(members) > 10000:
        raise SystemExit(f"Too many archive entries: {len(members)}.")
    total = 0
    for m in members:
        path = PurePosixPath(m.name)
        if path.is_absolute() or ".." in path.parts or m.issym() or m.islnk():
            raise SystemExit(f"Unsafe archive entry: {m.name}")
        if m.isfile():
            total += m.size
        if total > MAX_EXPANDED:
            raise SystemExit(f"Expanded archive exceeds 2 GiB: {total} bytes.")
    dest.mkdir()
    for m in members:
        path = dest.joinpath(*PurePosixPath(m.name).parts)
        if m.isdir():
            path.mkdir(parents=True, exist_ok=True)
        elif m.isfile():
            path.parent.mkdir(parents=True, exist_ok=True)
            src = tar.extractfile(m)
            if src is None:
                raise SystemExit(f"Could not read {m.name}")
            with src, path.open("wb") as out:
                shutil.copyfileobj(src, out)
print(f"Downloaded {written:,} bytes; checked {len(members)} entries and {total:,} expanded bytes.")
for p in dest.rglob("*"):
    if p.is_dir() and (p / "python").is_dir() and (p / "check").is_dir() and (p / "protocol.md").exists():
        print(f"Kit root: {p}")
