# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

`nxtgenhub/nxg-github-actions` is a shared library of reusable GitHub Actions workflows and composite
actions used by other nxtgenhub repos for CI/CD. Callers reference these via
`uses: nxtgenhub/nxg-github-actions/.github/...@<ref>` (see `.github/workflows/app-ci.yml` for the
calling pattern). Currently active development happens on the `deploys` branch, not `main`.

A caller repo drives the pipeline by dropping a `pipeline.yml` manifest in its root (see the top-level
`pipeline.yml` in this repo for the schema/example) declaring `validate`, `build`, and `deploy` stages.

## Architecture: manifest-driven pipeline

The core design is a **plan/fan-out** pattern:

1. **Plan** (`.github/actions/parse-manifest`, Python) reads the caller's `pipeline.yml`, cross-references
   `.github/config/registries.yml` for registry auth/endpoint metadata, and emits GitHub Actions job
   outputs: a `has-*` boolean flag and a `*-matrix` JSON array for each stage type (validate-npm,
   validate-python, build-pack-cli, build-docker, deploy-cloudrun, deploy-azure-ca).
2. **Fan-out** (`.github/workflows/_reusable-app-cicd.yml`, the main reusable workflow) consumes those
   outputs as `strategy.matrix` inputs to conditionally run parallel jobs (`if: needs.plan.outputs.has-X
   == 'true'`), each delegating to the matching composite action in `.github/actions/`.
3. Deploy jobs depend on the validate/build jobs and only run if none failed (`!contains(needs.*.result,
   'failure')`).

Manifest entries are matched to their target composite action purely by the `type:` field
(`npm-jest`, `python-pytest`, `pack-cli`, `docker`, `cloudrun`, `azure-ca`) — see
`parse_manifest.py`'s `_validate_matrix` / `_build_matrix` / `_deploy_matrix` helpers. Docker build
entries get enriched with resolved registry metadata (`registry-type`, `registry-endpoint`,
`registry-auth`, etc.) from `registries.yml` at plan time via `_normalize_entry`.

Deploy targets link to build entries by `target` (matching a build's `id`) or by supplying a literal
`image` directly — the two are mutually exclusive (enforced in `_deploy_matrix`).

## Composite actions (`.github/actions/`)

- `parse-manifest` — the planner (Python + PyYAML). Has the only test suite in the repo.
- `build-docker` — resolves image name/tag, checks if the image already exists (skips rebuild if so),
  logs into the target registry (GAR or ACR) via `login-gar`/`login-acr`, then builds and pushes.
- `build-pack-cli` — same image-resolution/dedup pattern as `build-docker` but for Cloud Native
  Buildpacks. **The actual `pack build` step is commented out** — treat this action as unfinished.
- `login-gar` / `login-acr` — workload-identity-federation login helpers, invoked conditionally by
  `build-docker` based on `registry-type`.
- `deploy-cloudrun` — action.yml is currently **empty** (not yet implemented).
- `validate-npm-jest` / `validate-python-pytest` — install deps (with lockfile-aware fallback) and run
  the project's test suite, surfacing JUnit results via a test-reporter action.

## Known incomplete areas

Several pieces referenced by the plan/fan-out design are stubbed or missing — don't assume they work
end-to-end:
- `deploy-cloudrun/action.yml` is empty.
- No `deploy-azure-ca` composite action exists yet, though `_reusable-app-cicd.yml` defines its plan
  outputs and `pipeline.yml` has an `azure-ca` example.
- `build-pack-cli`'s actual build/publish step is commented out.
- The `deploy-cloudrun` job in `_reusable-app-cicd.yml` resolves a deploy ref but doesn't yet invoke a
  deploy step.
- `.github/actions/ACTIONS.md` and `.github/workflows/WORKFLOWS.md` are placeholder files (empty).

## Testing

The only automated tests are for `parse-manifest`:

```bash
cd .github/actions/parse-manifest
pip install -r requirements.txt
pytest tests/
```

`node-app-test/` is a minimal Express app (`npm test` runs Jest) used as a fixture/example for
exercising the `validate-npm-jest` and `build-docker` actions, not a production service.

There is no top-level lint/build command for this repo; validity is effectively "the workflows run
correctly on GitHub Actions."
