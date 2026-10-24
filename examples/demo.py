"""Create original synthetic assets; require both real CLI outcomes."""

from __future__ import annotations

import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path


def run(*args: str, data: bytes | None = None) -> str:
    return subprocess.run(args, input=data, capture_output=True, check=True).stdout.decode().strip()


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".demo").resolve()
    root.mkdir(exist_ok=False)
    repo = root / "repository"
    repo.mkdir()
    run("git", "-C", str(repo), "init", "--quiet")
    payload = b"Original synthetic release asset.\n" * 400
    pointer = (
        "version https://git-lfs.github.com/spec/v1\n"
        f"oid sha256:{hashlib.sha256(payload).hexdigest()}\nsize {len(payload)}\n"
    ).encode("ascii")
    blob = run("git", "-C", str(repo), "hash-object", "-w", "--stdin", data=pointer)
    tree = run(
        "git", "-C", str(repo), "mktree", data=f"100644 blob {blob}\tasset.bin\n".encode("ascii")
    )
    manifest = root / "lfs-manifest.json"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "lfs_archive_guard",
            "manifest",
            "--repo",
            str(repo),
            "--ref",
            tree,
            "--output",
            str(manifest),
        ],
        check=True,
    )
    for name, content, expected in (("hydrated.zip", payload, 0), ("pointer-only.zip", pointer, 1)):
        archive = root / name
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as target:
            target.writestr("release/asset.bin", content)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "lfs_archive_guard",
                "verify",
                str(manifest),
                str(archive),
                "--strip-components",
                "1",
                "--json",
            ],
            check=False,
        )
        if result.returncode != expected:
            raise SystemExit(
                f"Unexpected exit for {name}: {result.returncode}, expected {expected}"
            )
    print("Demo verified: hydrated ZIP passed; pointer-only ZIP failed as expected.")


if __name__ == "__main__":
    main()
