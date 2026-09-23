---
status: draft
issue: 39
author: olafkfreund
---

# Intent: the baseline should mean "has been there all along"

## Problem

#29's guard refuses window-addressed input while a surface that was not mapped
when control was granted is up at level 2 or above, because such a surface may
hold the keyboard and Hyprland cannot be asked which one does. The set it
compares against — `baseline_layers` — is a snapshot of the namespaces mapped
at the instant the human confirmed.

That instant is the worst one available. The thing they clicked to confirm is
itself a layer surface, so the snapshot contains it:

    baseline_layers: ['omarchy-ai-mirror-confirm', 'omarchy-background', 'omarchy-bar']

For that surface it does not matter, since it is only up while control is off.
For anything else transient it matters a lot: a notification, an OSD, a
launcher the person left open at that moment is recorded as furniture and stays
exempt **for the life of the grant** — ten minutes of a guard that was added
precisely to refuse it.

The deeper fault is that the baseline records *presence at one instant* when
what the guard wants to know is *continuous presence*. The bar and the
background are exempt because they are always there; a notification that
happened to be there once is not the same thing, and the current snapshot
cannot tell them apart.

## Proposed outcome

- A surface is exempt only while it has been mapped continuously since the
  grant. The bar and background stay exempt, because they never go.
- A transient surface present at the moment of the grant stops being exempt as
  soon as it goes, without waiting for the grant to end.
- The confirm dialog leaves the baseline by the same rule, with no special case
  for ai-mirror's own namespace.
- No new protocol, no polling, and no extra Hyprland query: the check already
  lists the mapped surfaces on every window-addressed call.

## Affected users and systems

`src/ai_mirror/control.py` — `_baseline_layers`, `_refuse_new_surfaces`, and
the control state file, which gains no new key but whose `baseline_layers` may
now shrink during a grant. Anyone driving a desktop through ai-mirror while the
shell draws anything transient, which on this desktop is every notification.

## Constraints

- Must not widen what is allowed: the change can only remove namespaces from
  the exempt set, never add them.
- Must not cost a query. The intersection uses the `host.layers()` call that
  `_refuse_new_surfaces` already makes.
- Must keep working when the baseline is absent (a grant made by an older
  build, as every grant through the bar widget was until this morning) — that
  case skips the check and must continue to.
- A state write must not race the control file's other writers; it takes the
  same lock the rest of `control.py` uses.

## Open questions

1. A surface that restarts — the bar after `omarchy-restart-shell`, say —
   disappears and comes back under the same namespace. Under this rule it
   leaves the baseline while it is gone and is then treated as new, so
   window-addressed input is refused until control is re-taken. Is that the
   right trade, or should a namespace that returns within some window be
   re-admitted? Re-admitting reopens a smaller version of the hole this fixes.
2. Should the refusal message distinguish "this appeared after the grant" from
   "this was here at the grant and went away and came back"? The second is the
   more suspicious case and the caller can act on it differently.
