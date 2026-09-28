---
status: draft
issue: 47
intent: intent/2026-09-28-47-ci-tests-and-builds.md
---

# Spec: CI runs tests and builds on every push and pull request

## Design

One workflow, `.github/workflows/check.yml`, with one job that runs the command
developers already run:

```sh
nix flake check -L
```

That single command is the whole definition of green, because `flake.nix`
`checks.x86_64-linux` already holds everything:

| check | what it proves |
|---|---|
| `unittest` | the 180 tests in `tests/` pass, inside the Nix sandbox with no Wayland (`guard` armed) |
| `licence` | `ai-mirror`, `ai-mirror-input` and `plugin` all **build**, and each ships LICENSE + NOTICE |
| `plugin` | the plugin passes the Nixarchy validator rules (manifest shape, no symlinks, no `@ai-mirror@` left) |

`-L` prints build logs, so a failing test shows its traceback in the Actions
log instead of just "builder failed".

Decisions:

- **Triggers:** `push` to `master`, and `pull_request` (any base). Nothing else.
- **Runner:** GitHub-hosted `ubuntu-latest`. The flake defines only
  `x86_64-linux`, which is what that runner is.
- **Nix:** `cachix/install-nix-action`, which installs upstream Nix with flakes
  enabled and the sandbox on. The pinned nixpkgs comes from the committed
  `flake.lock` (its only input, public `github:NixOS/nixpkgs`), so CI builds the
  same tree a developer does.
- **No cache** (intent, open question 1). Store paths come from
  cache.nixos.org, and only our three packages and the checks are built.
  Revisit if a run regularly takes more than about 10 minutes.
- **Least privilege:** `permissions: contents: read`, no secrets, no
  `pull_request_target`. A fork's PR runs with a read-only token.
- **Actions pinned by commit SHA**, with the tag in a comment. This repo drives
  a real desktop, so a moved tag should not change what runs:
  - `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1  # v7.0.1`
  - `cachix/install-nix-action@13d8dd58da0234aa297dedd986986ccb8e7f3e24  # v31.11.1`
- **`timeout-minutes: 30`**, so a hung test (for example one that polls, like
  `wait`) fails the check instead of using the 6-hour default.
- **`concurrency`** keyed on the ref with `cancel-in-progress: true`, so a new
  push to a PR cancels the superseded run.

Out of scope: branch protection or required checks (a repo setting, intent
open question 2), `tests/smoke.py` (it moves the real mouse), and Dependabot for
the pinned SHAs.

## Alternatives rejected

- **Separate steps, `python -m unittest` plus `nix build .#…`:** a second
  definition of "passes" that drifts from `nix flake check`, and it would miss
  the licence and plugin validator checks.
- **Tests outside Nix (`actions/setup-python`):** a different Python and
  PyGObject from the ones that ship, so a pass would not mean the package works.
- **`DeterminateSystems/nix-installer-action`:** installs the Determinate
  distribution by default and adds a vendor in the path for no gain here.
  Upstream Nix via `install-nix-action` matches what the flake targets.
- **Cachix or Magic Nix Cache now:** deferred per the intent. It needs a secret
  or a third-party service, which is premature before a slow run shows it is
  worth it.
- **Self-hosted runner:** a public repo's fork PRs would run untrusted code on
  our machine.
- **Pinning by tag (`@v7`):** simpler, but the tag's owner can repoint it.

## Risks

- **First runs are slower than local:** the nixpkgs build closure (Python,
  wayland, gcc) downloads from cache.nixos.org each time, because nothing is
  cached. Expect minutes, not the 13 s a warm local store takes. That is
  acceptable, and the timeout bounds it.
- **A test that reads the host:** reads are deliberately not guarded. The
  `unittest` check already runs in the Nix sandbox locally with no Hyprland,
  and passes, so a clean runner sees the same world. A new test that needs a
  live seam would fail CI. That is intended, and `guard.disarm()` tests belong
  in `smoke.py`.
- **Pinned SHAs age:** nothing updates them automatically. Bump them by hand
  when needed. Dependabot is out of scope.
- **No effect on hosts:** the workflow touches no desktop and no package.

## Verification

1. Baseline, before any change: `nix flake check -L` passes locally (done while
   writing this spec: 180 tests OK, "all checks passed!", exit 0).
2. `nix run nixpkgs#actionlint -- .github/workflows/check.yml` reports nothing.
3. The PR for #47 shows the `check` job green, and its log contains
   `Ran 180 tests` and `all checks passed!`.
4. It fails when it should: on a throwaway draft PR, add a failing assertion
   and see the job go red with the traceback in the log, then close the PR
   without merging.
5. After merge, the `push` run on `master` is green.
