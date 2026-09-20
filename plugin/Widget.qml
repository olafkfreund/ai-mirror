import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui
import qs.Commons

// Warns, in the bar, while an agent may drive the desktop; click to stop.
//
// Icon and colour only, no caps banner. That follows omarchy's own
// ScreenRecording indicator, which signals a live recording the same way, and
// it gives back the width a 13-character label was taking on a bar that
// already carries twenty widgets. Nothing is lost: the tooltip still says who
// is driving and since when, and the mark is unmistakable at a glance.
BarWidget {
  id: root
  moduleName: "olafkfreund.ai-mirror"
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight
  property var state: null
  readonly property bool on: state !== null && state.owner === "agent"
  readonly property bool pending: state !== null && state.owner === "pending"
  // Looking is not driving, so it gets a steady neutral mark rather than the red
  // pulse. Stale after ten seconds: the file records when an agent last looked.
  property double lastLook: 0
  property double now: Date.now() / 1000
  readonly property bool watching: !root.on && root.now - root.lastLook < 10

  AgentCommand { id: command }

  AgentConfirmDialog {
    request: root.pending ? root.state.request : null
    command: command
  }

  FileView {
    id: looks
    path: Quickshell.env("XDG_RUNTIME_DIR") + "/ai-mirror/watching"
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: root.lastLook = parseFloat(String(text() || "0")) || 0
    onLoadFailed: root.lastLook = 0
  }
  Timer {
    interval: 1000
    repeat: true
    running: root.lastLook > 0
    onTriggered: root.now = Date.now() / 1000
  }

  FileView {
    id: file
    path: Quickshell.env("XDG_RUNTIME_DIR") + "/ai-mirror/state.json"
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: {
      try { root.state = JSON.parse(String(text() || "")) } catch (e) { root.state = null }
    }
    onLoadFailed: root.state = null
  }
  // ponytail: the state file only exists after first use; retry until it does, then inotify takes over
  Timer {
    interval: 3000
    repeat: true
    running: root.state === null
    onTriggered: file.reload()
  }

  // Live control is the one state worth interrupting someone for, so it is the
  // only one that moves. A still mark in a busy bar is easy to walk past.
  SequentialAnimation on opacity {
    running: root.on
    loops: Animation.Infinite
    alwaysRunToEnd: true
    NumberAnimation { from: 1.0; to: 0.5; duration: 700; easing.type: Easing.InOutSine }
    NumberAnimation { from: 0.5; to: 1.0; duration: 700; easing.type: Easing.InOutSine }
  }

  BarIconButton {
    id: button
    bar: root.bar
    fixedHeight: root.barSize

    // A drawn mark instead of `text`: the robot glyph this used to set is also
    // skal.bar's and sits beside the shell's own agents robot. See AgentMark.
    iconComponent: Component {
      Item {
        AgentMark {
          anchors.centerIn: parent
          iconSize: Style.bar.iconCanvas * 0.92
          color: root.on
                 ? (root.bar ? root.bar.urgent : Color.urgent)
                 : (root.bar ? root.bar.barForeground : Color.foreground)
          active: root.on
          opacity: root.on ? 1.0 : (root.watching || root.pending ? 0.8 : 0.45)
          Behavior on opacity { NumberAnimation { duration: 160 } }
        }
      }
    }

    interactive: !command.busy
    tooltipText: command.error || (root.on
      ? "An AI agent controls keyboard and mouse (since " + root.state.since + "). Click to stop."
      : root.pending
        ? "An agent is asking to use this desktop. Answer the dialog."
        : root.watching
          ? "An agent is reading the screen. It cannot type or click."
          : "ai-mirror: agent control is off. Click to ask for agent control.")
    onPressed: command.run(["control", root.on ? "off" : "agent"])
  }
}
