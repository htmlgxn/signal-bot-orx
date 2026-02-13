# Release Runbook

## Prerequisites

- PyPI token configured for `uv publish`.
- Clean working tree.
- CI passing on `main`.

## Steps

1. Update version in `pyproject.toml` using date-based scheme.
2. Update `CHANGELOG.md`.
3. Run quality gates:

```bash
uv run ruff check .
uv run ty check .
uv run pytest
uv build
```

4. Create and push annotated tag:

```bash
git tag -a v<version> -m "release <version>"
git push origin main
git push origin v<version>
```

5. Publish artifacts:

```bash
uv build
uv publish
```

6. Create GitHub release from the tag and paste changelog notes.
