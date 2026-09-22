# The screencast

`../assets/demo-desktop.mp4` is an agent driving a real desktop through
ai-mirror: typing (Unicode included) in a text editor, clicking a calculator to
`7+6=13`, then filling and submitting a web form in Chrome — targeted through
the accessibility tree, typed with real keystrokes — and walking browser
history with the mouse side buttons.

Re-record it after a change:

    ./rz status                 # drives ai-mirror on the desktop host over ssh
    scp testapp.html <host>:/tmp/
    scp record.sh <host>:/tmp/rec.sh
    ssh <host> 'setsid /tmp/rec.sh >/dev/null 2>&1 </dev/null &'
    ./demo.sh
    ssh <host> 'touch /tmp/STOPREC'
    ssh <host> 'cd /tmp/frames && ffmpeg -framerate 10 -pattern_type glob -i "*.jpg" \
        -c:v libx264 -pix_fmt yuv420p -crf 23 -movflags +faststart -y /tmp/demo.mp4'

`record.sh` captures frames with `grim -t jpeg` (22 ms a frame at 0.75 scale on
razer) rather than `wl-screenrec`, which recorded a frozen buffer there — every
frame of an 80 s take was identical while `screenshot` proved windows were on
screen.

`rz` exports the Hyprland session environment before calling `ai-mirror`, which
a non-login ssh shell does not have; without it every call fails with
`HYPRLAND_INSTANCE_SIGNATURE not set` (and `doctor` still passes — #32).

`demo.sh` opens the editor on an explicit fresh file: the unnamed draft buffer
is restored on every launch, so a second take appends under the first.

`demo.sh` takes `RZ_BIN` (the driver to use, default `./rz`) and `GEN` (the
control generation from `status`), so the same script can drive an installed
ai-mirror or a working copy:

    RZ_BIN=./rzdev GEN=19 ./demo.sh
