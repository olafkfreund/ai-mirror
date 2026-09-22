#!/usr/bin/env bash
# ai-mirror screencast: an agent driving razer's desktop. Run while wl-screenrec records.
set -u
S="$(dirname "$0")"; RZ="${RZ_BIN:-$S/rz}"; G="${GEN:-12}"
w(){ sleep "$1"; }
addr(){ $RZ windows | python3 -c 'import sys,json;ws=json.load(sys.stdin)["windows"];print(ws[0]["address"] if ws else "")'; }

# Kill by name, not by the pid launch returns: single-instance apps hand off and
# the launcher exits, so that pid is not the window's process. Then wait for the
# desktop to be empty, so nothing from the last section is in front of the next.
cleanup(){
  timeout 15 ssh -o BatchMode=yes razer 'pkill -f "[t]ext-editor"; pkill -f "[g]nome-calculator"; pkill -f "[c]hrome-demo"' >/dev/null 2>&1
  for _ in $(seq 1 20); do
    [ -z "$(addr)" ] && return 0
    sleep 0.5
  done
}

cleanup
w 3
# --- 1. text editor: typing, unicode, selection -----------------------------
# An explicit fresh file, never the unnamed draft: the draft buffer is restored
# on every launch, which appended this run's text under the last run's.
DOC=/tmp/aim-demo-$$.txt
timeout 10 ssh -o BatchMode=yes razer "rm -f $DOC; : > $DOC" >/dev/null 2>&1
$RZ launch gnome-text-editor "$DOC" >/dev/null
$RZ wait --window-class org.gnome.TextEditor --timeout 15 >/dev/null
A=$(addr); w 1
# The editor reopens whatever was open last, so a re-record starts with the
# previous take's file in a second tab. Close the others through the frame's
# own action; harmless when there is only one.
FRAME=$($RZ a11y-find --role frame --name "Text Editor" --limit 1 \
        | python3 -c 'import sys,json;ns=json.load(sys.stdin).get("nodes") or [];print(ns[0]["id"] if ns else "")')
[ -n "$FRAME" ] && $RZ a11y-act "$FRAME" win.close-other-pages >/dev/null 2>&1
w 1
$RZ input --generation $G --window "$A" '[{"type":"type","text":"ai-mirror"}]' >/dev/null; w 1
$RZ input --generation $G --window "$A" '[{"type":"type","text":" — an agent driving a real desktop"},{"type":"key","keys":["Return"]},{"type":"key","keys":["Return"]}]' >/dev/null; w 1
$RZ input --generation $G --window "$A" '[{"type":"type","text":"keystrokes are real: æøå ÆØÅ üñé 🦊 €£¥ →"},{"type":"key","keys":["Return"]}]' >/dev/null; w 2
$RZ input --generation $G --window "$A" '[{"type":"type","text":"selection, clipboard, chords — all verified by readback"}]' >/dev/null; w 2
$RZ input --generation $G --window "$A" '[{"type":"key","keys":["Home"]},{"type":"key","keys":["End"],"modifiers":["SHIFT"]}]' >/dev/null; w 2
cleanup; w 1

# --- 2. calculator: mouse clicks -------------------------------------------
PID_CA=$($RZ launch gnome-calculator | python3 -c 'import sys,json;print(json.load(sys.stdin)["pid"])')
$RZ wait --window-class org.gnome.Calculator --timeout 15 >/dev/null; w 2
# gnome-calculator is GTK4 and exposes no buttons to accessibility, so the
# keypad can only be clicked by pixel -- and its keypad is a centred column of
# fixed width, so a fraction of a full-width window misses. Give the window a
# geometry of our own first; then the offsets below hold.
CA=$($RZ windows | python3 -c 'import sys,json;print([w["address"] for w in json.load(sys.stdin)["windows"] if w["class"]=="org.gnome.Calculator"][0])')
$RZ window float "$CA" >/dev/null; w 1
$RZ window resize "$CA" --w 500 --h 700 >/dev/null; w 1
$RZ window center "$CA" >/dev/null; w 1
eval "$($RZ windows | python3 -c '
import sys, json
win = [w for w in json.load(sys.stdin)["windows"] if w["class"] == "org.gnome.Calculator"][0]
(x, y), (w, h) = win["at"], win["size"]
for name, fx, fy in (("SEVEN", 0.112, 0.746), ("PLUS", 0.692, 0.881),
                     ("SIX", 0.498, 0.814), ("EQUALS", 0.882, 0.916)):
    print(f"{name}=\"{x + round(w * fx)} {y + round(h * fy)}\"")
')"
for xy in "$SEVEN" "$PLUS" "$SIX" "$EQUALS"; do
  set -- $xy; $RZ input --generation $G "[{\"type\":\"click\",\"x\":$1,\"y\":$2,\"button\":\"left\"}]" >/dev/null; w 1
done
w 3
cleanup; w 1

# --- 3. browser: driving a web app -----------------------------------------
PID_CH=$($RZ launch google-chrome-stable --user-data-dir=/tmp/rz-chrome-demo --no-first-run \
  --no-default-browser-check --force-renderer-accessibility --new-window file:///tmp/testapp.html \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["pid"])')
sleep 5; A=$(addr)
NODE(){ $RZ a11y-find --role "$1" --name "$2" --limit 1 | python3 -c 'import sys,json;ns=json.load(sys.stdin)["nodes"];print(ns[0]["id"] if ns else "")'; }
CUST=$(NODE entry Customer); BTN=$(NODE button "Place order"); w 1
$RZ a11y-act "$CUST" focus >/dev/null; w 1
$RZ input --generation $G --window "$A" '[{"type":"type","text":"Ada Lovelace"}]' >/dev/null; w 1
$RZ input --generation $G --window "$A" '[{"type":"key","keys":["Tab"]},{"type":"key","keys":["CTRL","a"]},{"type":"type","text":"3"}]' >/dev/null; w 1
$RZ input --generation $G --window "$A" '[{"type":"key","keys":["Tab"]},{"type":"key","keys":["Down"]},{"type":"key","keys":["Down"]}]' >/dev/null; w 2
$RZ a11y-act "$BTN" click >/dev/null; w 3
# navigate a live site, then history with the mouse side buttons
BAR=$(NODE entry "Address and search bar")
$RZ a11y-act "$BAR" focus >/dev/null; w 1
$RZ input --generation $G --window "$A" '[{"type":"key","keys":["CTRL","a"]},{"type":"type","text":"example.com"},{"type":"key","keys":["Return"]}]' >/dev/null; w 4
$RZ input --generation $G '[{"type":"click","x":960,"y":500,"button":"back"}]' >/dev/null; w 3
$RZ input --generation $G '[{"type":"click","x":960,"y":500,"button":"forward"}]' >/dev/null; w 3
cleanup; w 1
