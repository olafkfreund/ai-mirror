"""Switch the overlay's badge without making the shell's login theme a desktop preference."""
import json
import os
import subprocess
import sys

from . import control, guard

BADGE = 'ai-mirror-agent'

# Read the current compositor environment in one IPC call. hl.env changes it for
# future clients, but cannot change the environment of an already running shell.
PREFERENCE = """
local native = hl.get_config("cursor.enable_hyprcursor") and os.getenv("HYPRCURSOR_THEME")
if native == "" then native = nil end
local theme = native or os.getenv("XCURSOR_THEME") or "default"
local size = (native and os.getenv("HYPRCURSOR_SIZE")) or os.getenv("XCURSOR_SIZE") or "24"
local synced = not native and hl.get_config("cursor.sync_gsettings_theme")
return table.concat({synced and "synced" or "configured", size, theme}, "\\n")
"""


def configured_cursor():
    output = subprocess.check_output(['hyprctl', 'repl', PREFERENCE], text=True, timeout=5)
    mode, size, theme = output.removesuffix('\n').split('\n', 2)
    if mode not in ('synced', 'configured'):
        raise ValueError('unexpected cursor settings from Hyprland')
    size = int(size) if size.isdecimal() else 0
    if not theme or theme == BADGE:
        theme = 'default'
    return [theme, size if size > 0 else 24], mode == 'synced'


def gtk_settings():
    from gi.repository import Gio

    schemas = Gio.SettingsSchemaSource.get_default()
    if schemas and schemas.lookup('org.gnome.desktop.interface', True):
        return Gio.Settings.new('org.gnome.desktop.interface')


def gtk_cursor(settings):
    if settings:
        theme = settings.get_string('cursor-theme')
        size = settings.get_int('cursor-size')
        if theme and theme != BADGE and size > 0:
            return [theme, size]


def restore_gtk(settings, cursor):
    # Switching back to a native Hyprcursor theme can leave the Xcursor badge in GTK.
    if settings and settings.get_string('cursor-theme') == BADGE:
        guard.check('GSettings cursor restore', 'cursor.restore_gtk')
        theme, size = cursor
        # Leave the badge in place until the size is restored so a retry still sees it.
        if settings.get_int('cursor-size') != size and not settings.set_int('cursor-size', size):
            raise RuntimeError('GSettings rejected cursor-size restore')
        if not settings.set_string('cursor-theme', theme):
            raise RuntimeError('GSettings rejected cursor-theme restore')
        settings.sync()


def set_cursor(cursor):
    guard.check('hyprctl setcursor', 'cursor.set_cursor')
    reply = subprocess.check_output(['hyprctl', 'setcursor', cursor[0], str(cursor[1])],
                                    text=True, timeout=5)
    if reply.strip() != 'ok':
        raise RuntimeError(f'hyprctl setcursor: {reply.strip()}')


def sync(agent):
    instance = os.environ['HYPRLAND_INSTANCE_SIGNATURE']
    with control.locked('cursor'):
        path = control.root() / f'cursor-{instance}.json'
        try:
            saved = json.loads(path.read_text())
        except FileNotFoundError:
            saved = None
        if not agent and saved is None:
            return

        configured, synced = configured_cursor()
        settings = gtk_settings()
        human_gtk = gtk_cursor(settings)
        if agent:
            if saved is None:
                # With GSettings sync, a manual setcursor may be newer than XCURSOR_THEME.
                desktop = human_gtk if synced and human_gtk else configured
                saved = {'desktop': desktop, 'configured': configured, 'gtk': human_gtk}
                control.atomic_write_json(path, saved)
            set_cursor([BADGE, saved['desktop'][1]])
        else:
            # A theme switch during the grant takes precedence over the snapshot.
            desktop = configured if configured != saved['configured'] else saved['desktop']
            if synced and human_gtk:
                desktop = human_gtk
            set_cursor(desktop)
            restore_gtk(settings, desktop if synced else (human_gtk or saved['gtk'] or desktop))
            path.unlink()


if __name__ == '__main__':
    mode, = sys.argv[1:]
    if mode not in ('agent', 'desktop'):
        sys.exit('expected agent or desktop')
    sync(mode == 'agent')
