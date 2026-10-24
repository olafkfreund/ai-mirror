#!/usr/bin/env bash
# ai-mirror showcase: an agent works in a window you are not using. The cursor
# and the focused window must not move. Needs the human to press A on the dialog.
# REC=<file> records; MON=<monitor> picks the one (default: the focused one).
set -u
S="$(cd "$(dirname "$0")" && pwd)"; AI="${AI_MIRROR:-ai-mirror}"
TMP="$(mktemp -d)"; FAIL=0; G=""; CH=""; RECPID=""
j(){ python3 -c "import sys,json;d=json.load(sys.stdin);print($1)"; }

cleanup(){
  omarchy-toggle-notification-silencing >/dev/null 2>&1   # toggles back
  [ -n "$RECPID" ] && { kill -INT "$RECPID" 2>/dev/null; wait "$RECPID" 2>/dev/null; }
  [ -n "$CH" ] && [ -n "$G" ] && $AI window --generation "$G" close "$CH" >/dev/null 2>&1
  $AI control off >/dev/null 2>&1
  rm -rf "$TMP"
}

HOME_WIN=$(hyprctl activewindow -j | j 'd["address"]')
HOME_WS=$(hyprctl activewindow -j | j 'd["workspace"]["id"]')

$AI control agent >/dev/null
for _ in $(seq 1 35); do
  [ "$($AI status | j 'd["owner"]')" = agent ] && break
  sleep 1
done
if [ "$($AI status | j 'd["owner"]')" != agent ]; then
  echo "no grant"; $AI control off >/dev/null 2>&1; exit 1
fi
G=$($AI status | j 'd["generation"]')
trap cleanup EXIT
omarchy-toggle-notification-silencing >/dev/null 2>&1

CH=$($AI launch --generation "$G" --timeout 15 -- google-chrome-stable --user-data-dir="$TMP/ch" \
  --no-first-run --no-default-browser-check --force-renderer-accessibility --new-window \
  "file://$S/background.html" | j 'd.get("window","")')
[ -n "$CH" ] || { echo "no chrome window"; exit 1; }
$AI window --generation "$G" workspace "$CH" --workspace "$HOME_WS" >/dev/null
$AI window --generation "$G" focus "$HOME_WIN" >/dev/null
sleep 1

if [ -n "${REC:-}" ]; then
  MON="${MON:-$(hyprctl monitors -j | j '[m["name"] for m in d if m["focused"]][0]')}"
  gpu-screen-recorder -w "$MON" -f 30 -k h264 -q very_high -o "$REC" >/dev/null 2>&1 &
  RECPID=$!; sleep 2
fi

NODE(){ $AI a11y-find --app chrome --role "$1" --name "$2" --limit 1 | j '(d["nodes"] or [{"id":""}])[0]["id"]'; }
SLIDER=""
for _ in $(seq 1 20); do SLIDER=$(NODE slider Volume); [ -n "$SLIDER" ] && break; sleep 1; done
[ -n "$SLIDER" ] || { echo "page not in the accessibility tree"; exit 1; }

cursor(){ hyprctl cursorpos | tr -d ' '; }
active(){ hyprctl activewindow -j | j 'd["address"]+" "+d["class"]'; }
C0=$(cursor); A0=$(active)

# step <must-verify 0|1> <node> <action> [args...]
step(){
  local must=$1 node=$2 action=$3; shift 3
  local out v
  out=$($AI a11y-act --generation "$G" "$node" "$action" "$@" 2>&1)
  v=$(printf '%s' "$out" | j 'd.get("verified")' 2>/dev/null || echo error)
  [ "$must" = 1 ] && [ "$v" != True ] && FAIL=1
  [ "$(cursor)" != "$C0" ] || [ "$(active)" != "$A0" ] && FAIL=1
  echo "$action $node: verified=$v cursor $(cursor) focused: $(active | cut -d' ' -f2)"
  sleep 1.5
}

step 1 "$SLIDER" set_value --value 7
step 1 "$(NODE 'list item' Large)" select --expect '{"role":"list item","name":"Large"}'
step 0 "$(NODE 'check box' Notify)" click
step 0 "$(NODE button Save)" click
$AI a11y-find --app chrome --name Saved | j '[n.get("name") or n.get("text") for n in d["nodes"]]'
sleep 2
exit $FAIL
