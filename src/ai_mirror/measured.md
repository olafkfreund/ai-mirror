# Measured: what a11y_act does, per app

**Measured examples, not a toolkit rule** (Hyprland, 2026-10-23, target window
unfocused): no action below changed the active window, the workspace or the
pointer. Re-measure on your host.

| App | Element | Actions offered | Tried | Result |
|---|---|---|---|---|
| GTK4 calculator | button | `click` | click | ok |
| GTK4 calculator | entry | `text.*`, `clipboard.*`, `menu.popup` | set_text | the app accepts it, but the text cannot be read back, so `not_confirmed`: screenshot to check |
| GTK4 calculator | button | `click` | focus | `atspi_error` (grab_focus unsupported) |
| Chrome | button | `press` | click | ok, in-page focus moves |
| Chrome | check box | `check` | click | ok (`check` counts as a click since #65) |
| Chrome | entry | `activate` | set_text | `unsupported` (no EditableText) |
| Chrome | entry | `activate` | focus | ok, in-page focus moves |
| Chrome | link | `jump` | click | ok |
| Firefox | button, link | `press`, `jump` | click | ok |
| Firefox | check box | `check` | click | ok (`check` counts as a click since #65) |
| Firefox | entry | `activate` | set_text, focus | ok |
| Chrome, Firefox | slider | Value | set_value | ok, read back (#70) |
| Chrome | spin button | Value | set_value | value unchanged: `not_confirmed` |
| Firefox | spin button | Value | set_value | ok |
| Chrome, Firefox | `<select size=4>` item | Selection on parent | select | ok, read back |
| Chrome, Firefox | ARIA `role=option` | Selection on parent | select | `not_confirmed`: the page owns `aria-selected` |
| Chrome | ARIA tab | Selection on parent | select | `unavailable` |
| Firefox | browser tab | Selection on tab bar | select | switches the tab |

Firefox exposes no content while its window is on a hidden workspace; Chrome
and GTK4 do.
