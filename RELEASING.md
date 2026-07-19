# Releasing Macropad

Releases publish the `poor-mans-macropad` distribution. Its command and import package remain
`macropad`. This file is the maintainer checklist for every release.

## Release Infrastructure

The one-time release setup is complete:

- PyPI publishes through a Trusted Publisher for project `poor-mans-macropad`, GitHub repository
  `rafaelglikis/macropad`, workflow `release.yml`, and environment `pypi`.
- The GitHub `pypi` environment accepts deployments only from tags matching `v*`.
- The `Protect release tags` ruleset restricts creating, updating, and deleting `v*` tags to
  repository administrators.
- `main` requires a pull request, linear history, resolved conversations, and a successful
  `Package and operations` check.
- `.github/workflows/release.yml` verifies, builds, publishes to PyPI, and then creates the GitHub
  release from the same artifacts.

No PyPI API token or GitHub repository secret is required. GitHub OIDC provides a short-lived PyPI
credential, and the publishing action creates attestations by default.

## Prepare A Release

Choose the next version using semantic versioning. Use a patch release for compatible fixes, a minor
release for compatible features, and a major release for incompatible changes.

1. Set the intended version once, then create a release branch from current `main`:

```bash
VERSION=0.1.1
git switch main
git pull --ff-only origin main
git switch -c "release/${VERSION}"
```

2. Update `project.version` and the lockfile together:

```bash
uv version "${VERSION}"
```

3. Update `CHANGELOG.md`. Move the relevant entries from `Unreleased` under a heading formatted as
   `## [<version>] - YYYY-MM-DD`, leave a fresh empty `Unreleased` section, and update the comparison
   links at the bottom of the file. Include only user-facing changes and verify the release heading
   matches `project.version`.

4. Run the complete local release checks in this order:

```bash
uv lock --check
make format
make lint
make test
make test-wheel
make test-service
make test-systemd
make build
uvx twine check dist/*
```

5. Confirm both entry points report the new version:

```bash
uv run macropad --version
uv run python -m macropad --version
```

6. Commit and push the release branch, then open a pull request into `main`:

```bash
git add pyproject.toml uv.lock CHANGELOG.md
git commit -m "Prepare version ${VERSION}"
git push -u origin "release/${VERSION}"
gh pr create --base main --fill
```

Include other intentional release-note or documentation files in the commit when applicable. Do not
include generated files from `dist/`.

7. Wait for every pull-request check to pass, resolve all review conversations, and merge using
squash or rebase so `main` remains linear.

## Publish A Release

1. Synchronize local `main` and verify the working tree is clean:

```bash
git switch main
git pull --ff-only origin main
git status --short
```

2. Read the merged package version, construct its tag, and confirm CI passed for this exact `main`
   commit:

```bash
VERSION=$(uv version --short)
TAG="v${VERSION}"
printf 'Publishing %s from %s\n' "${TAG}" "$(git rev-parse HEAD)"
```

3. Create and push a matching immutable tag:

```bash
git tag "${TAG}"
git push origin "${TAG}"
```

The tag must match `project.version` with a leading `v`. The release workflow rejects tags whose
commit is not reachable from the default branch, tags that do not match the package version, and
stale lockfiles.

4. Find and follow the release workflow:

```bash
RUN_ID=$(gh run list --workflow release.yml --branch "${TAG}" --limit 1 \
  --json databaseId --jq '.[0].databaseId')
gh run watch "$RUN_ID" --exit-status
```

The workflow performs the following operations in order:

1. Installs native build dependencies and the pinned `uv` version.
2. Verifies the tag, default-branch ancestry, and lockfile.
3. Runs lint, unit, wheel, service, and systemd checks.
4. Builds one wheel and one source archive without using a dependency cache.
5. Publishes those artifacts to PyPI through Trusted Publishing.
6. Creates a GitHub release with generated notes and the same artifacts.

## Verify A Release

1. Restore the release variables if verification runs in a new shell:

```bash
VERSION=$(uv version --short)
TAG="v${VERSION}"
```

2. Check the PyPI and GitHub release pages:

- `https://pypi.org/project/poor-mans-macropad/<version>/`
- `https://github.com/rafaelglikis/macropad/releases/tag/v<version>`

3. Install from PyPI rather than the checkout and verify the command:

```bash
uvx --refresh-package poor-mans-macropad \
  --from "poor-mans-macropad==${VERSION}" macropad --version
```

4. Confirm the GitHub release contains exactly one wheel and one source archive:

```bash
gh release view "${TAG}" --json url,isDraft,isPrerelease,assets
```

## Recover From A Failed Release

Use the existing tag and workflow run when the failure is configuration-only and no source change is
needed:

```bash
gh run rerun "$RUN_ID" --failed
gh run watch "$RUN_ID" --exit-status
```

For a Trusted Publishing failure, compare the workflow's rendered OIDC claims with the PyPI
publisher. The expected values are repository `rafaelglikis/macropad`, workflow `release.yml`, and
environment `pypi`.

If PyPI publication succeeded but GitHub release creation failed, rerunning failed jobs retries only
the GitHub release job. Do not republish the package.

If any artifact for a version reached PyPI, that version is immutable. Never move its tag or try to
replace its files. Fix the problem, increment the patch version, and follow the complete release
process again. Yank a broken PyPI release instead of deleting and reusing its version.

If no artifact reached PyPI but the source must change, prefer a new patch version rather than
retargeting the existing release tag. This keeps public tags and workflow history trustworthy.
