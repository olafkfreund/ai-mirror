#!/usr/bin/env bash
export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-1
rm -rf /tmp/frames; mkdir -p /tmp/frames; rm -f /tmp/STOPREC
i=0
while [ ! -e /tmp/STOPREC ]; do
  grim -t jpeg -q 80 -s 0.75 -o eDP-1 "$(printf /tmp/frames/%05d.jpg $i)" 2>/dev/null
  i=$((i+1)); sleep 0.06
done
echo "$i frames" > /tmp/frames.count
