# Third-party software and provenance

Runtime dependencies: Python standard library only. Python is provided by the user
under the PSF license. The LFS manifest command additionally invokes an installed Git,
distributed separately under GPL-2.0. No Python/Git source is vendored or redistributed.

Development tools are installed separately: setuptools (MIT), build (MIT), Ruff (MIT).
GitHub Actions checkout and setup-python are MIT-licensed services/actions referenced
by immutable commit IDs. They are not included in the distributed Python package.

All source and synthetic fixtures in this repository were written for this project.
External specifications and competing projects are linked as references, not copied
implementations. The MIT license applies to our code and fixtures, not linked material.
