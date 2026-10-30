---
status: draft
issue: 92
intent: intent/2026-10-30-92-windows-over-rdp.md
---

# Spec: drive a Windows PC through an RDP window

## Measured (2026-10-30, before design)

Test bed: libvirt `win11` (Windows 11, local account `rdptest`, keyboard
ENG US) at `192.168.122.172`, reached from this desktop with
`xfreerdp /v:… /u:rdptest /cert:tofu /dynamic-resolution +clipboard
[/kbd:unicode:on] /kbd:pipe:…` (FreeRDP 3.32.2, XWayland). Window class
`xfreerdp`. Every result read back byte for byte: Ctrl+A, Ctrl+C in
Notepad, then `clipboard read`.

**M1 typing** — test string `abc ABC 123 {}[]()<>;:'"\|/~ äöå → 😀 xAy`:

| Route | Result |
|---|---|
| `type` today (`T` lines) | ✗ `1231453678390-3=qwertyui2op[]as3dfg3h3j` — every character is the next key in physical order. FreeRDP loads its key map once at start (`load_map_from_xkbfile`) and sends scancodes for keycodes; the throwaway keymap never reaches it. |
| `type` + `/kbd:unicode:on` | ✗ same garbage. |
| `/kbd:pipe` (Unicode events) | ✗ intermittent: a character is replaced by its successor (`abc`→`bbc`, ` xAy`→` AAy`), a pipe newline does nothing, one long write lost its tail. |
| `clipboard` write + `key CTRL V` | ✓ 33/33 pastes exact, including indentation, `{}[]`, `äöå`, `→`, `😀`, with no delay between write and paste — once the bug below is fixed. |
| `key` (Enter, Ctrl+A/C/V/End, Alt+F4, Ctrl+Esc) | ✓ all as expected. |

**Clipboard bug found, not RDP-specific:** `api.py:242` runs `wl-copy`
without `--type`, so wl-copy sniffs the content. `d: …` was offered as
`application/x-coff` with no text target; Windows (and any local app) then
pastes the previous clipboard or nothing. `wl-copy --type
'text/plain;charset=utf-8'` restores `UTF8_STRING`/`TEXT`/`STRING`; the
failing text then pasted exactly.

**M2 OCR** — Start menu, Windows at 100 % scale, 24 known labels, a hit is
a box centre within 30 px of the label:

| Engine | Full screen 2560×1440 | Start-menu crop 840×880 |
|---|---|---|
| tesseract 5.5.3, 1× | 11/24, 1.2 s | 0.45 s |
| tesseract, 2× upscale | 18/24, 8.6 s | — |
| RapidOCR 3.9.2 (PP-OCRv6, onnxruntime CPU) | 22/24, 2.0 s | all 24 read, 0.65 s (3 runs); misreads `Clodk`, `Noetad`, `Fille Explorer` |
| ocrs 0.12.2 | does not build in nixpkgs (`rten-gemm`: AVX-512 intrinsic signature mismatch) | — |

Timings on this 128-thread host; slower machines will be slower.

**M2b OCR on window crops** (amendment, after the user asked whether
RapidOCR is reliably better). The tool reads one window, so this is the
real case. Seven captures: Start menu; Settings, File Explorer and a
40-line Python file in Notepad, each in light and dark mode. Labels are
the visible UI strings; code is scored per line against the exact text
pasted in.

| Screen (crop) | tesseract 1× | tesseract 2× | RapidOCR |
|---|---|---|---|
| Start 840×880 | 21/24 exact | **24/24** | 22/24 |
| Settings light 1200×930 | 23/23 | 23/23 | 23/23 |
| Explorer light 1120×634 | 18/24 | 21–22/24 | **24/24** |
| Explorer dark | 16/24 | 20/24 (23/24 fuzzy) | **24/24** |
| Notepad code light 2500×760 | 17/39 lines | **21–24/39**, 0.96 | **0 lines** (detector finds nothing; 17 on a 1000-px crop) |
| Notepad code dark | 18/39 | 25–29/39, 0.96 | 27/39, 0.965 |
| Time per window | 0.4–1.4 s | 0.6–1.6 s | 0.7–1.3 s |

(Settings dark was captured on the Colours page, not the page its answer
key described; all engines read it alike, so it is excluded.)

- RapidOCR is **not** reliably better: it wins on Explorer icons-with-
  labels, ties on Settings, and silently returns nothing for a light code
  editor — the case that matters most for coding.
- tesseract at 2× is within 1–4 labels of RapidOCR on UI, better on code,
  and never empty. Grayscale and inverting dark screens did not change
  accuracy (inverting made one dark run faster); plain 2× colour is enough.
