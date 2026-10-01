import QtQuick
import Quickshell
import Quickshell.Wayland
import Quickshell.Hyprland
import qs.Commons
import qs.Ui
import "ConfirmKeys.js" as ConfirmKeys

// The human's half of the control gate: an agent asking for the desktop puts a
// request in the state file, and this is where it is answered.
//
// Deny is the default in every direction — Escape, Return, any key typed at
// it before Allow is armed, and the window closing under a lapsed request all
// deny. Allow is armed by an arrow or Tab, then A; a click counts only after
// the pointer has moved (ConfirmKeys.js, #48). Nothing here decides anything:
// both buttons run the CLI, and the state file is what actually changes.
Item {
  id: root
  property var request: null        // {id, by, since, expires} from state.json, or null
  property var command: null        // the Widget's Command; one process at a time is plenty
  readonly property bool opened: request !== null
  property bool keyArmed: false
  property bool pointerArmed: false
  property var pointerStart: null
  property string armedFor: ""      // the request id the flags belong to
  property double now: Date.now() / 1000
  readonly property int secondsLeft: request ? Math.max(0, Math.round(request.expires - now)) : 0

  function answer(mode) {
    if (command && request) command.run(["control", mode, String(request.id)])
  }

  Timer {
    interval: 500
    repeat: true
    running: root.opened
    onTriggered: root.now = Date.now() / 1000
  }

  // Per request, not per opening: a second `control agent` while one is pending
  // replaces the request without closing the dialog, and arming for the first
  // must not grant the second.
  onRequestChanged: if (request && request.id !== armedFor) {
    armedFor = request.id
    keyArmed = false
    pointerArmed = false
    pointerStart = null
    Qt.callLater(function () { keys.forceActiveFocus() })
  }

  PanelWindow {
    visible: root.opened
    screen: {
      var monitor = Hyprland.focusedMonitor
      for (var i = 0; i < Quickshell.screens.length; i++)
        if (monitor && Quickshell.screens[i].name === monitor.name) return Quickshell.screens[i]
      return null
    }
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    WlrLayershell.namespace: "omarchy-ai-mirror-confirm"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      acceptedButtons: Qt.NoButton
      onPositionChanged: function (m) {
        if (!root.pointerStart) root.pointerStart = { x: m.x, y: m.y }
        else if (Math.hypot(m.x - root.pointerStart.x, m.y - root.pointerStart.y) > 8)
          root.pointerArmed = true
      }
    }

    BorderSurface {
      anchors.centerIn: parent
      width: Math.min(Style.space(620), parent.width - Style.gapsOut * 2)
      height: content.implicitHeight + Style.spacing.panelPadding * 2
      color: Color.menu.background
      radius: Style.cornerRadius
      borderSpec: Border.surfaceSpec("menu", "border", Color.urgent, Math.max(1, Style.space(2)))
      padding: Style.spacing.panelPadding

      Item {
        id: keys
        anchors.fill: parent
        focus: true
        Keys.onPressed: function (event) {
          var r = ConfirmKeys.decide({ keyArmed: root.keyArmed }, event.key, event.modifiers, event.isAutoRepeat)
          root.keyArmed = r.keyArmed
          if (r.answer) root.answer(r.answer)
          event.accepted = true
        }

        Column {
          id: content
          anchors.fill: parent
          spacing: Style.spacing.md

          Text {
            width: parent.width
            text: "Let an AI agent use this desktop?"
            color: Color.menu.text
            font { family: Style.font.menuFamily; pixelSize: Math.round(Style.font.title * 1.4); bold: true }
            textFormat: Text.PlainText
          }
          Text {
            width: parent.width
            wrapMode: Text.WordWrap
            text: "It will have your keyboard and mouse, and can do anything you can do. "
                + "Super+Shift+Escape takes it back at any moment.\n\n"
                + "Asked by: " + (root.request ? root.request.by : "") + "  ·  expires in "
                + root.secondsLeft + "s"
            color: Color.menu.text
            font { family: Style.font.menuFamily; pixelSize: Math.round(Style.font.caption * 1.3) }
            textFormat: Text.PlainText
          }
          Text {
            width: parent.width
            visible: !root.keyArmed
            text: "Typing? Your next key denies this."
            color: Color.menu.text
            font { family: Style.font.menuFamily; pixelSize: Math.round(Style.font.caption * 1.3) }
            textFormat: Text.PlainText
          }
          Row {
            spacing: Style.spacing.md
            Text {
              text: "  Deny (Esc)  "
              color: Color.menu.selectedText
              font { family: Style.font.menuFamily; pixelSize: Math.round(Style.font.caption * 1.3); bold: true }
              padding: Style.spacing.sm
              MouseArea { anchors.fill: parent; onClicked: root.answer("deny") }
            }
            Text {
              text: root.keyArmed ? "  Allow (A)  " : "  Allow (→ then A)  "
              color: Color.urgent
              font { family: Style.font.menuFamily; pixelSize: Math.round(Style.font.caption * 1.3) }
              padding: Style.spacing.sm
              MouseArea { anchors.fill: parent; onClicked: if (root.pointerArmed || root.keyArmed) root.answer("confirm") }
            }
          }
        }
      }
    }
  }
}
