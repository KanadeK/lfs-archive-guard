# Initial release validation

Local release checks on 2026-10-24 used Windows and CPython 3.13.16.

- 31 unit/integration/CLI tests passed from an installed wheel in a new virtual environment.
- Both CLI demo outcomes were checked: hydrated payload passes; unresolved pointer fails.
- Ruff lint (including security rules), format check and byte compilation passed.
- Source distribution and wheel built; offline wheel install, version and uninstall checks passed.
- A seeded 1,000-case ZIP mutation smoke experiment produced handled input errors,
  payload findings, or passes for changes that can affect irrelevant metadata; no
  unexpected exception was observed. This is not a security proof.
- A local 5,001-entry Git-tree experiment (5,000 ordinary files and one LFS pointer)
  produced the correct manifest using a batch blob read.

Review found and corrected decompression-error handling and a Windows test-fixture
issue: the ZIP writer normalizes backslashes, so that fixture now patches raw archive
headers to exercise actual backslash input. Manifest prefix collisions are rejected.

No runtime package dependencies are installed. Source and fixtures are original;
linked specifications and tools retain their own licenses. No credentials, services,
account configuration or global Git writes are part of the runtime workflow.

The CI workflow independently runs the declared checks on its actual runner platforms.
See the repository's Actions page for current results; local checks alone do not
establish Linux or macOS success.
