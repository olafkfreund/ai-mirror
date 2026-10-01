.pragma library

// The confirm dialog's key rule (#48). A key typed at whatever had focus must
// not grant control, so every key in the first second after a request appears
// denies. Once state.ready, A (Shift is fine) confirms and any other key denies.
// Escape, Return, Enter and D deny at any time. A modifier alone, or a repeat
// of a key held from before the dialog, decides nothing. Returns "confirm",
// "deny" or null.
function decide(state, key, modifiers, autoRepeat) {
  var MODS = [Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_AltGr, Qt.Key_Meta,
              Qt.Key_Super_L, Qt.Key_Super_R, Qt.Key_CapsLock]
  var DENY = [Qt.Key_Escape, Qt.Key_Return, Qt.Key_Enter, Qt.Key_D]
  if (autoRepeat) return null
  if (MODS.indexOf(key) >= 0) return null
  if (DENY.indexOf(key) >= 0) return "deny"
  if (!state.ready) return "deny"
  var held = modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)
  if (key === Qt.Key_A && !held) return "confirm"
  return "deny"
}
