"use strict";
// Card editor: the "#edit" overlay ("#edit/<id>" opens one card, "#edit/new" a
// blank one). Save posts to /api/editor/save, which validates the card like
// the build does, checks the excerpt against its source and writes the repo
// deck (routes_editor.py). Ids are never editable and nothing is deleted.
// One global, showCardEditor (called by session.js openHash); everything else
// stays inside this closure, since every page script shares one scope.
const showCardEditor = (() => {
  const LIMITS = { front: [1, 25], back: [1, 30], excerpt: [6, 40] };  // cards.py
  let data = null;  // GET /api/editor
  let editing = null;  // the card on the form; null while adding one
  let needs = [];  // the form's requires ids

  const node = (tag, cls, attrs = {}, text) => Object.assign(el(tag, cls, text), attrs);
  const root = node("div", "overlay", { id: "editor-view", hidden: true });
  root.setAttribute("role", "dialog");
  root.setAttribute("aria-label", "Edit cards");
  const panel = el("div", "overlay-panel editor");
  const close = node("button", "", { type: "button" }, "Close");
  const head = el("div", "overlay-head");
  head.append(el("h2", "", "Edit cards"), close);
  const banner = el("p", "editor-banner");
  // The list: topic filter, text search, New card, Edit this card.
  const listView = el("div");
  const topicFilter = node("select", "", { ariaLabel: "Topic" });
  const search = node("input", "", { type: "search", placeholder: "Search id, front or back", ariaLabel: "Search cards" });
  const newBtn = node("button", "", { type: "button" }, "New card");
  const thisBtn = node("button", "", { type: "button", title: "Edit the target card of the live session" }, "Edit this card");
  const tools = el("div", "editor-tools");
  tools.append(topicFilter, search, newBtn, thisBtn);
  const count = el("p", "muted editor-count");
  const list = el("ul", "editor-list");
  listView.append(tools, count, list);
  // The form. A fieldset, so one flag disables it all while a save runs.
  const form = node("form", "editor-form", { hidden: true });
  const box = el("fieldset");
  const title = el("h3", "editor-title");
  const idBox = node("input", "", { id: "editor-id", autocomplete: "off", spellcheck: false });
  const topicBox = node("select", "", { id: "editor-topic" });
  const inputs = {
    front: node("textarea", "", { id: "editor-front", rows: 2 }),
    back: node("textarea", "", { id: "editor-back", rows: 2 }),
    source: node("input", "", { id: "editor-source", type: "url", placeholder: "https://..." }),
    excerpt: node("textarea", "", { id: "editor-excerpt", rows: 3 }),
  };
  const hints = {};
  const chips = el("div", "editor-chips");
  const needInput = node("input", "", { id: "editor-need", placeholder: "card id, e.g. fund-plc" });
  needInput.setAttribute("list", "editor-ids");
  const idList = node("datalist", "", { id: "editor-ids" });
  const addNeed = node("button", "small", { type: "button" }, "Add");
  const status = node("p", "editor-status", { ariaLive: "polite" });
  const saveBtn = node("button", "primary", { type: "submit" }, "Save");
  const backBtn = node("button", "", { type: "button" }, "Back to list");

  function row(label, input, extra) {
    const wrap = el("div", "editor-field");
    const lab = node("label", "", { htmlFor: input.id }, label);
    wrap.append(lab, input);
    if (extra) lab.append(" ", extra);
    return wrap;
  }
  const needRow = el("div", "editor-need");
  needRow.append(needInput, addNeed, idList);
  const actions = el("div", "editor-actions");
  actions.append(backBtn, saveBtn);
  box.append(title, row("Id", idBox), row("Topic", topicBox));
  Object.entries(inputs).forEach(([key, input]) => {
    hints[key] = el("span", "muted");
    box.append(row(key[0].toUpperCase() + key.slice(1), input, key in LIMITS ? hints[key] : null));
  });
  const needLabel = node("label", "", { htmlFor: needInput.id }, "Requires (cards done before this one opens in the tutor)");
  box.append(needLabel, chips, needRow, status, actions);
  form.append(box);
  panel.append(head, banner, listView, form);
  root.append(panel);
  document.body.append(root);

  const words = (text) => text.split(/\s+/).filter(Boolean).length;
  function countWords(key) {
    const [low, high] = LIMITS[key];
    const n = words(inputs[key].value);
    hints[key].textContent = `${n} words (${low > 1 ? `${low}-` : "max "}${high})`;
    hints[key].className = n < low || n > high ? "error" : "muted";
  }
  const say = (text, cls = "muted") => { status.textContent = text; status.className = `editor-status ${cls}`; };
  const go = (hash) => window.history.replaceState(null, "", hash);
  const topicOf = (stem) => data.topics.find((t) => t.stem === stem);

  // JSON with its Content-Type: the save route refuses anything else.
  async function post(path, body) {
    let res;
    try {
      res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    } catch (err) {
      throw new ApiError("POST", path, body, null, null, err);
    }
    const raw = await res.text();
    let reply = null;
    try { reply = JSON.parse(raw); } catch { /* not JSON: ApiError reports it raw */ }
    if (!res.ok || reply === null) throw new ApiError("POST", path, body, res, reply ?? raw, null);
    return reply;
  }

  async function load() {
    data = await call("/api/editor");
    const keep = topicFilter.value;
    topicFilter.replaceChildren(node("option", "", { value: "" }, "All topics"), ...data.topics.map((t) =>
      node("option", "", { value: t.stem }, `${t.title} (${t.lines}/${data.max_lines} lines)`)));
    topicFilter.value = keep;
    topicBox.replaceChildren(...data.topics.map((t) => node("option", "", { value: t.stem }, t.title)));
    idList.replaceChildren(...data.cards.map((c) => node("option", "", { value: c.id }, c.front)));
    banner.textContent = data.reason;
    banner.hidden = data.writable;
    [newBtn, saveBtn, needRow].forEach((n) => { n.hidden = !data.writable; });
    [idBox, ...Object.values(inputs)].forEach((n) => { n.readOnly = !data.writable; });
    renderList();
  }

  function renderList() {
    const q = search.value.trim().toLowerCase();
    const shown = data.cards.filter((c) => (!topicFilter.value || c.topic === topicFilter.value)
      && (!q || [c.id, c.front, c.back].some((s) => s.toLowerCase().includes(q))));
    count.textContent = `${shown.length} of ${data.cards.length} cards`;
    list.replaceChildren(...shown.map((c) => {
      const item = node("button", "editor-item", { type: "button" });
      item.append(el("span", "editor-id", c.id), el("span", "", c.front));
      if (c.requires.length) item.append(el("span", "muted", `requires ${c.requires.length}`));
      item.addEventListener("click", () => openCard(c.id));
      const li = el("li");
      li.append(item);
      return li;
    }));
  }

  function renderChips() {
    const fronts = Object.fromEntries(data.cards.map((c) => [c.id, c.front]));
    chips.replaceChildren(...needs.map((id) => {
      const chip = node("span", "chip", { title: fronts[id] || "unknown card" }, id);
      const drop = node("button", "small", { type: "button", title: `Remove ${id}`, hidden: !data.writable }, "×");
      drop.addEventListener("click", () => { needs = needs.filter((n) => n !== id); renderChips(); });
      chip.append(drop);
      return chip;
    }));
    if (!needs.length) chips.append(el("span", "muted", "none"));
  }

  function fill(card, isNew) {
    editing = isNew ? null : card;
    listView.hidden = true;
    form.hidden = false;
    title.textContent = isNew ? "New card" : `Edit ${card.id}`;
    idBox.value = card.id;
    idBox.readOnly = !isNew || !data.writable;
    topicBox.value = card.topic;
    topicBox.disabled = !isNew;
    Object.keys(inputs).forEach((k) => { inputs[k].value = card[k]; if (k in LIMITS) countWords(k); });
    needs = [...card.requires];
    renderChips();
    say(isNew ? `Id must start with ${topicOf(card.topic).prefixes.join(" or ")}` : "Id is fixed (it is the Anki note key).");
  }

  function openList() {
    go("#edit");
    form.hidden = true;
    listView.hidden = false;
    renderList();
  }

  function openCard(id) {
    const card = data.cards.find((c) => c.id === id);
    if (!card) { openList(); count.textContent = `No card with id ${id}`; return; }
    go(`#edit/${encodeURIComponent(id)}`);
    fill(card, false);
  }

  function openNew() {
    go("#edit/new");
    const stem = topicFilter.value || data.topics[0].stem;
    fill({ id: topicOf(stem).prefixes[0], topic: stem, front: "", back: "", source: "", excerpt: "", requires: [] }, true);
  }

  function hide() {
    go(lastState?.session_id ? `#${lastState.session_id}` : location.pathname);
    root.hidden = true;
  }

  async function save(e) {
    e.preventDefault();
    if (!data.writable) return;
    const body = { id: idBox.value.trim(), new: editing === null, topic: topicBox.value, requires: needs };
    Object.keys(inputs).forEach((k) => { body[k] = inputs[k].value; });
    say("Checking source…");
    box.disabled = true;
    try {
      const reply = await post("/api/editor/save", body);
      await load();
      openCard(reply.saved);
      say(reply.note, "ok");
      loadCards().catch((err) => showError(err));  // history.js: the start picker
      refreshProgress();  // progress.js
      poll();  // net.js: the target card's new front
    } catch (err) {
      say(`Not saved: ${err.message.replace(/^HTTP \d+: /, "")}`, "error");
    } finally {
      box.disabled = false;
    }
  }

  close.addEventListener("click", hide);
  backBtn.addEventListener("click", openList);
  newBtn.addEventListener("click", openNew);
  thisBtn.addEventListener("click", () => openCard(lastState.card.id));
  topicFilter.addEventListener("change", renderList);
  search.addEventListener("input", renderList);
  topicBox.addEventListener("change", () => { if (editing === null) idBox.value = topicOf(topicBox.value).prefixes[0]; });
  Object.keys(LIMITS).forEach((k) => inputs[k].addEventListener("input", () => countWords(k)));
  form.addEventListener("submit", save);
  function addRequired() {
    const id = needInput.value.trim();
    if (!data.cards.some((c) => c.id === id)) { say(`No card with id ${id || "(empty)"}`, "error"); return; }
    if (!needs.includes(id)) needs.push(id);
    needInput.value = "";
    renderChips();
  }
  addNeed.addEventListener("click", addRequired);
  needInput.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); addRequired(); } });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !root.hidden) hide(); });
  $("edit-cards").addEventListener("click", () => { location.hash = "#edit"; });

  // target: null closes; "" the list; "new" a blank card; else a card id.
  return async (target) => {
    if (target === null) { root.hidden = true; return; }
    root.hidden = false;
    thisBtn.hidden = !lastState?.card;
    try {
      await load();
    } catch (err) {
      banner.hidden = false;
      banner.textContent = `Cards unavailable: ${err.message || err}`;
      return;
    }
    if (target === "new" && data.writable) openNew();
    else if (target && target !== "new") openCard(target);
    else openList();
  };
})();
