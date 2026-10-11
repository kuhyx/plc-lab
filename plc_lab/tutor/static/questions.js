"use strict";
// Answer boxes for the tutor's questions. Each question of the LATEST tutor
// message (its own `questions`, then the comprehension check) gets a quoted
// box with an answer field, plus one "Your own comment" field; together they
// replace the plain answer box in #composer. Older messages, and past
// sessions, show their questions read-only in #log.
// The boxes live in #composer, never in #log: #log is rebuilt on every poll,
// which would wipe what is being typed. They are rebuilt only when the latest
// tutor message changes. Every global here starts with q: all static scripts
// share one global scope (see index.html).
// Loaded after app.js (el, $, composerKeys), before net.js (startup).

// The boxes on screen: { key: "<session>:<message index>", index, asked }.
let qLive = null;
let qSending = "";  // the key whose answers are in flight
const qDraftKey = (key) => `tutor-qdraft:${key}`;

// What a page message asks, in box order: its own questions, then the check
// (numbered on, so the reply's Q1, Q2... match the boxes). Messages logged
// before `questions` existed have none of their own.
function qAsked(m) {
  const asked = (m.questions || []).map((text) => ({ text, check: false }));
  if (m.check) asked.push({ text: m.check.question, check: true });
  return asked.map((a, n) => ({ ...a, label: `Q${n + 1}` }));
}

function qQuote(a) {
  const quote = el("blockquote", "question");
  const label = a.check ? `${a.label} - Comprehension check` : a.label;
  quote.append(el("span", "question-label", label), el("span", "", a.text));
  return quote;
}

// Read-only, inside a message in #log (the check keeps its old look).
function qAppendAsked(box, m) {
  qAsked(m).forEach((a) => {
    box.append(a.check ? el("div", "check", `Comprehension check: ${a.text}`) : qQuote(a));
  });
}

// Whether message i shows its questions as live boxes (so #log leaves them out).
function qIsLive(i) {
  return qLive !== null && qLive.index === i;
}

const qFields = () => [...$("qboxes").querySelectorAll("textarea")];

// Grow a box with its text; CSS caps it (max-height) and it scrolls.
function qFit(box) {
  if (box.offsetParent === null) return;  // hidden: nothing to measure
  box.style.height = "auto";
  box.style.height = `${box.scrollHeight + box.offsetHeight - box.clientHeight}px`;
}

function qField(id, label, value) {
  const wrap = el("div", "qfield");
  const name = el("label", "question-label", label);
  const box = el("textarea");
  box.id = id; box.rows = 3; box.value = value || "";
  name.htmlFor = id;
  box.addEventListener("keydown", composerKeys);  // Ctrl+Enter sends, Tab indents
  box.addEventListener("input", () => { qSave(); qFit(box); qSyncSend(); });
  wrap.append(name, box);
  return wrap;
}

function qSave() {
  if (!qLive) return;
  const values = qFields().map((b) => b.value);
  localStorage.setItem(qDraftKey(qLive.key), JSON.stringify(values));
}

function qBuild(key, index, asked) {
  const boxes = $("qboxes");
  qLive = key ? { key, index, asked } : null;
  boxes.hidden = !key; $("text").hidden = Boolean(key);
  if (!key) { boxes.replaceChildren(); return; }
  let saved = [];
  try { saved = JSON.parse(localStorage.getItem(qDraftKey(key)) || "[]"); } catch { /* a corrupt draft starts empty */ }
  const fields = asked.map((a, n) => {
    const wrap = qField(`qa${n}`, "Your answer", saved[n]);
    wrap.prepend(qQuote(a));
    return wrap;
  });
  fields.push(qField("qcomment", "Your own comment", saved[asked.length]));
  boxes.replaceChildren(...fields);
  requestAnimationFrame(() => qFields().forEach(qFit));  // after the composer is unhidden
}

// Called by render(): boxes for the latest message when it is the tutor's
// and the composer is showing; otherwise the plain answer box.
function qSync(s, show) {
  const last = s.messages.length - 1;
  const m = s.messages[last];
  const asked = show && m && m.role === "tutor" ? qAsked(m) : [];
  const key = asked.length ? `${s.session_id}:${last}` : "";
  if (key !== (qLive ? qLive.key : "")) qBuild(key, last, asked);
  qSyncSend();
}

// Send needs at least one non-empty box; api() re-enables every button, so it
// calls this again afterwards. The plain answer box keeps its old behaviour:
// Send is only off while a call is in flight.
function qSyncSend() {
  const send = $("composer").querySelector("button[type=submit]");
  const empty = qLive !== null && qFields().every((b) => !b.value.trim());
  send.disabled = !$("busy").hidden || empty;
}

// The one message the boxes send: "Q1: ..." / "A: ..." per question, then
// the comment. Empty when nothing was typed. Only trailing space is cut, so
// an indented first line of code keeps its indent.
function qCompose() {
  const values = qFields().map((b) => (b.value.trim() ? b.value.trimEnd() : ""));
  if (values.every((v) => !v)) return "";
  const blocks = qLive.asked.map((a, n) => `${a.label}: ${a.text}\nA: ${values[n] || "(skipped)"}`);
  const comment = values[qLive.asked.length];
  if (comment) blocks.push(`Comment: ${comment}`);
  qSending = qLive.key;
  return blocks.join("\n\n");
}

// While a send is in flight nothing in the composer can change.
function qReadOnly(on) {
  [$("text"), ...qFields()].forEach((b) => { b.readOnly = on; });
}

// The server has the answers: drop their draft.
function qSent() {
  localStorage.removeItem(qDraftKey(qSending));
  qSending = "";
}
