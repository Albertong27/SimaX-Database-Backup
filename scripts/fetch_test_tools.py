"""Fetch pinned Windows test binaries into build/native-tools; no installation."""

import hashlib
import os
from pathlib import Path
import urllib.request
import zipfile


ROOT = Path(__file__).resolve().parents[1] / "build/native-tools"
PACKAGES = (
    ("postgresql-17.11.zip", "postgresql", "https://get.enterprisedb.com/postgresql/postgresql-17.11-3-windows-x64-binaries.zip",
     "4b8db0930c38f6ef845db919551dedda3b6b845aeb0927b3d79a6e8e9e4537cf"),
    ("mysql-8.4.11.zip", "mysql", "https://cdn.mysql.com/Downloads/MySQL-8.4/mysql-8.4.11-winx64.zip",
     "a492371d687d2bab088b0062581144a0044b8964baefdf4faa579292b423d25c"),
)


def main():
    if os.name != "nt":
        raise SystemExit("This download helper is for Windows. On other systems supply native binaries on PATH.")
    ROOT.mkdir(parents=True, exist_ok=True)
    for filename, folder, url, expected in PACKAGES:
        archive = ROOT / filename
        if not archive.exists():
            partial = archive.with_suffix(".partial")
            print(f"Downloading {filename}", flush=True)
            with urllib.request.urlopen(url, timeout=120) as response, partial.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
            partial.rename(archive)
        with archive.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                raise SystemExit(f"Checksum mismatch: {archive}. No binaries were executed; replace the archive before retrying.")
        destination = ROOT / folder
        with zipfile.ZipFile(archive) as package:
            for entry in package.infolist():
                if not (destination / entry.filename).resolve().is_relative_to(destination.resolve()):
                    raise SystemExit("Archive contains a path outside its extraction directory.")
            package.extractall(destination)
        print(f"Verified and extracted {filename}", flush=True)


if __name__ == "__main__":
    main()
