import QtQuick
import Quickshell.Io

// Runs the packaged CLI; @ai-mirror@ is replaced with its store path at build time.
Item {
  id: root
  property bool busy: process.running
  property string error: ""
  function run(args) {
    if (busy) return
    error = ""
    process.command = ["@ai-mirror@"].concat(args)
    process.running = true
  }
  Process {
    id: process
    stdout: StdioCollector {
      onStreamFinished: {
        try {
          var result = JSON.parse(text)
          if (result.error) root.error = result.error.message || "Action failed"
        } catch (e) { root.error = "Could not read ai-mirror output" }
      }
    }
    onExited: function(code, status) {
      if (code !== 0 && !root.error) root.error = "ai-mirror command failed (" + code + ")"
    }
  }
}
