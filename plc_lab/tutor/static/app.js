"use strict";
// All dynamic text goes in through textContent / createTextNode; no innerHTML.
const $ = (id) => document.getElementById(id);
const seen = new Set();
let lastCount = 0;
let simulate = new URLSearchParams(location.search).get("advance");
// The unsent answer is kept per session in localStorage, so neither a reload
// nor a server restart mid-session can lose what was being typed.
let sessionId = "";
let picking = false;
let lastState = null;
// Developer feedback ("Report a problem"): null = whole experience, else the
// index of the tutor message being reported.
let reportIndex = null;
let reportBusy = false;
const draftKey = () => `tutor-draft:${sessionId}`;

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

// Tiny markdown: paragraphs, "- " / "1. " lists, **bold**, *em*, `code`.
function inline(parent, text) {
  const re = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g;
  text.split(re).forEach((part) => {
    if (part.startsWith("**") && part.endsWith("**")) parent.append(el("strong", "", part.slice(2, -2)));
    else if (part.startsWith("`") && part.endsWith("`")) parent.append(el("code", "", part.slice(1, -1)));
    else if (part.length > 2 && part.startsWith("*") && part.endsWith("*")) parent.append(el("em", "", part.slice(1, -1)));
    else parent.append(document.createTextNode(part));
  });
}

function markdown(text) {
  const box = el("div");
  text.split(/\n{2,}/).forEach((block) => {
    const lines = block.split("\n");
    if (lines.every((l) => /^\s*([-*]|\d+\.)\s+/.test(l))) {
      const list = el(/^\s*\d+\./.test(lines[0]) ? "ol" : "ul");
      lines.forEach((l) => { const li = el("li"); inline(li, l.replace(/^\s*([-*]|\d+\.)\s+/, "")); list.append(li); });
      box.append(list);
    } else {
      const p = el("p");
      lines.forEach((l, i) => { if (i) p.append(el("br")); inline(p, l); });
      box.append(p);
    }
  });
  return box;
}

function figure(img) {
  const fig = el("figure");
  const pic = el("img");
  pic.src = `/media/${img.file}`;
  pic.alt = img.title;
  fig.append(pic);
  const cap = el("figcaption", "", `${img.title} - ${img.author}, `);
  const lic = el("a", "", img.licence);
  lic.href = img.licence_url || img.page_url; lic.target = "_blank"; lic.rel = "noreferrer";
  const src = el("a", "", "Wikimedia Commons");
  src.href = img.page_url; src.target = "_blank"; src.rel = "noreferrer";
  cap.append(lic, document.createTextNode(" - "), src);
  fig.append(cap);
  return fig;
}

function renderMessage(m, i) {
  const box = el("article", `msg ${m.role}`);
  if (m.role === "tutor") {
    const head = el("div", "msg-head");
    head.append(el("div", "tag", m.low_effort ? "Tutor (last reply was low effort)" : "Tutor"));
    const flag = el("button", "flag", "⚑ Report");
    flag.type = "button";
    flag.title = "Report a problem with this message (for the developer, not the tutor)";
    flag.addEventListener("click", () => openReport(i));
    head.append(flag);
    box.append(head);
  }
  box.append(markdown(m.text));
  (m.images || []).forEach((i) => box.append(figure(i)));
  if ((m.diagrams || []).length) {
    const row = el("div", "diagrams");
    m.diagrams.forEach((d) => { const i = el("img"); i.src = `/media/${d}`; i.alt = m.diagram_title || "circuit diagram"; row.append(i); });
    box.append(row, el("figcaption", "", `${m.diagram_title || "Circuit"} - drawn by code (schemdraw)`));
  }
  if (m.check_result) {
    const c = el("div", `check ${m.check_result.passed ? "pass" : "fail"}`, `Check ${m.check_result.passed ? "passed" : "not yet"}: ${m.check_result.feedback || ""}`);
    box.append(c);
  }
  if (m.check) box.append(el("div", "check", `Comprehension check: ${m.check.question}`));
  return box;
}

