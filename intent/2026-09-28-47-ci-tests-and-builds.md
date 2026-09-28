---
status: approved
issue: 47
author: olafkfreund
---

# Intent: CI runs tests and builds on every push and pull request

## Problem

Nothing checks a change automatically. The repo has no `.github/workflows`, so
the unit tests and the three package builds run only when someone remembers to
run `nix flake check` locally. A pull request can merge with a broken test or
a package that no longer builds, and nobody finds out until the next local run.

## Proposed outcome

Every push to `master` and every pull request shows a pass/fail check on
GitHub. The check fails if any unit test fails or if `ai-mirror`,
`ai-mirror-input` or `plugin` stops building, or if the plugin fails the
Nixarchy validator checks already in `flake.nix`.

## Affected users and systems

- Contributors and reviewers: a status check on each PR.
- GitHub Actions on the public repo (hosted `ubuntu-latest` runners, free for
  public repos).
- No change to the desktop, the packages, or any host.

## Constraints

- Must run what developers already run (`nix flake check`), not a second,
  drifting definition of "tests pass".
- Must not reach a desktop: the tests already arm `guard` and need no Wayland;
  CI must not add a live-desktop step (`tests/smoke.py` stays manual).
- No secrets and no write permissions for the workflow.
- `x86_64-linux` only — the only system `flake.nix` defines.

## Open questions

1. Cache Nix builds (e.g. Magic Nix Cache / Cachix) now, or start uncached and
   add it only if runs are slow? Proposed: start uncached.
2. Make the check required for merging into `master` (branch protection)?
   That is a repo setting outside this change.
