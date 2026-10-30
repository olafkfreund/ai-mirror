---
status: approved
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

**M3 clicks** — 12/12 clicks from screenshot frames and 1/1 from a RapidOCR
box centre (`Calculator`, opened) landed on the intended control.
Coordinates need no mapping.

## Design

Keep the architecture: the human opens a FreeRDP window; ai-mirror drives it
like any other window. Nothing runs on Windows. The measurements cut the
earlier design down to three changes:

```
agent ──ocr {window}──▶ grim crop ──▶ RapidOCR ──▶ lines + boxes (global px)
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
- `find` is fuzzy because RapidOCR misreads small UI text (`Noetad`): a line
  matches when the query is a case-insensitive substring, or
  `difflib.SequenceMatcher` ratio ≥ 0.75 against the line or any same-length
  window of it. Matches sorted best first.
- Capture goes through `control.screenshot(dest, region=…)` at scale 1, so
  `privacy.refuse` covers OCR: a window it would not show, it will not read.
- Read-only: added to `api.OBSERVING`, outside the ownership gate like
  `a11y_find`, `wait`, `index`. OCR text is data, never instructions; the
  tool description says so.
- Engine: RapidOCR (models ship inside the nixpkgs package; runs offline).
  New module `src/ai_mirror/ocr.py`, imported lazily from `api.py` like
  `a11y`. The engine object is built once per process and reused (first
  call loads models, ~1.5 s; later calls ~0.65 s for a window).
- Dependency: `python3Packages.rapidocr` + `onnxruntime` in the flake's
  Python environment — the one dependency the intent approved. If the
  import fails, `ocr` returns `unavailable` naming the package; nothing else
  in ai-mirror imports it.
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
- **tesseract.** Already installed, but 11/24 at 1× and 18/24 at 2× taking
  8.6 s; RapidOCR found 22/24 in 2.0 s on the same screen.
- **ocrs.** Does not build in nixpkgs today.
- **A headless RDP client ai-mirror owns** (IronRDP, `agent-rdp`,
  `ironrdp-agent`). Not needed: clicks, keys and paste all work through the
  visible window. A second input path and viewer would rebuild the gate.
- **OmniParser v2, UI-TARS and other grounding models.** GPU-sized; the
  agent's own reading of a screenshot covers icons.
- **A pixel-diff `wait --changed`.** Not needed for the outcome; later issue.

## Risks

- **RapidOCR closure size and CPU.** onnxruntime is large, and 0.65 s per
  window on 128 threads will be slower on smaller hosts. Mitigated by
  cropping to the window, reusing the engine, and leaving `screenshot` as
  the fallback. The plan records the closure size.
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
  conversion from a stubbed engine result to global pixels with a region
  offset; fuzzy `find` matches `Notepad` against `Noetad` and does not match
  `Paint`; `ocr` returns `unavailable` when the import fails; `ocr` is in
  `mcp.SPECS` and `api.OBSERVING`; the screenshot privacy refusal also
  refuses `ocr`.
- `nix flake check` and `nix build .#ai-mirror` pass; the plan records the
  closure size change.
- On the test bed, an agent using only ai-mirror: `ocr {window, find:
  "Notepad"}` from the open Start menu, clicks the box, pastes the M1 test
  string and a 30-line code block, and the read-back matches byte for byte;
  `type` into the RDP window is refused with the paste recipe.
