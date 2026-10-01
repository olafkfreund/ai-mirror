// Runs the shipped plugin/ConfirmKeys.js against Qt 6's numeric key values.
import test from "node:test"
import assert from "node:assert/strict"
import vm from "node:vm"
import { readFileSync } from "node:fs"

const VALUES = {
  Key_A: 0x41, Key_D: 0x44, Key_Escape: 0x01000000, Key_Tab: 0x01000001,
  Key_Backtab: 0x01000002, Key_Return: 0x01000004, Key_Enter: 0x01000005,
  Key_Left: 0x01000012, Key_Up: 0x01000013, Key_Right: 0x01000014,
  Key_Down: 0x01000015, Key_Shift: 0x01000020, Key_Control: 0x01000021,
  Key_Meta: 0x01000022, Key_Alt: 0x01000023, Key_CapsLock: 0x01000024,
  Key_Super_L: 0x01000053, Key_Super_R: 0x01000054, Key_AltGr: 0x01001103,
  ShiftModifier: 0x02000000, ControlModifier: 0x04000000,
  AltModifier: 0x08000000, MetaModifier: 0x10000000,
}
// A typo or a missing key throws instead of silently being undefined.
const Qt = new Proxy(VALUES, {
  get(t, name) {
    if (!(name in t)) throw new Error("unknown Qt." + String(name))
    return t[name]
  },
})
const src = readFileSync(new URL("../plugin/ConfirmKeys.js", import.meta.url), "utf8")
  .replace(/^\.pragma library\s*$/m, "")
const ctx = vm.createContext({ Qt })
vm.runInContext(src, ctx)
// JSON round-trip: objects built inside the vm have another realm's prototype.
const decide = (armed, key, mods = 0, rep = false) => JSON.parse(JSON.stringify(vm.runInContext("decide", ctx)({ keyArmed: armed }, key, mods, rep)))

const V = VALUES
const MODS = ["Key_Shift", "Key_Control", "Key_Alt", "Key_AltGr", "Key_Meta", "Key_Super_L", "Key_Super_R", "Key_CapsLock"]
const ARROWS = ["Key_Left", "Key_Right", "Key_Up", "Key_Down", "Key_Tab", "Key_Backtab"]
const DENY = ["Key_Escape", "Key_Return", "Key_Enter", "Key_D"]
const keyOf = (c) => 0x41 + c.charCodeAt(0) - 97

test("modifier alone changes nothing", () => {
  for (const m of MODS) for (const armed of [false, true])
    assert.deepEqual(decide(armed, V[m]), { answer: null, keyArmed: armed }, m)
})

test("deny keys deny, armed or not", () => {
  for (const k of DENY) for (const armed of [false, true])
    assert.deepEqual(decide(armed, V[k]), { answer: "deny", keyArmed: armed }, k)
})

test("arrows and Tab arm, and do nothing when armed", () => {
  for (const k of ARROWS) {
    assert.deepEqual(decide(false, V[k]), { answer: null, keyArmed: true }, k)
    assert.deepEqual(decide(true, V[k]), { answer: null, keyArmed: true }, k)
  }
})

test("A: denies unarmed, confirms armed", () => {
  assert.equal(decide(false, V.Key_A).answer, "deny")
  assert.equal(decide(true, V.Key_A).answer, "confirm")
})

test("other keys deny in both states", () => {
  for (const armed of [false, true]) assert.equal(decide(armed, keyOf("b")).answer, "deny")
})

test("typed words deny on the first key", () => {
  for (const w of ["banana", "hello", "a"])
    assert.equal(decide(false, keyOf(w[0])).answer, "deny", w)
})

test("Right then A confirms", () => {
  const r = decide(false, V.Key_Right)
  assert.equal(decide(r.keyArmed, V.Key_A).answer, "confirm")
})

test("Shift, Right, then Shift+A confirms", () => {
  let r = decide(false, V.Key_Shift, V.ShiftModifier)
  r = decide(r.keyArmed, V.Key_Right, V.ShiftModifier)
  assert.equal(r.keyArmed, true)
  assert.equal(decide(r.keyArmed, V.Key_A, V.ShiftModifier).answer, "confirm")
})

test("Ctrl/Alt/Meta+A denies in both states", () => {
  for (const mod of [V.ControlModifier, V.AltModifier, V.MetaModifier])
    for (const armed of [false, true])
      assert.equal(decide(armed, V.Key_A, mod).answer, "deny")
})

test("a repeat of a held key decides nothing", () => {
  for (const k of [V.Key_Right, V.Key_A, V.Key_Escape, keyOf("b")])
    for (const armed of [false, true])
      assert.deepEqual(decide(armed, k, 0, true), { answer: null, keyArmed: armed })
})

test("an arrow with Ctrl/Alt/Meta is editing: it denies and never arms", () => {
  for (const mod of [V.ControlModifier, V.AltModifier, V.MetaModifier])
    for (const armed of [false, true])
      assert.deepEqual(decide(armed, V.Key_Right, mod), { answer: "deny", keyArmed: armed })
})

test("Shift+Tab (Backtab) still arms", () => {
  assert.deepEqual(decide(false, V.Key_Backtab, V.ShiftModifier), { answer: null, keyArmed: true })
})
