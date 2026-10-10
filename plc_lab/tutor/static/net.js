"use strict";
// Server calls: retry through a restart, paste-back errors, the state poll
// and startup. Loaded last (after app.js, session.js, history.js,
// report.js and wheel.js; see index.html).

// A failed call carries everything needed to paste it back to Claude: the
// request, the HTTP status, the server's traceback, or the fact that nothing
// answered at all (a dead server only ever says "Failed to fetch").
class ApiError extends Error {
  constructor(method, path, body, res, data, cause) {
    super(cause ? "Tutor server is not reachable - is it running?" : `HTTP ${res.status}: ${data?.error || res.statusText}`);
    const lines = [
      `Automation tutor error (${new Date().toISOString()})`,
      `Request: ${method} ${path}${body ? ` ${JSON.stringify(body)}` : ""}`,
    ];
    if (cause) {
      lines.push(
        `Response: none - ${location.origin} did not answer (${cause.name}: ${cause.message})`,
        "Hint: the server process is gone. Start it: cd ~/src/plc-lab && .venv/bin/python -m plc_lab.tutor",
      );
    } else {
      lines.push(`Response: HTTP ${res.status} ${res.statusText}`);
      if (typeof data === "string") lines.push("Body (not JSON):", data.slice(0, 4000));
      else lines.push(`Error: ${data.type || "?"}: ${data.error}`, ...(data.traceback ? ["Server traceback:", data.traceback.trimEnd()] : []));
    }
    lines.push(`Page: ${location.href}`, `Browser: ${navigator.userAgent}`);
    this.report = lines.join("\n");
  }
}

// While the server restarts for a deploy it refuses connections for a few
// seconds (longer if it is finishing a reply); keep retrying instead of failing.
// Only a refused connection is retried: the request never reached the server.
const RETRY_FOR_MS = 300000;
async function call(path, body, { retry = false } = {}) {
  const method = body ? "POST" : "GET";
  const until = Date.now() + RETRY_FOR_MS;
  let res;
  for (;;) {
    try {
      res = await fetch(path, body ? { method, body: JSON.stringify(body) } : undefined);
      break;
    } catch (err) {
      if (!retry || Date.now() > until) throw new ApiError(method, path, body, null, null, err);
      $("busy").textContent = "Reconnecting to the tutor (it is restarting)...";
      await new Promise((r) => setTimeout(r, 1000));
    }
  }
  $("busy").textContent = "Tutor is thinking...";
  const raw = await res.text();
  let data = null;
  try { data = JSON.parse(raw); } catch { /* not JSON: reported raw below */ }
  if (!res.ok || data === null) throw new ApiError(method, path, body, res, data ?? raw, null);
  return data;
}

let errorFromPoll = false;
function showError(err, fromPoll = false) {
  errorFromPoll = fromPoll;
  $("error").hidden = false;
  $("error-summary").textContent = String(err.message || err);
  $("error-detail").textContent = err.report || String(err.stack || err);
  $("error-copy").textContent = "Copy error";
}

$("error-copy").addEventListener("click", async () => {
  const text = $("error-detail").textContent;
  try {
    await navigator.clipboard.writeText(text);
    $("error-copy").textContent = "Copied";
  } catch {
    getSelection().selectAllChildren($("error-detail"));
    $("error-copy").textContent = "Selected - press Ctrl+C";
  }
});

async function poll() {
  if (!$("busy").hidden) return;
  try {
    render(await call("/api/state"));
    if (errorFromPoll) $("error").hidden = true;
  } catch (err) {
    showError(err, true);
  }
}


(async () => {
  try {
    await loadCards();  // history.js
    render(await call("/api/state"));
  } catch (err) {
    showError(err, true);
  }
  refreshHistory();
  await openHash();  // "#<id>" of a past session opens it read-only
  // The poll also notices a server that died after the page loaded.
  setInterval(poll, 5000);
})();
