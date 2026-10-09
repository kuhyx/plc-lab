"use strict";
// Developer feedback goes to /api/feedback through call(), never api(): no
// busy flag, no render, nothing the tutor or the engagement clock can see.
// The panel lives outside #log and #composer, so polls and the answer draft
// are untouched.
function openReport(index) {
  reportIndex = index;
  const msg = index === null ? null : lastState?.messages?.[index];
  const preview = msg ? msg.text.replace(/\s+/g, " ").slice(0, 90) : "";
  $("report-scope").textContent = msg
    ? `About tutor message #${index}: "${preview}${msg.text.length > 90 ? "..." : ""}"`
    : "About the UI or the experience as a whole.";
  if (!$("report-text").value) $("report-category").value = msg ? "response" : "experience";
  $("report-form").hidden = false;
  $("report-done").hidden = true;
  $("report-error").hidden = true;
  $("report").hidden = false;
  document.querySelectorAll(".msg.flagged").forEach((n) => n.classList.remove("flagged"));
  if (msg) $(`m${index}`)?.classList.add("flagged");
  $("report").scrollIntoView({ block: "nearest" });
  $("report-text").focus();
}

function closeReport() {
  $("report").hidden = true;
  reportIndex = null;
  document.querySelectorAll(".msg.flagged").forEach((n) => n.classList.remove("flagged"));
}

async function submitReport() {
  const text = $("report-text").value.trim();
  if (reportBusy) return;
  if (!text) {
    $("report-error").hidden = false;
    $("report-error").textContent = "Describe what is wrong first.";
    return;
  }
  reportBusy = true;
  $("report-submit").textContent = "Saving...";
  try {
    const res = await call("/api/feedback", {
      category: $("report-category").value,
      text,
      session_id: sessionId,
      message_index: reportIndex,
      page_url: location.href,
      user_agent: navigator.userAgent,
    });
    // Saved: only now is the typed report cleared; a failure keeps it.
    $("report-text").value = "";
    $("report-saved").textContent = `Saved as feedback #${res.id}`;
    $("report-md").textContent = res.markdown;
    $("report-copy").textContent = "Copy report";
    $("report-form").hidden = true;
    $("report-done").hidden = false;
  } catch (err) {
    $("report-error").hidden = false;
    // A 404 means the page is newer than the running server process.
    const stale = /^HTTP 404/.test(err.message || "") ? " - the running server predates this feature; restart it" : "";
    $("report-error").textContent = `Not saved: ${err.message || err}${stale}. Your report is kept.`;
    if (err.report) console.error(err.report);
  } finally {
    reportBusy = false;
    $("report-submit").textContent = "Save report";
  }
}

$("report-open").addEventListener("click", () => openReport(null));
$("report-cancel").addEventListener("click", closeReport);
$("report-close").addEventListener("click", closeReport);
$("report-submit").addEventListener("click", submitReport);
$("report-text").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); submitReport(); }
  if (e.key === "Escape") closeReport();
});
$("report-copy").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($("report-md").textContent);
    $("report-copy").textContent = "Copied";
  } catch {
    $("report-md").closest("details").open = true;
    getSelection().selectAllChildren($("report-md"));
    $("report-copy").textContent = "Selected - press Ctrl+C";
  }
});
