# Security

Version 0.1.x is the currently supported release series.
Report vulnerabilities privately through [GitHub private vulnerability reporting](https://github.com/KanadeK/lfs-archive-guard/security/advisories/new).
If that feature is unavailable, open an issue asking for a private channel **without**
including exploit details or sensitive files. Never publish secrets in an issue.

The CLI reads local inputs. Runtime code makes no network requests and does not
execute input content. Treat reports as local data: they can contain artifact paths
or identifiers. Input limits and remaining trust assumptions are described in README.
Python and Git (where used) must be maintained with upstream security fixes.
