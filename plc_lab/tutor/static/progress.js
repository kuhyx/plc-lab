"use strict";
// Deck progress: the side-panel summary (done / pending / %, per topic) and
// the "#progress" overlay with progress over time (GET /api/progress). The
// overlay sits above the chat, so the live render and its polls carry on
// underneath untouched; Close (or Esc) goes back to the live session's hash.
const PROGRESS_HASH = "#progress";
const SVG_NS = "http://www.w3.org/2000/svg";
let progressData = null;

function svg(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
  return node;
}

function meter(done, total) {
  const bar = el("span", "meter");
  const fill = el("i");
  fill.style.width = `${total ? (100 * done) / total : 0}%`;
  bar.append(fill);
  return bar;
}

function topicRow(t) {
  const row = el("li", "topic-row");
  row.append(el("span", "", t.title), el("span", "muted", `${t.done}/${t.total}`), meter(t.done, t.total));
  return row;
}

function renderSummary(p) {
  const box = $("deck-progress");
  const head = el("div", "deck-head");
  head.append(el("b", "", `${p.done} / ${p.total} done`), el("span", "muted", ` · ${p.pending} pending · ${p.percent}%`));
  const topics = el("details", "deck-topics");
  topics.append(el("summary", "", "By topic"), el("ul", ""));
  topics.lastChild.append(...p.topics.map(topicRow));
  const link = el("a", "", "Progress over time →");
  link.href = PROGRESS_HASH;
  box.replaceChildren(head, meter(p.done, p.total), topics, link);
}

// From render(): refetch only when what the summary shows can have moved.
let progressKey = null;
function noteProgress(s) {
  const key = `${s.session_id}|${s.card_done}|${s.credited_minutes}`;
  if (key !== progressKey) refreshProgress();
  progressKey = key;
}

async function refreshProgress() {
  try {
    progressData = await call("/api/progress");
    renderSummary(progressData);
    if (!$("progress-view").hidden) renderProgressView(progressData);
  } catch (err) {
    $("deck-progress").textContent = `Progress unavailable: ${err.message || err}`;
  }
}

