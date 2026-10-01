import QtQuick
import Quickshell
import Quickshell.Io

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
      try { root.state = JSON.parse(String(text() || "")) } catch (e) { root.state = null }
    }
    onLoadFailed: root.state = null
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
