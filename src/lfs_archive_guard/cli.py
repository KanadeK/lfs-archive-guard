"""Command-line interface with stable success/failure/input-error exit codes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .core import InputError, Limits, make_manifest, read_manifest, verify_zip


def positive(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify LFS payload identities in a release ZIP.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    manifest = commands.add_parser("manifest", help="Read pointers from a trusted local Git tree")
    manifest.add_argument("--repo", type=Path, default=Path("."))
    manifest.add_argument("--ref", default="HEAD")
    manifest.add_argument("--output", type=Path, required=True, help="New file; never overwritten")
    verify = commands.add_parser("verify", help="Compare a ZIP to a manifest, without extraction")
    verify.add_argument("manifest", type=Path)
    verify.add_argument("archive", type=Path)
    verify.add_argument("--strip-components", type=int, default=0)
    verify.add_argument("--max-archive-bytes", type=positive, default=Limits().max_archive_bytes)
    verify.add_argument("--max-payload-bytes", type=positive, default=Limits().max_payload_bytes)
    verify.add_argument("--json", action="store_true", help="Machine-readable report on stdout")
    args = parser.parse_args(argv)
    try:
        if args.command == "manifest":
            result = make_manifest(args.repo, args.ref)
            with args.output.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(result, indent=2, ensure_ascii=True) + "\n")
            print(
                f"Recorded {len(result['objects'])} LFS object(s) from tree {result['source_tree']}"
            )
            return 0
        result = verify_zip(
            read_manifest(args.manifest),
            args.archive,
            strip=args.strip_components,
            limits=Limits(
                max_archive_bytes=args.max_archive_bytes,
                max_payload_bytes=args.max_payload_bytes,
            ),
        )
        if args.json:
            print(json.dumps(result, sort_keys=True, ensure_ascii=True))
        else:
            status = "PASS" if result["passed"] else "FAIL"
            print(
                f"{status}: {result['verified_objects']}/{result['expected_objects']} "
                "payloads verified"
            )
            for finding in result["findings"]:
                print(f"{finding['code']}: {json.dumps(finding['path'], ensure_ascii=True)}")
            if result["findings_truncated"]:
                print(f"Findings truncated; total: {result['finding_count']}")
        return 0 if result["passed"] else 1
    except (InputError, OSError, ValueError) as exc:
        message = f"Check incomplete: {exc}"
        if getattr(args, "json", False):
            print(json.dumps({"passed": False, "error": message}, ensure_ascii=True))
        else:
            print(json.dumps(message, ensure_ascii=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
