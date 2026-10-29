---
status: approved
issue: 83
intent: intent/2026-10-29-83-layer-furniture-rivals.md
---

# Spec: typing into a panel works when only the desktop's furniture shares its level

## Design

**One definition of furniture, used by both guards.** Furniture is a surface that has
been mapped continuously since the grant: `baseline_layers` minus anything seen to
leave. That is #39's rule, which `_refuse_new_surfaces` (`src/ai_mirror/control.py`
~685-745) already applies to window typing. Today the layer guard, `_require_layer`
(~747-777), ignores it.

1. **Extract** the baseline bookkeeping from `_refuse_new_surfaces` into
   `_furniture(mapped) -> set[str] | None`. It reads state, computes `still`, and
   persists departures under the lock exactly as now. It returns the furniture
   namespaces, or `None` when the grant has no baseline (granted before #29's
   snapshot). `_refuse_new_surfaces` calls it and keeps its behaviour and messages
   unchanged.
2. **`_require_layer`** gets the furniture set and narrows its rivals. Another surface
   blocks when:
   - it is at a **higher** level than the target, furniture or not; or
   - it is at the **same** level and is not furniture.

   *Decided (intent open question, option b; the user approved without choosing,
   so this is the recommended default):* furniture above the target still blocks;
   only same-level furniture is ignored. That is the smallest widening that unblocks
   p620, where Nixi, `omarchy-notifications` and `accent-hold` are all at level 3.
3. **`None` furniture** (no baseline) keeps today's rule: every surface at the same
   level or above blocks. A failed `host.layers()` still falls through to
   `_require_focus` and is refused for a layer target (`_require_target`, unchanged).
4. **The message** for a refusal stays "another surface is open at the same level or
   above: …", listing only the surfaces that actually block. A same-level surface
   that left and came back is not furniture, so it blocks and is named.

No other call site changes. `_require_target`, `run_batch` and the key-release rescue
keep their logic.

## Alternatives rejected

- **Option (a): furniture never blocks, at any level.** It unblocks the same case
  but also lets furniture *above* a panel sit over it unnoticed. That is wider than
  p620 needs.
- **A namespace allowlist** (`omarchy-notifications`, `accent-hold`): it must be
  updated for every shell and plugin, and the existing baseline already answers the
  question. The intent rules it out.
- **Ask Hyprland which layer has the keyboard:** 0.56 doesn't say (measured, #29).
- **Leave it and type with `wtype`:** no guard at all. The intent's incident shows
  where that lands.

## Risks

- **Furniture that takes the keyboard.** A same-level notification with an inline
  reply could hold the keys while the agent types at the panel. The window path has
  accepted this since #39. The note still says delivery is NOT verified. All hosts.
- **Namespace granularity.** Furniture is matched by namespace, as #39 does: a second
  surface opened under a furniture namespace (a second notifications surface) counts
  as furniture. Same exposure as window typing today.
- **Behaviour on razer and other hosts:** strictly fewer refusals, and only where the
  sole same-level rivals were mapped continuously since the grant.

## Verification

- Unit tests in `tests/test_layer_typing.py`, granting with a level-3 furniture
  surface in the baseline:
  - the panel is typed into when the only same-level rival is furniture;
  - a surface that **opened** at the same level after the grant still refuses;
  - furniture that **left and came back** refuses;
  - furniture **above** the panel's level still refuses (option b);
  - a grant with **no baseline** keeps today's refusal;
  - the existing tests are unchanged, including a failed layer read never typing
    into a surface.
- Full suite: `python -m unittest discover -s tests`, with and without
  `HYPRLAND_INSTANCE_SIGNATURE`, and CI `check` green.
- Live on p620 after deploy: open Nixi (SUPER+H), then `input` type addressed to its
  layer. The text arrives in Nixi, with no `wrong_target`.
