import QtQuick
import Quickshell
import Quickshell.Wayland
import Quickshell.Hyprland
import qs.Commons
import qs.Ui

// The human's half of the control gate: an agent asking for the desktop puts a
// request in the state file, and this is where it is answered.
//
// Deny is the default in every direction — Escape, Return and the window
// closing under a lapsed request all deny. Allow needs its own key (A) or a
// click, so no stray Enter from whatever had focus can hand an agent the
// keyboard. Nothing here decides anything: both buttons run the CLI, and the
// state file is what actually changes.
Item {
  id: root
  property var request: null        // {id, by, since, expires} from state.json, or null
  property var command: null        // the Widget's Command; one process at a time is plenty
  readonly property bool opened: request !== null
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

  onOpenedChanged: if (opened) Qt.callLater(function () { keys.forceActiveFocus() })

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
          event.accepted = true
          if (event.key === Qt.Key_A) root.answer("confirm")
          else if (event.key === Qt.Key_Escape || event.key === Qt.Key_Return || event.key === Qt.Key_Enter
                   || event.key === Qt.Key_D) root.answer("deny")
          else event.accepted = false
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
              text: "  Allow (A)  "
              color: Color.urgent
              font { family: Style.font.menuFamily; pixelSize: Math.round(Style.font.caption * 1.3) }
              padding: Style.spacing.sm
              MouseArea { anchors.fill: parent; onClicked: root.answer("confirm") }
            }
          }
        }
      }
    }
  }
}
