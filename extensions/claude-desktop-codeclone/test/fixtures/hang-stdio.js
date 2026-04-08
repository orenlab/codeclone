"use strict";

// Intentionally hung stdio child used to exercise the launcher's shutdown
// escalation: it ignores SIGTERM and keeps the event loop alive so only a
// SIGKILL from the wrapper can bring it down.
process.on("SIGTERM", () => {});
process.stdin.resume();
setInterval(() => {}, 1 << 30);
