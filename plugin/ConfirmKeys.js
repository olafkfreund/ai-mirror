.pragma library

// The confirm dialog's key rule (#48). A key typed at whatever had focus must
// not grant control, so Allow is armed by a deliberate arrow or Tab first;
// only then does A confirm. Any other first key denies. Modifier keys alone
// change nothing, so Shift+A and typing a capital still work as expected.
// A repeat of a key held from before the dialog decides nothing, and an arrow
// with Ctrl/Alt/Meta (a word jump) is editing, not arming: it denies.
function decide(state, key, modifiers, autoRepeat) {
  var K = [Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down, Qt.Key_Tab, Qt.Key_Backtab]
  var MODS = [Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_AltGr, Qt.Key_Meta,
              Qt.Key_Super_L, Qt.Key_Super_R, Qt.Key_CapsLock]
  var DENY = [Qt.Key_Escape, Qt.Key_Return, Qt.Key_Enter, Qt.Key_D]
  var armed = !!state.keyArmed
  if (autoRepeat) return { answer: null, keyArmed: armed }
  if (MODS.indexOf(key) >= 0) return { answer: null, keyArmed: armed }
  if (DENY.indexOf(key) >= 0) return { answer: "deny", keyArmed: armed }
  var held = modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)
  if (K.indexOf(key) >= 0 && !held) return { answer: null, keyArmed: true }
  if (armed && key === Qt.Key_A && !held) return { answer: "confirm", keyArmed: armed }
  return { answer: "deny", keyArmed: armed }
}
