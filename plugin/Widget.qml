import QtQuick
import Quickshell
import Quickshell.Io
import qs.Ui
import qs.Commons

// Red "AGENT CONTROL" while an agent may drive the desktop; click to stop.
BarWidget {
  id: root
  moduleName: "olafkfreund.ai-mirror"
  implicitWidth: button.implicitWidth
  implicitHeight: barSize
  property var state: null
  readonly property bool on: state !== null && state.owner === "agent"

  Command { id: command }

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

  WidgetButton {
    id: button
    bar: root.bar
    fixedHeight: root.barSize
    active: root.on
    text: root.on ? "󰚩 AGENT CONTROL" : "󰚩"
    dimmed: !root.on
    interactive: !command.busy
    tooltipText: command.error || (root.on
      ? "An AI agent controls keyboard and mouse (since " + root.state.since + "). Click to stop."
      : "ai-mirror: agent control is off. Click to allow agent control.")
    onPressed: command.run(["control", root.on ? "off" : "agent"])
  }
}
