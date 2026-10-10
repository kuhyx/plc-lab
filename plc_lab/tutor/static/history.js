"use strict";
// Session history in the side panel: links to "#<session_id>", plus the
// done toggles for each card. Refreshed on load, when the live session
// changes (start, Repeat, Stop here), after Next card and after a toggle.
// No editing or deleting of transcripts: Archive only hides a session here
// (sessions with no reply of yours are archived automatically).
let showArchived = false;  // survives the refreshes, or the list would collapse

// One card of a session: its front, ✓ if done in progress now (cards[].done),
// and a Mark done / Mark not done toggle (POST /api/card_done).
function cardRow(c) {
  const row = el("div", "card-row");
  row.append(el("span", "", `${c.front}${c.done ? " ✓" : ""}`));
  const btn = el("button", "small", c.done ? "Mark not done" : "Mark done");
  btn.type = "button";
  btn.title = c.done ? "Mark this card as not done" : "Mark this card as done";
  btn.addEventListener("click", () => setCardDone(c.id, !c.done));
  row.append(btn);
  return row;
}

// The reply is /api/state, so api() renders it (a done live card shows the
// Next card / Stop here box); then everything listing done states refreshes.
async function setCardDone(cardId, done) {
  if (!(await api("/api/card_done", { card_id: cardId, done }))) return;
  refreshHistory();
  loadCards().catch((err) => showError(err));
  if (view !== "live") openHash();  // the past view re-reads its cards
}

function historyItem(s) {
  const li = el("li", "history-item");
  const link = el("a", "", s.started);
  link.href = `#${s.session_id}`;
  // After Stop here the hash already points at that session: no hashchange
  // would fire, so open it directly.
  link.addEventListener("click", (e) => {
    if (link.hash !== location.hash) return;
    e.preventDefault();
    openHash();
  });
  li.append(link);
  if (s.live) li.append(" ", el("span", "pill pill-ok", "live"));
  s.cards.forEach((c) => li.append(cardRow(c)));
  // "done" here means a card was finished in THAT session (done_here).
  const done = s.cards.some((c) => c.done_here) ? " · done ✓" : "";
  li.append(el("div", "muted", `active ${s.active_minutes} / credited ${s.credited_minutes} min${done}`));
  if (s.auto_archived) li.append(el("div", "muted", "archived: no reply"));
  else if (!s.live) li.append(archiveButton(s.session_id, s.archived));
  return li;
}

// Archive / Unarchive; never for the live session or an auto-archived one.
function archiveButton(sid, archived) {
  const btn = el("button", "small", archived ? "Unarchive" : "Archive");
  btn.type = "button";
  btn.title = archived ? "Show this session in History again" : "Hide this session from History (nothing is deleted)";
  btn.addEventListener("click", () => setArchived(sid, !archived));
  return btn;
}

// The reply is the new /api/sessions list (not /api/state): call(), not api().
async function setArchived(sid, archived) {
  try {
    renderHistory(await call("/api/archive", { session_id: sid, archived }));
    if (view === sid) openHash();  // the banner shows the new archived state
  } catch (err) {
    showError(err);
  }
}

function renderHistory(sessions) {
  const shown = sessions.filter((s) => !s.archived);
  const hidden = sessions.filter((s) => s.archived);
  $("history").replaceChildren(...shown.map(historyItem));
  if (!shown.length) $("history").append(el("li", "muted", sessions.length ? "No unarchived sessions" : "No sessions yet"));
  $("history-archived").replaceChildren(...hidden.map(historyItem));
  $("history-archived").hidden = !showArchived || !hidden.length;
  $("archived-toggle").hidden = !hidden.length;
  $("archived-toggle").textContent = `${showArchived ? "Hide" : "Show"} archived (${hidden.length})`;
}

async function refreshHistory() {
  try {
    renderHistory(await call("/api/sessions"));
  } catch (err) {
    $("history").replaceChildren(el("li", "muted", `History unavailable: ${err.message || err}`));
  }
}

$("archived-toggle").addEventListener("click", () => {
  showArchived = !showArchived;
  refreshHistory();
});

// The start picker; re-fetched after a toggle so its "[done]" labels update.
async function loadCards() {
  const cards = await call("/api/cards");
  const keep = $("cards").value;
  $("cards").replaceChildren(
    el("option", "", "Next unfinished card"),
    ...cards.map((c) => { const o = el("option", "", `${c.done ? "[done] " : ""}${c.topic}: ${c.front}`); o.value = c.id; return o; }),
  );
  $("cards").firstChild.value = "";
  $("cards").value = keep;
}
