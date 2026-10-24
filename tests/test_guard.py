from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path

from lfs_archive_guard.cli import main
from lfs_archive_guard.core import (
    FORMAT,
    InputError,
    Limits,
    clean_path,
    make_manifest,
    parse_pointer,
    read_manifest,
    validate_manifest,
    verify_zip,
)


def pointer(payload: bytes) -> bytes:
    return (
        f"version https://git-lfs.github.com/spec/v1\n"
        f"oid sha256:{hashlib.sha256(payload).hexdigest()}\nsize {len(payload)}\n"
    ).encode("ascii")


def manifest(payload: bytes = b"actual asset", path: str = "assets/model.bin") -> dict:
    return {
        "format": FORMAT,
        "source_tree": "a" * 40,
        "objects": [
            {"path": path, "oid": hashlib.sha256(payload).hexdigest(), "size": len(payload)}
        ],
    }


class PointerTests(unittest.TestCase):
    def test_standard_pointer(self):
        self.assertEqual(parse_pointer(pointer(b"abc")), (hashlib.sha256(b"abc").hexdigest(), 3))

    def test_legacy_version(self):
        data = pointer(b"abc").replace(b"git-lfs.github", b"hawser.github")
        self.assertIsNotNone(parse_pointer(data))

    def test_ordinary_binary_and_documentation(self):
        for data in (b"\xff\x00", b"", b"Example:\n" + pointer(b"x")):
            self.assertIsNone(parse_pointer(data))

    def test_noncanonical_and_extensions_rejected(self):
        valid = pointer(b"x")
        cases = [
            valid.rstrip(b"\n"),
            valid.replace(b"\n", b"\r\n"),
            valid.replace(b"size 1", b"size -1"),
            valid.replace(b"size 1", b"size 01"),
            valid.replace(b"sha256:", b"sha512:"),
            valid.replace(b"size 1", b"size 9999999999999999999"),
            valid.replace(b"oid ", b"ext-0-filter abc\noid "),
        ]
        for data in cases:
            with self.subTest(data=data), self.assertRaises(InputError):
                parse_pointer(data)

    def test_reject_manifest_duplicates_and_types(self):
        for change in ({"size": True}, {"size": -1}, {"oid": "A" * 64}, {"path": "../x"}):
            data = manifest()
            data["objects"][0].update(change)
            with self.subTest(change=change), self.assertRaises(InputError):
                validate_manifest(data)
        data = manifest(path="a")
        data["objects"].append(dict(data["objects"][0], path="A"))
        with self.assertRaises(InputError):
            validate_manifest(data)

    def test_unsafe_paths(self):
        for path in ("/a", "a//b", "a/../b", "a\\b", "a\x00b", "C:foo", "a/", "a/./b"):
            with self.subTest(path=path), self.assertRaises(InputError):
                clean_path(path)


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root / "release.zip"

    def zip(self, files, compression=zipfile.ZIP_DEFLATED):
        with zipfile.ZipFile(self.archive, "w", compression=compression) as target:
            for name, data in files:
                target.writestr(name, data)

    def codes(self, files, data=None, **kwargs):
        self.zip(files)
        return {
            f["code"] for f in verify_zip(data or manifest(), self.archive, **kwargs)["findings"]
        }

    def test_good_exact_payload(self):
        self.zip([("assets/model.bin", b"actual asset"), ("README.md", b"ordinary")])
        original = self.archive.read_bytes()
        report = verify_zip(manifest(), self.archive)
        self.assertTrue(report["passed"])
        self.assertEqual(report["verified_objects"], 1)
        self.assertEqual(report["bytes_hashed"], 12)
        self.assertEqual(self.archive.read_bytes(), original)
        self.assertEqual(list(self.root.iterdir()), [self.archive])

    def test_unresolved_pointer(self):
        self.assertEqual(
            self.codes([("assets/model.bin", pointer(b"actual asset"))]), {"unresolved_pointer"}
        )

    def test_missing_and_extra_pointer(self):
        self.assertEqual(
            self.codes([("other.bin", pointer(b"else"))]), {"missing_payload", "extra_pointer"}
        )

    def test_malformed_pointer_fails(self):
        self.assertIn(
            "malformed_pointer", self.codes([("assets/model.bin", pointer(b"x").rstrip())])
        )

    def test_size_and_hash_mismatch(self):
        self.assertEqual(self.codes([("assets/model.bin", b"short")]), {"size_mismatch"})
        self.assertEqual(self.codes([("assets/model.bin", b"actual asSet")]), {"sha256_mismatch"})

    def test_empty_payload(self):
        self.zip([("empty", b"")])
        self.assertTrue(verify_zip(manifest(b"", "empty"), self.archive)["passed"])

    def test_large_payload_streaming(self):
        payload = bytes(range(256)) * 2000
        self.zip([("assets/model.bin", payload)])
        self.assertTrue(verify_zip(manifest(payload), self.archive)["passed"])

    def test_explicit_strip_prefix(self):
        self.zip([("project/", b""), ("project/assets/model.bin", b"actual asset")])
        self.assertTrue(verify_zip(manifest(), self.archive, strip=1)["passed"])
        self.assertFalse(verify_zip(manifest(), self.archive)["passed"])

    def test_over_stripping(self):
        self.zip([("file", b"x")])
        with self.assertRaises(InputError):
            verify_zip(manifest(), self.archive, strip=1)

    def test_traversal_and_backslashes_rejected_without_writing(self):
        for name in ("../outside", "/absolute", "root/../outside", "root\\file"):
            self.zip([(name.replace("\\", "/"), b"x")])
            if "\\" in name:
                # Windows' ZIP writer normalizes separators. Patch the raw headers
                # to ensure the fixture actually contains the invalid bytes.
                self.archive.write_bytes(
                    self.archive.read_bytes().replace(b"root/file", b"root\\file")
                )
            with self.subTest(name=name), self.assertRaises(InputError):
                verify_zip(manifest(), self.archive, strip=1)
        self.assertFalse((self.root.parent / "outside").exists())

    def test_case_unicode_duplicates_and_prefix_conflicts(self):
        cases = [("a", "A"), ("caf\u00e9", "cafe\u0301"), ("a", "a/b"), ("a", "a/")]
        for names in cases:
            self.zip([(name, b"x") for name in names])
            with self.subTest(names=names), self.assertRaises(InputError):
                verify_zip(manifest(), self.archive)

    def test_exact_duplicate(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            self.zip([("x", b"a"), ("x", b"b")])
        with self.assertRaises(InputError):
            verify_zip(manifest(), self.archive)

    def test_symlink_not_accepted_as_payload(self):
        info = zipfile.ZipInfo("assets/model.bin")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.assertEqual(self.codes([(info, b"actual asset")]), {"not_regular_file"})

    def test_compressed_size_payload_and_count_limits(self):
        self.zip([("assets/model.bin", b"actual asset"), ("another", b"x")])
        for limits in (
            Limits(max_archive_bytes=1),
            Limits(max_payload_bytes=2),
            Limits(max_entries=1),
        ):
            with self.subTest(limits=limits), self.assertRaises(InputError):
                verify_zip(manifest(), self.archive, limits=limits)

    def test_report_truncation_is_failure(self):
        data = manifest()
        data["objects"].append(dict(data["objects"][0], path="two"))
        self.zip([])
        report = verify_zip(data, self.archive, limits=Limits(max_findings=1))
        self.assertFalse(report["passed"])
        self.assertTrue(report["findings_truncated"])
        self.assertEqual(report["finding_count"], 2)

    def test_corrupt_zip_and_crc_failure(self):
        self.archive.write_bytes(b"not a ZIP")
        with self.assertRaises(InputError):
            verify_zip(manifest(), self.archive)
        self.zip([("assets/model.bin", b"actual asset")], compression=zipfile.ZIP_STORED)
        data = self.archive.read_bytes().replace(b"actual asset", b"actual asSet", 1)
        self.archive.write_bytes(data)
        with self.assertRaises(InputError):
            verify_zip(manifest(), self.archive)

    def test_embedded_nul_not_silently_truncated(self):
        self.zip([("assets/model.bin", b"actual asset")], compression=zipfile.ZIP_STORED)
        data = self.archive.read_bytes().replace(b"assets/model.bin", b"assets/model\x00bin")
        self.archive.write_bytes(data)
        with self.assertRaises(InputError):
            verify_zip(manifest(), self.archive)

    def test_invalid_deflate_is_an_input_failure(self):
        self.zip([("assets/model.bin", b"actual asset")])
        data = bytearray(self.archive.read_bytes())
        name_size, extra_size = struct.unpack_from("<HH", data, 26)
        start = 30 + name_size + extra_size
        data[start : start + 3] = b"\xff\xff\xff"
        self.archive.write_bytes(data)
        with self.assertRaises(InputError):
            verify_zip(manifest(), self.archive)

    def test_encrypted_flag_fails_closed(self):
        self.zip([("assets/model.bin", b"actual asset")])
        data = bytearray(self.archive.read_bytes())
        central = data.index(b"PK\x01\x02")
        struct.pack_into("<H", data, central + 8, 1)
        self.archive.write_bytes(data)
        with self.assertRaises(InputError):
            verify_zip(manifest(), self.archive)

    def test_manifest_duplicate_json_keys(self):
        path = self.root / "manifest.json"
        path.write_text('{"format":"a","format":"b"}', encoding="utf-8")
        with self.assertRaises(InputError):
            read_manifest(path)

    def test_cli_real_process_exit_codes(self):
        path = self.root / "manifest.json"
        path.write_text(json.dumps(manifest()), encoding="utf-8")
        for payload, code in ((b"actual asset", 0), (pointer(b"actual asset"), 1)):
            self.zip([("assets/model.bin", payload)])
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "lfs_archive_guard",
                    "verify",
                    str(path),
                    str(self.archive),
                    "--json",
                ],
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, code, result.stderr)
            self.assertEqual(json.loads(result.stdout)["passed"], code == 0)
        self.archive.write_bytes(b"corrupt")
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["verify", str(path), str(self.archive), "--json"]), 2)
        self.assertIn("error", json.loads(output.getvalue()))


class GitFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "--quiet")

    def git(self, *args, data=None):
        result = subprocess.run(
            ["git", "-C", str(self.root), *args],
            input=data,
            capture_output=True,
            check=True,
            env=dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull),
        )
        return result.stdout.strip().decode("ascii")

    def tree(self, payload=None):
        payload = pointer(b"actual asset") if payload is None else payload
        blob = self.git("hash-object", "-w", "--stdin", data=payload)
        # Write blobs/trees only: fixtures create no Git commits or external authors.
        return self.git("mktree", data=f"100644 blob {blob}\tmodel.bin\n".encode())

    def test_git_tree_to_zip_full_workflow(self):
        tree = self.tree()
        data = make_manifest(self.root, tree)
        self.assertEqual(data["source_tree"], tree)
        self.assertEqual(data["objects"][0]["path"], "model.bin")
        archive = self.root / "release.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("model.bin", b"actual asset")
        self.assertTrue(verify_zip(data, archive)["passed"])
        self.assertEqual(make_manifest(self.root, tree), data)

    def test_working_tree_cannot_replace_committed_identity(self):
        tree = self.tree()
        before = make_manifest(self.root, tree)
        (self.root / "model.bin").write_bytes(b"different uncommitted payload")
        self.assertEqual(make_manifest(self.root, tree), before)

    def test_empty_tree_and_invalid_ref(self):
        tree = self.tree(b"ordinary file")
        for ref in (tree, "--help", "missing"):
            with self.subTest(ref=ref), self.assertRaises(InputError):
                make_manifest(self.root, ref)

    def test_manifest_output_never_overwrites(self):
        tree = self.tree()
        path = self.root / "output.json"
        args = ["manifest", "--repo", str(self.root), "--ref", tree, "--output", str(path)]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(args), 0)
            original = path.read_bytes()
            self.assertEqual(main(args), 2)
        self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
