import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons as Commons

// Owns the one confirm dialog. The shell creates an overlay once, but a bar
// widget once per bar, so a dialog in the widget opened three on three
// monitors (#58).
Item {
  id: root
  property var shell: null
  property var manifest: null
  property string omarchyPath: ""
  property var state: null
  readonly property bool pending: state !== null && state.owner === "pending"
  // Display only, like the bar: state.json is the gate, these just follow it (#78).
  readonly property bool agent: state !== null && state.owner === "agent"
  property string wantedMode: ""
  property string appliedMode: ""
  property string runningMode: ""
  function readState(next) {
    state = next
    wantedMode = next && next.owner === "agent" ? "agent" : "desktop"
  }
  function applyCursor() {
    if (!wantedMode || wantedMode === appliedMode || setcursor.running || retryCursor.running) return
    runningMode = wantedMode
    setcursor.command = ["@ai-mirror-cursor@", runningMode]
    setcursor.running = true
  }
  onWantedModeChanged: applyCursor()

  AgentCommand { id: command }

  AgentConfirmDialog {
    request: root.pending ? root.state.request : null
    command: command
  }

  FileView {
    id: file
    path: Quickshell.env("XDG_RUNTIME_DIR") + "/ai-mirror/state.json"
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: {
      try { root.readState(JSON.parse(String(text() || ""))) } catch (e) { root.readState(null) }
    }
    onLoadFailed: root.readState(null)
  }

  // Re-checks on exit: a change that arrived while hyprctl ran is applied now.
  Process {
    id: setcursor
    onExited: function(code) {
      if (code === 0) {
        root.appliedMode = root.runningMode
        root.applyCursor()
      } else {
        root.appliedMode = ""
        retryCursor.restart()
      }
    }
  }
  Timer { id: retryCursor; interval: 3000; onTriggered: root.applyCursor() }

  // Always mapped, so a grant records it as furniture (baseline_layers) and
  // _refuse_new_surfaces never calls it new; Top, the bar's level, so it is
  // no rival _require_layer did not already have (#78). Only the border follows the state.
  Variants {
    model: Quickshell.screens
    PanelWindow {
      required property var modelData
      screen: modelData
      anchors { top: true; bottom: true; left: true; right: true }
      color: "transparent"
      exclusionMode: ExclusionMode.Ignore
      mask: Region {}
      WlrLayershell.namespace: "omarchy-ai-mirror-frame"
      WlrLayershell.layer: WlrLayer.Top
      WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
      Rectangle {
        anchors.fill: parent
        color: "transparent"
        border.width: root.agent ? 4 : 0
        border.color: Commons.Color.urgent
      }
    }
  }

  // The state file only exists after first use; retry until it does, then
  // inotify takes over. Without this a shell started before the first request
  // never sees one, and every request lapses unanswered (#58 review).
  Timer {
    interval: 3000
    repeat: true
    running: root.state === null
    onTriggered: file.reload()
  }
}
