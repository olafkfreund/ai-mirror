#!/usr/bin/env bash
# ai-mirror showcase: an agent works in a window you are not using. The cursor
# and the focused window must not move. Needs the human to press A on the dialog.
# REC=<file> records; MON=<monitor> picks the one (default: the focused one).
set -u
S="$(cd "$(dirname "$0")" && pwd)"; AI="${AI_MIRROR:-ai-mirror}"
TMP="$(mktemp -d)"; FAIL=0; G=""; CH=""; RECPID=""; DND=""
j(){ python3 -c "import sys,json;d=json.load(sys.stdin);print($1)"; }
# A terminal older than the running Hyprland (herdr, tmux) keeps a dead signature.
if ! hyprctl activewindow -j >/dev/null 2>&1; then
  for sig in $(hyprctl instances -j | j '"\n".join(i["instance"] for i in d)'); do
    HYPRLAND_INSTANCE_SIGNATURE=$sig hyprctl activewindow -j >/dev/null 2>&1 && { export HYPRLAND_INSTANCE_SIGNATURE=$sig; break; }
  done
fi
hyprctl activewindow -j | j 'd["address"]' >/dev/null 2>&1 || { echo "cannot reach Hyprland"; exit 1; }

cleanup(){
  [ "$DND" = set ] && omarchy-toggle-notification-silencing >/dev/null 2>&1   # only undo our own toggle
  # gpu-screen-recorder installs its own SIGINT handler, so this flushes the file.
  [ -n "$RECPID" ] && { kill -INT "$RECPID" 2>/dev/null; wait "$RECPID" 2>/dev/null; }
  [ -n "$CH" ] && [ -n "$G" ] && $AI window --generation "$G" close "$CH" >/dev/null 2>&1
  # A revoked grant cannot close a window, and a launch can time out with Chrome running.
  pkill -f -- "--user-data-dir=$TMP/ch" 2>/dev/null; sleep 0.5
  $AI control off >/dev/null 2>&1
  rm -rf "$TMP"
}

HOME_WIN=$(hyprctl activewindow -j | j 'd["address"]')
HOME_WS=$(hyprctl activewindow -j | j 'd["workspace"]["id"]')

trap cleanup EXIT   # before asking: an interrupted wait must still release the request
$AI control agent >/dev/null
for _ in $(seq 1 35); do
  [ "$($AI status | j 'd["owner"]')" = agent ] && break
  sleep 1
done
if [ "$($AI status | j 'd["owner"]')" != agent ]; then
  echo "no grant"; exit 1
fi
G=$($AI status | j 'd["generation"]')
[ "$(omarchy-shell notifications isDnd 2>/dev/null)" = off ] && omarchy-toggle-notification-silencing >/dev/null 2>&1 && DND=set

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
  [ -n "$node" ] || { v=no-node; FAIL=1; }
  [ "$must" = 1 ] && [ "$v" != True ] && FAIL=1
  [ "$v" = error ] && FAIL=1
  [ "$(cursor)" != "$C0" ] || [ "$(active)" != "$A0" ] && FAIL=1
  echo "$action $node: verified=$v cursor $(cursor) focused: $(active | cut -d' ' -f2)"
  sleep 1.5
}

step 1 "$SLIDER" set_value --value 7
step 1 "$(NODE 'list item' Large)" select --expect '{"role":"list item","name":"Large"}'
step 0 "$(NODE 'check box' Notify)" click
step 0 "$(NODE button Save)" click
SAVED=$($AI a11y-find --app chrome --name Saved | j '" ".join(n.get("name") or n.get("text") or "" for n in d.get("nodes", []))' 2>/dev/null)
echo "$SAVED"
[[ "$SAVED" == *"Saved: volume 7, size Large, notify on"* ]] || FAIL=1
sleep 2
exit $FAIL
