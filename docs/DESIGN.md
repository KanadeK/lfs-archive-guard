# Design and acceptance contract

User: a maintainer distributing source ZIPs containing LFS-managed assets.
Success: a trusted tree produces a stable identity manifest; a complete payload ZIP
passes; missing, wrong and unresolved payloads fail with actionable paths and exit codes.

The manifest stores Git's tree ID and LFS SHA-256/size, not machine paths, source data,
credentials or a Git remote. Git operations use argument arrays, no shell, optional
locks disabled and lazy-fetch disabled. Local trusted object databases are the input.
One batch read handles all small blobs. No LFS client or network is used.

Archive verification validates path mapping before opening entries, rejects ambiguous
names, checks expected regular files and hashes in chunks. An unsupported structure,
corrupt CRC, encryption or quota is incomplete verification (exit 2), never success.
Failure findings are bounded while retaining the total and failed state.

The MVP deliberately omits repair, `.gitattributes` interpretation, TAR, signatures
and transformed LFS extension payloads. Standard library ZIP directory allocation is
not a hard memory sandbox. Checksums establish equality to the supplied manifest,
not trust in that manifest or safety of executing the release.
