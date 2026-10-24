# lfs-archive-guard

Verify that a release ZIP contains the **actual Git LFS payloads** promised by a Git tree.
Runs offline, hashes payloads without extracting them, and needs no Python runtime dependencies.

[中文说明](README.zh-CN.md) · [Security](SECURITY.md) · [Contributing](CONTRIBUTING.md)

GitHub source archives can contain LFS pointer text instead of assets. A ZIP can also
contain missing, truncated or wrong assets even after LFS checkout. This tool records
the expected path, byte count and SHA-256 from committed pointers, then checks the
ZIP you intend to distribute against that record.

## Install

Requires Python 3.11+. Manifest creation also requires a maintained Git version with
`GIT_NO_LAZY_FETCH` support (Git 2.46+ recommended); ZIP verification needs neither Git
nor Git LFS. It never downloads LFS objects.

```sh
git clone https://github.com/KanadeK/lfs-archive-guard.git
cd lfs-archive-guard
python -m venv .venv
# Linux/macOS:
. .venv/bin/activate
# Windows PowerShell instead:
# .\.venv\Scripts\Activate.ps1
python -m pip install .
lfs-archive-guard --version
```

If shell activation is unavailable, use `.venv/bin/python -m lfs_archive_guard` or
`.\.venv\Scripts\python.exe -m lfs_archive_guard`. Versioned wheels are attached to
GitHub Releases; a downloaded wheel installs with `python -m pip install path/to/file.whl`.
No PyPI publication is implied.

## Core workflow

From your project's local checkout:

```sh
lfs-archive-guard manifest --repo . --ref HEAD --output lfs-manifest.json
lfs-archive-guard verify lfs-manifest.json release.zip
```

For a GitHub ZIP whose entries start with `project-tag/`, explicitly remove that
one prefix component:

```sh
lfs-archive-guard verify lfs-manifest.json source.zip --strip-components 1 --json
```

The manifest command reads committed Git objects, so an uncommitted working-tree
change cannot silently alter the expected payload. The manifest records the resolved
tree ID and is deterministic. Keep it from a trusted revision: this is a content
comparison, not a signature or proof of who authored that revision. Existing output
files are never overwritten. A tree with no supported LFS pointers is an input error.

The verifier reports unresolved pointers, missing files, byte-count mismatches,
SHA-256 mismatches, non-regular expected files and additional small LFS pointers.
It rejects duplicate names, Unicode/case collisions, path traversal, backslashes,
embedded NULs, file/directory conflicts and encryption instead of selecting an
ambiguous entry. It writes nothing to the archive or an extraction directory.

## Try it without LFS or a network

After installation, from this repository:

```sh
python examples/demo.py .demo
```

This builds synthetic Git blobs and a tree **without creating a Git commit**, exports
a real manifest through the CLI and creates two ZIPs. It runs both checks and requires
the hydrated ZIP to return `0` and the pointer-only ZIP to return `1`. The printed tree
ID is produced by your Git object format. The data is original test data, not a real
model or dataset.

## Reports and exit codes

`--json` on `verify` emits one JSON object on stdout. Schema `lfs-archive-guard/v1`
contains `passed`, `source_tree`, expected/verified object counts, `bytes_hashed`,
`finding_count`, `findings_truncated`, and findings with stable `code` and `path`.
It never prints file contents. Input failures emit `passed: false` and `error`.

| Exit | Meaning |
|---|---|
| 0 | Every expected payload was verified and no pointer findings were found |
| 1 | Completed verification found a payload problem |
| 2 | Invalid input, unsupported structure, quota or I/O failure; check incomplete |

Human reports escape paths to avoid terminal-control injection. Reports and manifests
still reveal filenames, object hashes and sizes; keep them private when appropriate.

## Bounds and current limits

Defaults: 50,000 ZIP entries, 512 MiB compressed ZIP size, 2 GiB total declared
uncompressed data and at most 200 displayed findings (the total is retained; truncation
never passes). Raise byte limits explicitly when needed:

```sh
lfs-archive-guard verify lfs-manifest.json release.zip --max-archive-bytes 1073741824 --max-payload-bytes 4294967296
```

Payload hashing uses 128 KiB chunks. Python's ZIP central directory is loaded in memory;
these are input/payload quotas, not a hard process-memory or time sandbox. Use OS
resource limits when processing hostile archives. Git metadata is captured before its
32 MiB check (64 MiB batch-content check); manifest generation is for trusted local
repositories, with a 60-second timeout per Git command. It uses three Git commands,
including a batch blob read, rather than starting Git separately for every small file.

Version 0.1.0 supports ZIP only and canonical v1 SHA-256 pointers, including the legacy
hawser version URL. LFS extension pointers are rejected because transformed payloads
need different verification. Non-UTF-8/control-character LFS paths are unsupported.
Empty normal files cannot be discovered as LFS objects without pointer metadata.
The manifest checks all discovered pointers, not arbitrary build outputs or every
`.gitattributes` rule. Extra large files are not hashed, and ordinary extra files are
not integrity-checked. A passing check does not certify extraction safety, software
behavior, licensing or the entire ZIP's integrity.

## Development and cleanup

See [CONTRIBUTING.md](CONTRIBUTING.md) for the exact test, lint and build commands.
CI runs on Linux, Windows and macOS with Python 3.11 and 3.13 and never writes commits.
Tests exercise the real Git-to-manifest-to-ZIP flow, CLI exit codes and malformed,
ambiguous, corrupted, oversized and pointer-only archives.

Uninstall with `python -m pip uninstall lfs-archive-guard`. Delete the dedicated virtual
environment and `.demo` directory if no longer needed. The tool installs no service,
cache, hooks or global Git configuration. Delete generated manifests/reports separately.

## References and alternatives

[GitHub archive behavior](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/managing-git-lfs-objects-in-archives-of-your-repository)
and the [Git LFS pointer specification](https://github.com/git-lfs/git-lfs/blob/main/docs/spec.md)
define the relevant formats. Git LFS `pull`/`fsck` and GitHub's archive inclusion setting
help prepare assets; this tool checks the actual distributed ZIP against the original
pointer identities. It does not replace Git LFS or repair missing payloads. MIT license;
see [THIRD_PARTY.md](THIRD_PARTY.md) for tool licenses and provenance.
