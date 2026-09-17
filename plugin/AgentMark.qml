import QtQuick
import QtQuick.Shapes
import qs.Commons

// Our own mark rather than a font glyph.
//
// The bar cannot tell two robots apart. The shell's own agents widget draws
// U+F16A3 and skal.bar maps anything named "agent" or "copilot" to U+F06A9,
// which is the glyph this widget used to use — so on a normal bar they sat
// side by side and meant different things. A drawn mark cannot collide with a
// plugin we have never heard of.
//
// A cursor rather than a robot, because the thing worth warning about is not
// that an agent exists, it is that something else is moving the pointer. The
// silhouette is also deliberately unlike nixarchy-voice's ring mark, so the
// two never blur together at 13px.
//
// Geometry is written on a 100x100 grid and scaled by `u`, so the mark keeps
// its proportions at whatever Style.bar.iconFont the theme picks.
Item {
  id: root

  property real iconSize: 16
  property color color: Color.foreground
  // Control is live: fill the cursor and let it throw motion arcs.
  property bool active: false

  readonly property real u: iconSize / 100

  implicitWidth: iconSize
  implicitHeight: iconSize
  width: iconSize
  height: iconSize

  Shape {
    anchors.fill: parent
    antialiasing: true
    layer.enabled: true
    layer.samples: 4

    // ---- cursor ---------------------------------------------------------
    // Hollow while control is off: present, clearly not driving anything.
    ShapePath {
      fillColor: root.active ? root.color : "transparent"
      strokeColor: root.active ? "transparent" : root.color
      strokeWidth: 7 * root.u
      joinStyle: ShapePath.RoundJoin
      capStyle: ShapePath.RoundCap

      startX: 24 * root.u; startY: 14 * root.u
      PathLine { x: 24 * root.u; y: 70 * root.u }
      PathLine { x: 37 * root.u; y: 58 * root.u }
      PathLine { x: 46 * root.u; y: 78 * root.u }
      PathLine { x: 56 * root.u; y: 74 * root.u }
      PathLine { x: 47 * root.u; y: 54 * root.u }
      PathLine { x: 64 * root.u; y: 52 * root.u }
      PathLine { x: 24 * root.u; y: 14 * root.u }
    }

    // ---- motion ---------------------------------------------------------
    // Only while control is live. Arcs sit clear of the cursor body on the
    // right, so they read as the pointer being driven rather than as noise.
    Motion { radius: 26; shown: root.active }
    Motion { radius: 38; shown: root.active }
  }

  component Motion: ShapePath {
    property real radius: 0
    property bool shown: false

    fillColor: "transparent"
    strokeColor: shown ? root.color : "transparent"
    strokeWidth: 7 * root.u
    capStyle: ShapePath.RoundCap
    PathAngleArc {
      centerX: 56 * root.u; centerY: 40 * root.u
      radiusX: radius * root.u; radiusY: radius * root.u
      startAngle: -60; sweepAngle: 80
      moveToStart: true
    }
  }
}
