# Contributing

Open an issue with a minimal, non-sensitive reproducer before proposing a change.
Never attach production credentials, personal exports or proprietary datasets.
Use synthetic fixtures where possible and record their provenance otherwise.

Use Python 3.11 or newer:

```sh
python -m venv .venv
# Activate .venv for your shell.
python -m pip install -r requirements-dev.txt
python -m pip install -e .
python -m unittest discover -s tests -v
python -m ruff check .
python -m ruff format --check .
python -m build --no-isolation
```

Changes must preserve documented exit codes, deterministic JSON and input limits.
Add a regression test for a behavioral fix. Please discuss schema changes first.
Pull requests are reviewed manually; CI never commits code or enables auto-merge.
Third-party copyrights and licenses must be retained. Contributions are MIT-licensed.