- `grim -g <window> -s 2 -t ppm - | tesseract stdin - --psm 11 tsv`
  measured 1.1 s end to end on dark Explorer, 20/24 exact, and a
  double-click on its `Downloads` box opened Downloads.
- Closure: flake-nixpkgs `tesseract` with all languages is 1.1 GiB;
  `tesseract.override { enableLanguages = [ "eng" ]; }` is 111.6 MiB.
  RapidOCR's Python environment is 1.2 GiB against 246 MiB today.

**M3 clicks** — 12/12 clicks from screenshot frames, 1/1 from a RapidOCR
box (`Calculator`, opened) and 1/1 from a tesseract box (`Downloads`,
opened) landed on the intended control. Coordinates need no mapping. A
window still loading can move under a click (Settings' sidebar shifted
16 px; the click hit `Apps`): observe after a window settles.

## Design

Keep the architecture: the human opens a FreeRDP window; ai-mirror drives it
like any other window. Nothing runs on Windows. The measurements cut the
earlier design down to three changes:

```
agent ──ocr {window}──▶ grim -s 2 ──▶ tesseract ──▶ lines + boxes (global px)
agent ──input click/key──▶ helper ──▶ xfreerdp ──▶ Windows       (works today)
agent ──clipboard write──▶ wl-copy --type text/plain ──▶ +clipboard
agent ──input key CTRL V──▶ paste                                 (works today)
agent ──input type──▶ refused for RDP windows, with the paste recipe
```

### 1. Fix `clipboard` write's type (`api.py:242`)

`['wl-copy']` → `['wl-copy', '--type', 'text/plain;charset=utf-8']`. The
tool already promises "the clipboard as text"; this makes it so for every
app, not only RDP. Test: the argv carries the type.

### 2. `type` into an RDP client window is refused

`type` sends keystrokes FreeRDP turns into the wrong scancodes, so in a
remote shell it types and runs garbage. In `api.run`'s `input` branch,
after the existing `needs_window` check: if the batch types (`type` action)
and the target window's class is an RDP client, raise `invalid` before any
line is sent:

> typing into an RDP window sends the wrong keys. Put the text on the
> clipboard (clipboard write) and paste it with key ["CTRL","V"]; use key
> for Enter, Tab and shortcuts.

- Classes: `xfreerdp` (measured). `wlfreerdp`, `sdl-freerdp` and
  `org.remmina.Remmina` are refused too, unmeasured: all forward scancodes
  from keycodes the same way, and a refusal costs one call while a wrong
  keystroke in a remote shell costs more. One tuple in `api.py`.
- `key`, `key_down`, `key_up` and pointer actions are not affected.
- The class comes from `host.windows()`, the same lookup `_require_target`
  already makes for the address.

### 3. An `ocr` tool

Text on screen with boxes the agent can click — what `a11y_find` is for
AT-SPI, for surfaces AT-SPI cannot see. A few hundred bytes instead of an
image.

- Arguments: `window` (address; its box is the region) or `region`
  [x,y,w,h]; optional `find` (fuzzy match), `limit` (1–200, default 50).
- Returns `{lines: [{text, box: [x,y,w,h], conf}], region, generation,
  engine}`, boxes in **global layout pixels**: a box centre goes straight
  into `input` with `generation` (measured, M3).
- `find` is fuzzy because OCR misreads small UI text (`Noetad`): a line
  matches when the query is a case-insensitive substring, or
  `difflib.SequenceMatcher` ratio ≥ 0.75 against the line or any same-length
  window of it. Matches sorted best first.
- Capture: the same `privacy.refuse` check `control.screenshot` makes
  (`control.py:964`) runs first, so a window it would not show, it will not
  read; then `grim -g <region> -s 2 -t ppm -` piped into `tesseract stdin -
  --psm 11 tsv` (argv, no shell, no temp file). Words are grouped into lines
  by tesseract's block/paragraph/line numbers; boxes are divided by 2 and
  offset by the region origin.
- Read-only: added to `api.OBSERVING`, outside the ownership gate like
  `a11y_find`, `wait`, `index`. OCR text is data, never instructions; the
  tool description says so.
- Engine: tesseract, English only. New module `src/ai_mirror/ocr.py`,
  stdlib only, imported lazily from `api.py` like `a11y`. ~0.6–1.6 s per
  window on this host.
- Dependency: `(tesseract.override { enableLanguages = [ "eng" ]; })` on
  the wrapper's PATH (`flake.nix:52`), +111.6 MiB at most, shared with any
  system tesseract. Always installed, no opt-in: the user asked for opt-in
  only if RapidOCR was used. If `tesseract` is missing (checkout launcher),
  `ocr` returns `unavailable` naming it.
