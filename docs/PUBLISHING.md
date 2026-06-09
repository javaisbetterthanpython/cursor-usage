# Publishing

Steps to turn this local project into a public repo and a `pip install`-able
package. Replace `your-username` with your GitHub/PyPI account.

## 1. Fill placeholders

- In `pyproject.toml`: set the `Homepage`/`Issues` URLs (replace `your-username`).
  (`authors` is intentionally generic — fill it in only if you want.)
- The PyPI distribution name is `cursor-usage`; the import package is
  `cursor_usage`; the command is `cursor-usage`. Change all three together if you
  rename.

## 2. Run the tests locally

No CI is configured (keeps the repo lightweight). Verify before publishing:

```bash
python -m pip install -e . pytest
pytest -q
cursor-usage --help
```

## 3. Create the public GitHub repo

```bash
gh repo create your-username/cursor-usage --public --source=. --remote=origin \
  --description "Cross-platform CLI for your Cursor (cursor.com) usage & spend" --push
```

## 4. Publish to PyPI

```bash
python -m pip install --upgrade build twine
python -m build                 # creates dist/*.whl and dist/*.tar.gz
twine check dist/*
twine upload dist/*             # needs a PyPI API token (recommended via ~/.pypirc)
```

Then anyone can:

```bash
pip install cursor-usage
cursor-usage --by-day
```

## 5. Versioning

Bump `version` in both `pyproject.toml` and `src/cursor_usage/__init__.py`, tag
`vX.Y.Z`, and push the tag.

<details>
<summary>Optional: automate PyPI releases on tag (requires GitHub Actions)</summary>

GitHub Actions is free for public repos. If you ever want hands-off releases,
add `.github/workflows/release.yml` using PyPI Trusted Publishing (OIDC) — no
stored secrets:

```yaml
name: release
on:
  push:
    tags: ["v*"]
permissions:
  id-token: write   # trusted publishing
jobs:
  pypi:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install build && python -m build
      - uses: pypa/gh-action-pypi-publish@release/v1
```

Then configure the matching Trusted Publisher on PyPI (project → Publishing).
</details>

## Note on data & secrets

Nothing account-specific is in the repo. CSV exports (`*.csv`) and virtualenvs
are git-ignored. The tool reads the session token from the local machine at
runtime — it is never committed.
