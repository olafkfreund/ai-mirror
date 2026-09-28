---
status: approved
issue: 47
spec: spec/2026-09-28-47-ci-tests-and-builds.md
---

# Plan: CI runs tests and builds on every push and pull request

Self-contained summary of the approved decisions:

- One workflow file, `.github/workflows/check.yml`, with one job running
  `nix flake check -L`. That command is the whole definition of green. It covers
  the `unittest` check, the `licence` check (which builds `ai-mirror`,
  `ai-mirror-input` and `plugin`) and the `plugin` validator check.
- Triggers: `push` to `master` and `pull_request`. Nothing else.
- Runner: GitHub-hosted `ubuntu-latest` (x86_64-linux, the flake's only system).
- Nix via `cachix/install-nix-action` (upstream Nix, flakes on, sandbox on).
  nixpkgs comes from the committed `flake.lock`.
- No cache. Revisit if runs regularly take more than about 10 minutes.
- `permissions: contents: read`, no secrets, no `pull_request_target`.
- Actions pinned by full commit SHA, with the tag in a comment:
  checkout `3d3c42e5aac5ba805825da76410c181273ba90b1` (v7.0.1),
  install-nix-action `13d8dd58da0234aa297dedd986986ccb8e7f3e24` (v31.11.1).
- `timeout-minutes: 30`. `concurrency` is keyed on the ref with
  `cancel-in-progress: true`.
- Out of scope: branch protection, `tests/smoke.py`, Dependabot.

## Steps

1. `.github/workflows/check.yml`: create it with exactly this content:

   ```yaml
   name: check

   on:
     push:
       branches: [master]
     pull_request:

   permissions:
     contents: read

   concurrency:
     group: check-${{ github.ref }}
     cancel-in-progress: true

   jobs:
     check:
       runs-on: ubuntu-latest
       timeout-minutes: 30
       steps:
         - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
         - uses: cachix/install-nix-action@13d8dd58da0234aa297dedd986986ccb8e7f3e24 # v31.11.1
         - run: nix flake check -L
   ```

   → verify by `nix run nixpkgs#actionlint -- .github/workflows/check.yml`,
   which prints nothing and exits 0.
   Commit: `ci: run nix flake check on every push and pull request (#47)`.

2. Local green: `nix flake check -L` → `Ran 180 tests … OK` and
   `all checks passed!`, exit 0.

3. Push `ci/47-tests-and-builds` and open a PR against `master`. The
   description links `intent/`, `spec/` and `plan/` for this slug and says
   `Closes #47`. → verify by the PR's `check` job going green, with
   `Ran 180 tests` and `all checks passed!` in its log.

4. It fails when it should. From the PR branch, create
   `ci/47-red-check` with one extra file, `tests/test_ci_red.py`:

   ```python
   import unittest


   class Red(unittest.TestCase):
       def test_red(self):
           self.fail('CI must go red on a failing test')
   ```

   Push it and open a **draft** PR titled `DO NOT MERGE: CI red check (#47)`.
   → verify by the `check` job failing, with `CI must go red on a failing test`
   in its log. Then close that PR unmerged and delete the `ci/47-red-check`
   branch, both locally and on the remote. Nothing from it reaches the #47 PR.

5. After you merge the #47 PR: → verify by the `push` run on `master` going
   green.

## Tests

```sh
nix run nixpkgs#actionlint -- .github/workflows/check.yml   # no output, exit 0
nix flake check -L                                        # all checks passed!, exit 0
gh pr checks <pr-number> --watch                          # check: pass (step 3), fail (step 4)
gh run list --branch master --workflow check.yml --limit 1  # completed / success (step 5)
```

## Rollback

Delete `.github/workflows/check.yml` (or `git revert` the step-1 commit) and
push. Nothing else changes: no repo settings, secrets or packages are touched.
If a run misbehaves before a revert lands, disable it with
`gh workflow disable check.yml`.
