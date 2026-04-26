# Release and PyPI Publishing

This project publishes with PyPI Trusted Publishing from GitHub Actions. That
keeps long-lived PyPI API tokens out of GitHub secrets. GitHub Actions presents
an OIDC identity to PyPI, and PyPI returns a short-lived upload token only for
the configured workflow.

## One-Time Setup

1. Create GitHub environments:
   - `testpypi`
   - `pypi`

2. On the `pypi` environment, require reviewer approval before deployment. This
   keeps an accidental GitHub Release from immediately publishing to PyPI.

3. Create or configure a PyPI Trusted Publisher for this project:
   - PyPI project name: `kombu-solace`
   - Owner: `kswaroop1`
   - Repository: `kombu-solace`
   - Workflow filename: `release.yml`
   - Environment: `pypi`

4. For the first public release, use a PyPI pending publisher if the project
   does not exist yet. A pending publisher does not reserve the name; it creates
   the PyPI project on the first successful publish if the name is still
   available.

5. Configure the same publisher on TestPyPI if you want a dry run:
   - Project name: `kombu-solace`
   - Owner: `kswaroop1`
   - Repository: `kombu-solace`
   - Workflow filename: `release.yml`
   - Environment: `testpypi`

No PyPI API token or GitHub secret is required for the workflow.

## TestPyPI Dry Run

Run the **Release** workflow manually from GitHub Actions with:

```text
publish_to = testpypi
```

The workflow builds the package, runs unit tests, validates the metadata with
`twine check`, and publishes to TestPyPI using Trusted Publishing.

Install from TestPyPI for a smoke test:

```powershell
python -m pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ kombu-solace
```

## Public PyPI Release

1. Update the version in both files:
   - `pyproject.toml`
   - `kombu_solace/__init__.py`

2. Run local verification:

```powershell
python -m pytest -q
python -m coverage run -m pytest tests/unit -q
python -m coverage report -m
python -m pip wheel . --no-deps -w dist
```

3. Commit and push the version change.

4. Create a tag matching the package version. Both `0.1.0` and `v0.1.0` are
   accepted by the workflow.

```powershell
git tag v0.1.0
git push origin v0.1.0
```

5. In GitHub, create and publish a Release for that tag.

The release workflow will:

- check that the GitHub Release tag matches `pyproject.toml`
- run unit tests
- build source distribution and wheel
- validate package metadata with `twine check`
- attach the artifacts to the GitHub Release
- publish the artifacts to PyPI through Trusted Publishing

After publication, users can install the package with:

```powershell
python -m pip install kombu-solace
```

PyPI files are immutable. If a publish has bad metadata or broken artifacts,
bump the version and publish a new release.

## References

- PyPI Trusted Publishing overview: <https://docs.pypi.org/trusted-publishers/>
- PyPI pending publisher setup: <https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/>
- Adding a Trusted Publisher to an existing project: <https://docs.pypi.org/trusted-publishers/adding-a-publisher/>
- Publishing with PyPA's GitHub Action: <https://docs.pypi.org/trusted-publishers/using-a-publisher/>