// One single-series chart over the days: "line" (cumulative cards) or "bar"
// (minutes per day, with the daily cap as a dashed reference line). A hover
// column per day, wider than the mark, drives the tooltip.
function chart(days, key, kind, { cap = null, unit = "" } = {}) {
  const W = 760, H = 220, L = 40, R = 16, T = 16, B = 28;
  const max = Math.max(1, cap ?? 0, ...days.map((d) => d[key]));
  const step = (W - L - R) / days.length;
  const x = (i) => L + step * (i + 0.5);
  const y = (v) => T + (H - T - B) * (1 - v / max);
  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img" });
  [0, max / 2, max].forEach((v) => {
    root.append(svg("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), class: "grid" }));
    const label = svg("text", { x: L - 6, y: y(v) + 4, class: "axis", "text-anchor": "end" });
    label.textContent = Math.round(v);
    root.append(label);
  });
  if (cap !== null) {
    root.append(svg("line", { x1: L, x2: W - R, y1: y(cap), y2: y(cap), class: "cap" }));
    const label = svg("text", { x: W - R, y: y(cap) - 6, class: "axis", "text-anchor": "end" });
    label.textContent = `${cap} ${unit} cap`;
    root.append(label);
  }
  const today = days.length - 1;
  if (kind === "bar") {
    const w = Math.min(32, step - 2);
    days.forEach((d, i) => {
      if (!d[key]) return;
      const h = y(0) - y(d[key]), r = Math.min(4, h / 2, w / 2), x0 = x(i) - w / 2;
      root.append(svg("path", {
        class: i === today ? "mark today" : "mark",
        d: `M${x0},${y(0)}V${y(d[key]) + r}q0,-${r} ${r},-${r}h${w - 2 * r}q${r},0 ${r},${r}V${y(0)}Z`,
      }));
    });
  } else {
    root.append(svg("polyline", { class: "line", points: days.map((d, i) => `${x(i)},${y(d[key])}`).join(" ") }));
    days.forEach((d, i) => root.append(svg("circle", { cx: x(i), cy: y(d[key]), r: i === today ? 5 : 4, class: i === today ? "dot today" : "dot" })));
  }
  root.append(svg("line", { x1: L, x2: W - R, y1: y(0), y2: y(0), class: "baseline" }));
  const every = Math.ceil(days.length / 8);  // at most ~8 date labels
  days.forEach((d, i) => {
    if (i % every && i !== today) return;
    const label = svg("text", { x: x(i), y: H - 8, class: "axis", "text-anchor": "middle" });
    label.textContent = i === today ? "today" : d.day.slice(5);
    root.append(label);
  });
  days.forEach((d, i) => {
    const hit = svg("rect", { x: x(i) - step / 2, y: T, width: step, height: H - T - B, class: "hit" });
    hit.addEventListener("mouseenter", () => showTip(root, x(i), y(d[key]), `${d.day}: ${d[key]} ${unit}`));
    hit.addEventListener("mouseleave", () => hideTip(root));
    root.append(hit);
  });
  return root;
}

function showTip(root, cx, cy, text) {
  hideTip(root);
  const g = svg("g", { class: "tip" });
  g.append(svg("line", { x1: cx, x2: cx, y1: 16, y2: 192, class: "crosshair" }));
  const label = svg("text", { x: cx, y: Math.max(28, cy - 12), "text-anchor": "middle" });
  label.textContent = text;
  g.append(label);
  root.append(g);
  const box = label.getBBox();
  g.insertBefore(svg("rect", { x: box.x - 6, y: box.y - 3, width: box.width + 12, height: box.height + 6, rx: 4, class: "tip-box" }), label);
}
const hideTip = (root) => root.querySelector(".tip")?.remove();

function chartFigure(title, note, chartNode) {
  const fig = el("figure", "chart-fig");
  const cap = el("figcaption", "");
  cap.append(el("b", "", title), el("span", "muted", ` · ${note}`));
  fig.append(cap, chartNode);
  return fig;
}

function dayTable(days) {
  const det = el("details", "chart-table");
  const table = el("table", "");
  const head = el("tr", "");
  ["Day", "Cards done", "Cards done (total)", "Minutes credited"].forEach((h) => head.append(el("th", "", h)));
  table.append(head);
  [...days].reverse().forEach((d) => {
    const tr = el("tr", "");
    [d.day, d.cards_done, d.cards_done_total, d.minutes].forEach((v) => tr.append(el("td", "", String(v))));
    table.append(tr);
  });
  det.append(el("summary", "", "Show as table"), table);
  return det;
}

function renderProgressView(p) {
  const stats = el("div", "stat-row");
  [["Done", p.done], ["Pending", p.pending], ["Complete", `${p.percent}%`]].forEach(([k, v]) => {
    const tile = el("div", "stat");
    tile.append(el("div", "stat-value", String(v)), el("div", "muted", k));
    stats.append(tile);
  });
  const topics = el("ul", "topic-list");
  topics.append(...p.topics.map(topicRow));
  const minutes = p.days.reduce((sum, d) => sum + d.minutes, 0);
  $("progress-body").replaceChildren(
    stats,
    topics,
    chartFigure("Cards done", `running total, ${p.done} of ${p.total}`, chart(p.days, "cards_done_total", "line", { unit: "cards" })),
    chartFigure("Minutes credited per day", `${minutes} min since ${p.days[0].day}`, chart(p.days, "minutes", "bar", { cap: 60, unit: "min" })),
    dayTable(p.days),
  );
}

// Called by openHash (session.js) on startup and every hash change.
function showProgressView(open) {
  $("progress-view").hidden = !open;
  if (open && progressData) renderProgressView(progressData);
  if (open) refreshProgress();
}

function closeProgressView() {
  window.history.replaceState(null, "", lastState?.session_id ? `#${lastState.session_id}` : location.pathname);
  showProgressView(false);
}
$("progress-close").addEventListener("click", closeProgressView);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("progress-view").hidden) closeProgressView();
});
