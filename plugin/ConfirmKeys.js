.pragma library

// The confirm dialog's key rule (#48). A key typed at whatever had focus must
// not grant control, so Allow is armed by a deliberate arrow or Tab first;
// only then does A confirm. Any other first key denies. Modifier keys alone
// change nothing, so Shift+A and typing a capital still work as expected.
function decide(state, key, modifiers) {
  var K = [Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down, Qt.Key_Tab, Qt.Key_Backtab]
  var MODS = [Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_AltGr, Qt.Key_Meta,
              Qt.Key_Super_L, Qt.Key_Super_R, Qt.Key_CapsLock]
  var DENY = [Qt.Key_Escape, Qt.Key_Return, Qt.Key_Enter, Qt.Key_D]
  var armed = !!state.keyArmed
  if (MODS.indexOf(key) >= 0) return { answer: null, keyArmed: armed }
  if (DENY.indexOf(key) >= 0) return { answer: "deny", keyArmed: armed }
  if (K.indexOf(key) >= 0) return { answer: null, keyArmed: true }
  var held = modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)
  if (armed && key === Qt.Key_A && !held) return { answer: "confirm", keyArmed: armed }
  return { answer: "deny", keyArmed: armed }
}