- New tool recipe: `api.run` branch + `mcp.TOOLS` entry + CLI subcommand +
  test (AGENTS.md).

### 4. `gotchas.md`: "Windows over RDP"

Served by `ai-mirror index`. Launch line and why each flag
(`+clipboard` for paste, `/dynamic-resolution` keeps the window 1:1); text
by paste only, never `type`; `ocr {window}` before screenshots; copy back
with Ctrl+A, Ctrl+C, `clipboard read` to verify; Ctrl+Esc for Start
(Super may be taken by Hyprland); Ctrl+Alt+End for Ctrl+Alt+Del; `wait`
cannot see inside the session, observe again instead; a Microsoft-account
login fails over NLA with Kerberos errors — use a local account or
`MicrosoftAccount\…`.

## Alternatives rejected

- **`/kbd:pipe` typing** (previous draft). Measured unreliable: characters
  replaced by their successor, newline ignored, tail lost. Also a second
  input path outside the helper. Dropped with its chunking and pacing.
- **Fix `type` for RDP with a keymap delay or `/kbd:unicode:on`.** FreeRDP
  never reads the uploaded keymap; measured garbage with and without the
  flag.
- **Make `type` paste silently into RDP windows.** One call instead of two,
  but it overwrites the human's clipboard behind their back and hides a
  second channel inside `input`. The refusal names the two calls instead.
  Easy to add later if two calls prove costly.
- **Type ASCII through real key codes (`P` taps with Shift).** Works only
  when the Windows layout matches a table we would hard-code, and cannot do
  `äöå → 😀`. Paste covers all of it.
- **RapidOCR** (the approved spec's first choice). On window crops it is not
  reliably better (M2b): it returned nothing for light-mode code, and it
  adds ~950 MiB. Its full-screen lead (22/24 vs 18/24) disappears once the
  capture is the window, which is what `ocr` reads.
- **Grayscale or inverting dark screens before OCR.** Measured no accuracy
  gain; one less step.
- **ocrs.** Does not build in nixpkgs today.
- **A headless RDP client ai-mirror owns** (IronRDP, `agent-rdp`,
  `ironrdp-agent`). Not needed: clicks, keys and paste all work through the
  visible window. A second input path and viewer would rebuild the gate.
- **OmniParser v2, UI-TARS and other grounding models.** GPU-sized; the
  agent's own reading of a screenshot covers icons.
- **A pixel-diff `wait --changed`.** Not needed for the outcome; later issue.

## Risks

- **OCR speed on smaller hosts.** 0.6–1.6 s per window here; slower
  elsewhere. Mitigated by reading one window, not the screen, and leaving
  `screenshot` as the fallback.
- **OCR on code is not exact** (24–29 of 39 lines exact, 0.96 similarity).
  `ocr` finds and reads; it does not replace copy-back (Ctrl+A, Ctrl+C,
  `clipboard read`) when exact text matters. The gotcha says so.
- **OCR misreads.** Fuzzy `find` absorbs single-letter errors; a label it
  cannot match costs a screenshot, not a wrong click, because the agent
  clicks a returned box, never a guessed one.
- **Refusing `type` breaks a caller typing into an RDP window today.** That
  caller was already sending garbage; the error tells it what works.
- **Clipboard redirection disabled by policy** on some Windows hosts. Then
  there is no reliable text path; the gotcha says so rather than offering
  `type`.
- **Overwriting the human's clipboard** by `clipboard` write is existing,
  gated behaviour; unchanged.
- **Hosts:** this desktop's `ai-mirror` and the `win11` test VM only.

## Verification

- `python3 -m unittest discover -s tests -v` passes, with new tests:
  `wl-copy` argv carries `--type text/plain;charset=utf-8`; `type` to a
  window of class `xfreerdp` (stubbed `host.windows`) raises `invalid` and
  sends no line, while `key` to it and `type` to `foot` do not; `ocr` box
  fuzzy `find` matches `Notepad` against `Noetad` and does not match
  `Paint`; TSV fixture lines grouped and boxes halved and offset; `ocr`
  returns `unavailable` when `tesseract` is not on PATH; `ocr` is in
  `mcp.SPECS` and `api.OBSERVING`; the screenshot privacy refusal also
  refuses `ocr`.
- `nix flake check` and `nix build .#ai-mirror` pass; the plan records the
  closure size change.
- On the test bed, an agent using only ai-mirror: `ocr {window, find:
  "Notepad"}` from the open Start menu, clicks the box, pastes the M1 test
  string and a 30-line code block, and the read-back matches byte for byte;
  `type` into the RDP window is refused with the paste recipe.