function render(s) {
  lastState = s;
  const log = $("log");
  const keep = log.scrollTop;
  log.replaceChildren(...s.messages.map((m, i) => {
    const n = renderMessage(m, i);
    n.id = `m${i}`; n.style.marginBottom = "16px";
    n.classList.toggle("flagged", reportIndex === i);
    return n;
  }));
  const started = Boolean(s.session_id);
  if (s.session_id !== sessionId) {
    sessionId = s.session_id;
    if (started && !$("text").value) $("text").value = localStorage.getItem(draftKey()) || "";
  }
  $("empty").hidden = started && !picking;
  $("switch").hidden = !started || picking;
  $("composer").hidden = !started;
  $("card").textContent = s.card ? s.card.front : "-";
  $("mastered").replaceChildren(...s.mastered.map((c) => el("li", "", c)));
  $("credited").textContent = `Credited ${s.credited_minutes}/${s.target_minutes} min`;
  [...$("blocks").children].forEach((b, i) => b.classList.toggle("on", (i + 1) * 15 <= s.credited_minutes));
  const c = s.clock || {};
  if (started) {
    const mins = ((c.active_seconds || 0) / 60).toFixed(1);
    const pend = c.blocks_pending_check ? " - 15 min reached, waiting for a passed check" : "";
    $("active").textContent = `Active ${mins} min${pend}`;
  }
  $("paused").hidden = !c.paused;
  if (c.paused) $("paused").textContent = `Clock paused: ${c.paused_reason}`;
  s.receipts.forEach((r) => {
    if (seen.has(r.entry_id)) return;
    seen.add(r.entry_id);
    const toast = $("toast");
    toast.hidden = false;
    toast.className = r.recorded ? "pill pill-ok" : "pill pill-warn";
    toast.textContent = r.recorded ? "🎮 +15 min recorded" : `Credit NOT recorded: ${r.error}`;
  });
  log.scrollTop = keep;
  const anchor = location.hash && document.querySelector(location.hash);
  if (anchor && lastCount === 0) anchor.scrollIntoView();
  else if (s.messages.length !== lastCount) log.scrollTop = log.scrollHeight;
  lastCount = s.messages.length;
}
async function api(path, body) {
  $("busy").hidden = false; $("error").hidden = true;
  document.querySelectorAll("button").forEach((b) => { b.disabled = true; });
  try {
    render(await call(path, body, { retry: true }));
    return true;
  } catch (err) {
    showError(err);
    return false;
  } finally {
    $("busy").hidden = true;
    document.querySelectorAll("button").forEach((b) => { b.disabled = false; });
  }
}

$("start").addEventListener("click", async () => {
  if (await api("/api/start", { card_id: $("cards").value || null })) picking = false;
});
$("switch").addEventListener("click", () => { picking = true; $("empty").hidden = false; $("switch").hidden = true; });
$("text").addEventListener("input", () => {
  if (sessionId) localStorage.setItem(draftKey(), $("text").value);
});
$("composer").addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = $("text").value.trim();
  if (!text || $("text").readOnly) return;
  // The text stays in the box until the server has it; a failed send keeps it.
  $("text").readOnly = true;
  const sentFrom = sessionId;
  const ok = await api("/api/message", { text, advance_s: simulate ? Number(simulate) : 0, msg_id: crypto.randomUUID() });
  $("text").readOnly = false;
  if (ok) {
    $("text").value = "";
    localStorage.removeItem(`tutor-draft:${sentFrom}`);
  }
});
// Enter is a newline (answers are often code); Ctrl/Cmd+Enter sends, like the
// report box. Tab indents the touched lines by four spaces, Shift+Tab dedents;
// right after Esc, Tab leaves the box so the keyboard is never trapped.
const INDENT = "    ";
let tabLeaves = false;
function indentLines(box, dedent) {
  const { value, selectionStart: start, selectionEnd: end } = box;
  if (!dedent && start === end) {
    box.setRangeText(INDENT, start, end, "end");
    return;
  }
  const from = value.lastIndexOf("\n", start - 1) + 1;
  const lines = value.slice(from, end).split("\n");
  const changed = lines.map((l) => (dedent ? l.replace(/^ {1,4}/, "") : INDENT + l));
  const firstShift = changed[0].length - lines[0].length;
  box.setRangeText(changed.join("\n"), from, end, "preserve");
  const total = changed.join("\n").length - lines.join("\n").length;
  box.setSelectionRange(Math.max(from, start + firstShift), end + total);
}
$("text").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    $("composer").requestSubmit();
    return;
  }
  if (e.key === "Escape") { tabLeaves = true; return; }
  if (e.key !== "Tab") { tabLeaves = false; return; }
  if (tabLeaves || e.ctrlKey || e.altKey || e.metaKey) { tabLeaves = false; return; }
  e.preventDefault();
  indentLines(e.target, e.shiftKey);
  e.target.dispatchEvent(new Event("input"));  // the draft autosave
});
