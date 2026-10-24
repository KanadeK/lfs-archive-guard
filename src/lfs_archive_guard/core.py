"""Git LFS identity manifests and extraction-free ZIP verification."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import unicodedata
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path

FORMAT = "lfs-archive-guard/v1"
POINTER_LIMIT = 1024
MANIFEST_LIMIT = 16 * 1024 * 1024
TREE_LIMIT = 32 * 1024 * 1024
ENTRY_LIMIT = 50_000
VERSIONS = (b"https://git-lfs.github.com/spec/v1", b"https://hawser.github.com/spec/v1")
OID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
SHA256 = re.compile(r"[0-9a-f]{64}")


class InputError(ValueError):
    """The requested check could not be completed."""


@dataclass(frozen=True)
class Object:
    path: str
    oid: str
    size: int

    def as_dict(self) -> dict:
        return {"path": self.path, "oid": self.oid, "size": self.size}


@dataclass(frozen=True)
class Limits:
    max_entries: int = ENTRY_LIMIT
    max_archive_bytes: int = 512 * 1024 * 1024
    max_payload_bytes: int = 2 * 1024 * 1024 * 1024
    max_findings: int = 200

    def __post_init__(self) -> None:
        if any(type(v) is not int or v <= 0 for v in vars(self).values()):
            raise InputError("Limits must be positive integers")


def clean_path(value: str, *, directory: bool = False) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise InputError("Expected a nonempty POSIX relative path")
    if directory and value.endswith("/"):
        value = value[:-1]
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise InputError("Absolute, empty and dot path components are not supported")
    if any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise InputError("Control characters and invalid Unicode in paths are not supported")
    if any(":" in part for part in parts):
        raise InputError("Drive names and alternate data stream paths are not supported")
    return value


def canonical(path: str) -> str:
    return unicodedata.normalize("NFC", path).casefold()


def parse_pointer(data: bytes) -> tuple[str, int] | None:
    """Return canonical v1 identity, None for ordinary data; reject suspect pointers."""
    if not any(data.startswith(b"version " + version) for version in VERSIONS):
        return None
    if len(data) >= POINTER_LIMIT:
        raise InputError("LFS pointer exceeds the v1 size limit")
    lines = data.split(b"\n")
    if any(line.startswith(b"ext-") for line in lines):
        raise InputError("LFS extension pointers are unsupported; transformed payloads need review")
    if len(lines) != 4 or lines[-1] or lines[0][8:] not in VERSIONS:
        raise InputError("Noncanonical or malformed LFS v1 pointer")
    oid_match = re.fullmatch(rb"oid sha256:([0-9a-f]{64})", lines[1])
    size_match = re.fullmatch(rb"size (0|[1-9][0-9]{0,18})", lines[2])
    if not oid_match or not size_match:
        raise InputError("Invalid LFS SHA-256 or size")
    size = int(size_match[1])
    if size > 2**63 - 1:
        raise InputError("LFS size exceeds supported signed 64-bit range")
    return oid_match[1].decode("ascii"), size


def _git(repo: Path, *args: str, limit: int = TREE_LIMIT, stdin: bytes | None = None) -> bytes:
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_NO_LAZY_FETCH="1")
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "-c", "core.fsmonitor=false", *args],
            capture_output=True,
            input=stdin,
            timeout=60,
            env=env,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InputError("Git is unavailable or exceeded the 60-second command timeout") from exc
    if result.returncode:
        raise InputError("Git could not read the requested tree/blob (check repository and ref)")
    if len(result.stdout) > limit:
        raise InputError("Git metadata exceeds the supported size limit")
    return result.stdout


def make_manifest(repo: Path, ref: str = "HEAD") -> dict:
    """Read committed objects, never the working tree or external LFS storage."""
    tree = _git(repo, "rev-parse", "--verify", "--end-of-options", ref + "^{tree}", limit=256)
    tree_id = tree.decode("ascii").strip()
    if not OID.fullmatch(tree_id):
        raise InputError("Git returned an unsupported tree ID")
    listing = _git(repo, "ls-tree", "-r", "-l", "-z", tree_id)
    records = listing.split(b"\0")
    if records[-1] != b"" or len(records) - 1 > ENTRY_LIMIT:
        raise InputError("Git tree is malformed or exceeds 50000 entries")
    candidates = []
    for record in records[:-1]:
        metadata, raw_path = record.split(b"\t", 1)
        mode, kind, blob, raw_size = metadata.split()
        if kind != b"blob" or mode not in (b"100644", b"100755"):
            continue
        size = int(raw_size)
        if size >= POINTER_LIMIT:
            continue
        blob_id = blob.decode("ascii")
        if not OID.fullmatch(blob_id):
            raise InputError("Git returned an unsupported blob ID")
        candidates.append((raw_path, blob_id))
    blob_ids = sorted({blob_id for _, blob_id in candidates})
    batch = _git(
        repo,
        "cat-file",
        "--batch",
        stdin="".join(blob_id + "\n" for blob_id in blob_ids).encode("ascii"),
        limit=TREE_LIMIT * 2,
    )
    blobs = {}
    offset = 0
    for blob_id in blob_ids:
        end = batch.find(b"\n", offset)
        header = batch[offset:end].split()
        if len(header) != 3 or header[0].decode("ascii") != blob_id or header[1] != b"blob":
            raise InputError("Git returned malformed batch metadata")
        size = int(header[2])
        if size >= POINTER_LIMIT or size < 0 or end < offset:
            raise InputError("Git blob changed or exceeds the pointer size limit")
        start = end + 1
        data = batch[start : start + size]
        if len(data) != size or batch[start + size : start + size + 1] != b"\n":
            raise InputError("Git returned incomplete batch content")
        blobs[blob_id] = data
        offset = start + size + 1
    objects = []
    for raw_path, blob_id in candidates:
        data = blobs[blob_id]
        pointer = parse_pointer(data)
        if pointer is None:
            continue
        try:
            path = clean_path(raw_path.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise InputError("LFS object paths must be UTF-8") from exc
        objects.append(Object(path, *pointer))
    if not objects:
        raise InputError("No supported LFS pointers found in this Git tree")
    manifest = {
        "format": FORMAT,
        "source_tree": tree_id,
        "objects": [obj.as_dict() for obj in sorted(objects, key=lambda obj: obj.path)],
    }
    validate_manifest(manifest)
    return manifest


def unique_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError("Duplicate JSON object key")
        result[key] = value
    return result


def validate_manifest(data: object) -> list[Object]:
    if not isinstance(data, dict) or set(data) != {"format", "source_tree", "objects"}:
        raise InputError("Unsupported manifest structure")
    if data["format"] != FORMAT:
        raise InputError("Unsupported manifest format")
    if not isinstance(data["source_tree"], str) or not OID.fullmatch(data["source_tree"]):
        raise InputError("Invalid manifest source tree")
    rows = data["objects"]
    if not isinstance(rows, list) or not rows or len(rows) > ENTRY_LIMIT:
        raise InputError("Manifest must contain 1..50000 objects")
    objects, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"path", "oid", "size"}:
            raise InputError("Invalid manifest object")
        path = clean_path(row["path"])
        if not isinstance(row["oid"], str) or not SHA256.fullmatch(row["oid"]):
            raise InputError("Manifest object must have a lower-case SHA-256")
        if type(row["size"]) is not int or not 0 <= row["size"] <= 2**63 - 1:
            raise InputError("Invalid manifest payload size")
        key = canonical(path)
        if key in seen:
            raise InputError("Manifest paths collide after Unicode/case normalization")
        seen.add(key)
        objects.append(Object(path, row["oid"], row["size"]))
    for key in seen:
        parts = key.split("/")
        if any("/".join(parts[:i]) in seen for i in range(1, len(parts))):
            raise InputError("Manifest contains file/directory prefix conflicts")
    return objects


def read_manifest(path: Path) -> dict:
    with path.open("rb") as stream:
        data = stream.read(MANIFEST_LIMIT + 1)
    if len(data) > MANIFEST_LIMIT:
        raise InputError("Manifest exceeds 16 MiB")
    try:
        result = json.loads(data, object_pairs_hook=unique_pairs)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise InputError("Manifest is not valid, unambiguous JSON") from exc
    validate_manifest(result)
    return result


def verify_zip(
    manifest: dict, archive: Path, *, strip: int = 0, limits: Limits | None = None
) -> dict:
    limits = limits or Limits()
    if type(strip) is not int or strip < 0:
        raise InputError("strip-components must be a nonnegative integer")
    expected = {obj.path: obj for obj in validate_manifest(manifest)}
    if archive.stat().st_size > limits.max_archive_bytes:
        raise InputError("ZIP exceeds configured compressed-size limit")
    findings: list[dict] = []
    finding_count = 0

    def finding(code: str, path: str) -> None:
        nonlocal finding_count
        finding_count += 1
        if len(findings) < limits.max_findings:
            findings.append({"code": code, "path": path})

    try:
        with zipfile.ZipFile(archive) as zipped:
            entries = zipped.infolist()
            if len(entries) > limits.max_entries:
                raise InputError("ZIP exceeds configured entry limit")
            if sum(entry.file_size for entry in entries) > limits.max_payload_bytes:
                raise InputError("ZIP exceeds configured declared uncompressed-size limit")
            mapped: dict[str, zipfile.ZipInfo] = {}
            canonical_names: dict[str, str] = {}
            directories = set()
            for entry in entries:
                # orig_filename retains embedded NULs that filename would silently truncate.
                name = clean_path(entry.orig_filename, directory=entry.is_dir())
                parts = name.split("/")
                if len(parts) <= strip:
                    if entry.is_dir():
                        continue
                    raise InputError("strip-components removes an entire file path")
                name = "/".join(parts[strip:])
                key = canonical(name)
                if key in canonical_names:
                    raise InputError("Duplicate or Unicode/case-colliding ZIP paths")
                canonical_names[key] = name
                if entry.is_dir():
                    directories.add(key)
                else:
                    mapped[name] = entry
            regular_keys = {canonical(name) for name in mapped}
            for name in canonical_names:
                parents = name.split("/")
                for i in range(1, len(parents)):
                    if "/".join(parents[:i]) in regular_keys:
                        raise InputError("ZIP contains a file/directory prefix conflict")
            if regular_keys & directories:
                raise InputError("ZIP contains a file/directory collision")
            verified = 0
            bytes_hashed = 0
            for path, entry in sorted(mapped.items()):
                mode = (entry.external_attr >> 16) & 0xFFFF
                special = stat.S_IFMT(mode)
                if entry.flag_bits & 1:
                    raise InputError("Encrypted ZIP entries are unsupported")
                if special not in (0, stat.S_IFREG):
                    if path in expected:
                        finding("not_regular_file", path)
                    continue
                small = None
                if entry.file_size < POINTER_LIMIT:
                    with zipped.open(entry) as stream:
                        small = stream.read(POINTER_LIMIT)
                    try:
                        pointer = parse_pointer(small)
                    except InputError:
                        finding("malformed_pointer", path)
                        continue
                    if pointer is not None:
                        finding("unresolved_pointer" if path in expected else "extra_pointer", path)
                        continue
                if path not in expected:
                    continue
                obj = expected[path]
                if entry.file_size != obj.size:
                    finding("size_mismatch", path)
                    continue
                digest = hashlib.sha256()
                actual_size = 0
                if small is not None:
                    digest.update(small)
                    actual_size = len(small)
                else:
                    with zipped.open(entry) as stream:
                        while block := stream.read(128 * 1024):
                            actual_size += len(block)
                            if (
                                actual_size > obj.size
                                or bytes_hashed + actual_size > limits.max_payload_bytes
                            ):
                                raise InputError("Actual ZIP payload exceeds permitted size")
                            digest.update(block)
                bytes_hashed += actual_size
                if actual_size != obj.size:
                    finding("size_mismatch", path)
                elif digest.hexdigest() != obj.oid:
                    finding("sha256_mismatch", path)
                else:
                    verified += 1
            for path in sorted(expected.keys() - mapped.keys()):
                finding("missing_payload", path)
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError, EOFError, zlib.error) as exc:
        raise InputError("ZIP is corrupt or uses unsupported encryption/compression") from exc
    return {
        "schema": FORMAT,
        "source_tree": manifest["source_tree"],
        "passed": finding_count == 0,
        "expected_objects": len(expected),
        "verified_objects": verified,
        "archive_entries": len(entries),
        "bytes_hashed": bytes_hashed,
        "finding_count": finding_count,
        "findings_truncated": finding_count > len(findings),
        "findings": findings,
    }
