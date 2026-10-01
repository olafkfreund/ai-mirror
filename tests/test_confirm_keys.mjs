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

// Answers are plain strings or null, so no JSON round-trip is needed.
const decide = (ready, key, mods = 0, rep = false) => vm.runInContext("decide", ctx)({ ready }, key, mods, rep)

const V = VALUES
const MODS = ["Key_Shift", "Key_Control", "Key_Alt", "Key_AltGr", "Key_Meta", "Key_Super_L", "Key_Super_R", "Key_CapsLock"]
const ARROWS = ["Key_Left", "Key_Right", "Key_Up", "Key_Down", "Key_Tab", "Key_Backtab"]
const DENY = ["Key_Escape", "Key_Return", "Key_Enter", "Key_D"]
const keyOf = (c) => 0x41 + c.charCodeAt(0) - 97

test("a modifier alone or a repeat decides nothing, ready or not", () => {
  for (const ready of [false, true]) {
    for (const m of MODS) assert.equal(decide(ready, V[m]), null, m)
    for (const k of [V.Key_Right, V.Key_A, V.Key_Escape, keyOf("b")])
      assert.equal(decide(ready, k, 0, true), null)
  }
})

test("Escape, Return, Enter and D deny in both states", () => {
  for (const k of DENY) for (const ready of [false, true])
    assert.equal(decide(ready, V[k]), "deny", k)
})

test("a and A (Shift) deny when not ready and confirm when ready", () => {
  for (const mods of [0, V.ShiftModifier]) {
    assert.equal(decide(false, V.Key_A, mods), "deny")
    assert.equal(decide(true, V.Key_A, mods), "confirm")
  }
})

test("arrows and Tab deny in both states", () => {
  for (const k of ARROWS) for (const ready of [false, true])
    assert.equal(decide(ready, V[k]), "deny", k)
})

test("other keys deny in both states", () => {
  for (const ready of [false, true]) assert.equal(decide(ready, keyOf("b")), "deny")
})

test("typed words deny on the first key when not ready", () => {
  for (const w of ["banana", "hello", "a"])
    assert.equal(decide(false, keyOf(w[0])), "deny", w)
})

test("Ctrl/Alt/Meta+A deny in both states", () => {
  for (const mod of [V.ControlModifier, V.AltModifier, V.MetaModifier])
    for (const ready of [false, true])
      assert.equal(decide(ready, V.Key_A, mod), "deny")
})
