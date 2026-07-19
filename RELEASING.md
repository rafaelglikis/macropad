# Releasing Macropad

Releases publish the `poor-mans-macropad` distribution. Its command and import package remain
`macropad`.

## One-Time PyPI Setup

1. Create a PyPI account at <https://pypi.org/account/register/> and enable two-factor
   authentication.
2. Open PyPI's publishing settings and add a pending Trusted Publisher with these exact values:
   - PyPI project name: `poor-mans-macropad`
   - GitHub owner: `rafaelglikis`
   - GitHub repository: `macropad`
   - Workflow filename: `release.yml`
   - Environment name: `pypi`
3. In the GitHub repository settings, create an environment named `pypi`. Add required reviewers if
   more than one release maintainer has repository write access.
4. If the repository visibility and GitHub plan support rulesets, protect tags matching `v*` so only
   release maintainers can create or update them.

The pending publisher creates the PyPI project on the first successful release. No API token or
repository secret is needed. The workflow requests a short-lived PyPI credential through GitHub OIDC
and publishes attestations by default.

## Publish A Release

1. Update `project.version` in `pyproject.toml` and run `uv lock`.
2. Add release notes or other version-specific documentation as needed.
3. Run `uv lock --check`, `make format`, `make lint`, `make test`, `make test-wheel`,
   `make test-service`, `make test-systemd`, and `make build`.
4. Commit the release changes, merge them into the default branch, and wait for CI to pass.
5. Create a matching tag from that default-branch commit, such as `v0.1.0` for package version
   `0.1.0`, then push it:

```bash
git tag v0.1.0
git push origin v0.1.0
```

`.github/workflows/release.yml` rejects a commit not reachable from the default branch, a tag that
does not match `project.version`, or a stale lockfile. It builds one wheel and source archive,
publishes those exact artifacts to PyPI, and creates a GitHub release with the same files after
publication succeeds.
