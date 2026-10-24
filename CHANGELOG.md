# Changelog

## 0.1.0 — 2026-10-24

- Export deterministic path/size/SHA-256 manifests from committed Git LFS pointers.
- Verify actual ZIP payloads without extraction, Git LFS, credentials or network access.
- Report unresolved pointers, missing/wrong payloads and ambiguous archive mappings.
- Bound entry counts, declared payload bytes and displayed findings; incomplete checks fail.
- Include an executable offline demo, 31 tests and a read-only cross-platform CI matrix.

Initial scope: ZIP and canonical v1 pointers; no transformed extensions, repair, TAR,
signatures or full-archive integrity certification. See README for resource assumptions.
