"use strict";
// Session URLs and the read-only view. The hash is "#<session_id>",
// "#<session_id>/m14" or "#m14" (message 14 of the live session, used by the
// headless screenshots). Session ids start with a digit, which is not a valid
// CSS selector: anchors are looked up with getElementById, never querySelector.
const SESSION_RE = /^\d{8}-\d{6}-[0-9a-f]{4}$/;
const ANCHOR_RE = /^m\d+$/;

function parseHash() {
  const [first = "", second = ""] = location.hash.slice(1).split("/");
  if (ANCHOR_RE.test(first)) return { sid: "", anchor: first };
  return { sid: first, anchor: ANCHOR_RE.test(second) ? second : "" };
}
const hashAnchor = () => parseHash().anchor;

// "live" or the id of the past session on screen. Decided from the hash
// before the first render, so the live sync can't overwrite a pasted URL.
let view = parseHash().sid || "live";
let pastCard = null;  // first card of the past session, for Repeat
let pastArchived = false;  // whether the past session on screen is archived

function clockStatus(s) {
  const active = Math.floor(((s.clock || {}).active_seconds || 0) / 60);
  return `Active ${active} min · credited ${s.session_credited_minutes || 0}`;
}

// Keep the hash on the live session (no history entry, no scroll jump). A
// "#m14" anchor is kept as "#<id>/m14". With no live session (after Stop
// here) the hash keeps pointing at the stopped one, which reopens read-only.
function syncHash(live) {
  if (!live) return;
  const { sid, anchor } = parseHash();
  const want = `#${live}${anchor && (!sid || sid === live) ? `/${anchor}` : ""}`;
  if (location.hash !== want) window.history.replaceState(null, "", want);
}

// render() asks this before touching the chat: false keeps a past view.
function liveView(s) {
  if (view !== "live" && view === s.session_id) view = "live";
  if (view !== "live") return false;
  $("past").hidden = true;
  $("session-id").textContent = s.session_id;
  syncHash(s.session_id);
  return true;
}

function showLive() {
  view = "live";
  lastCount = 0;
  $("past").hidden = true;
  if (lastState) render(lastState);
}

function showPast(data) {
  if (reportIndex !== null) closeReport();
  lastCount = 0;
  renderLog(data.messages, true);
  ["empty", "switch", "mark-done", "composer", "card-end"].forEach((id) => { $(id).hidden = true; });
  $("past").hidden = false;
  $("past-title").textContent = `Past session ${data.session_id} - read-only`;
  pastCard = data.cards.length ? data.cards[0].id : null;
  $("repeat").hidden = !pastCard;
  $("session-id").textContent = data.session_id;
  // Archived tag; Archive / Unarchive by hand (auto-archived: no reply, no button).
  pastArchived = Boolean(data.archived);
  $("past-archived").hidden = !pastArchived;
  $("past-archived").textContent = data.auto_archived ? "archived: no reply" : "archived";
  $("past-archive").hidden = Boolean(data.auto_archived || data.live);
  $("past-archive").textContent = pastArchived ? "Unarchive" : "Archive";
  // Each card with its done state now and a Mark done / Mark not done toggle.
  if (data.cards.length) $("card").replaceChildren(...data.cards.map(cardRow));
  else $("card").textContent = "-";
  const mins = Math.floor((data.active_seconds || 0) / 60);
  $("active").textContent = `Active ${mins} min · credited ${data.credited_minutes}`;
}

// Startup and every hashchange (a pasted URL, a history link, Back).
async function openHash() {
  const { sid } = parseHash();
  if (!sid || sid === lastState?.session_id) { showLive(); return; }
  view = sid;
  $("busy").hidden = false; $("error").hidden = true;
  try {
    // call(), not api(): this payload is not /api/state and must not hit render().
    const data = await call(`/api/session/${encodeURIComponent(sid)}`);
    if (view !== sid) return;  // moved on (or the poll found it is the live one)
    if (data.live) {
      render(await call("/api/state"));
      showLive();
    } else showPast(data);
  } catch (err) {
    showLive();
    showError(err);
  } finally {
    $("busy").hidden = true;
  }
}

window.addEventListener("hashchange", openHash);

$("back-live").addEventListener("click", () => {
  // No live session: drop the hash, or a reload would reopen the past one.
  if (!lastState?.session_id) window.history.replaceState(null, "", location.pathname + location.search);
  showLive();
});

$("repeat").addEventListener("click", async () => {
  // Same as Start: a fresh session on that card replaces any live one.
  if (await api("/api/start", { card_id: pastCard })) {
    picking = false;
    showLive();
  }
});

$("past-archive").addEventListener("click", () => {
  if (view !== "live") setArchived(view, !pastArchived);
});

$("next-card").addEventListener("click", async () => {
  if (await api("/api/next", {})) refreshHistory();
});
$("stop-here").addEventListener("click", () => api("/api/stop", {}));
// The live card by hand; the reply's card_done brings up Next card / Stop here.
$("mark-done").addEventListener("click", () => {
  if (lastState?.card) setCardDone(lastState.card.id, true);
});
