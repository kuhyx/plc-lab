"use strict";
// The chat is the page's main scroller. The page itself never scrolls
// (style.css), so a wheel over the margins, the header or the gaps around
// the composer would otherwise do nothing; it scrolls #log instead.
// Left alone (native scrolling): the side panel, textareas, and anything
// else that can still scroll that way itself (error/report <pre> boxes).
// Self-contained; loaded before net.js (see index.html).
(() => {
  const LINE_PX = 40;  // Chromium's pixels per DOM_DELTA_LINE step
  const SCROLLABLE = new Set(["auto", "scroll", "overlay"]);

  function toPixels(e, scroller) {
    if (e.deltaMode === WheelEvent.DOM_DELTA_LINE) return e.deltaY * LINE_PX;
    if (e.deltaMode === WheelEvent.DOM_DELTA_PAGE) return e.deltaY * scroller.clientHeight;
    return e.deltaY;
  }

  // Can el still move in the wheel's direction, i.e. not already at that edge?
  function canScroll(el, dy) {
    if (el.scrollHeight <= el.clientHeight) return false;
    if (!SCROLLABLE.has(getComputedStyle(el).overflowY)) return false;
    return dy < 0 ? el.scrollTop > 0 : el.scrollTop + el.clientHeight < el.scrollHeight - 1;
  }

  // True when the browser should handle this wheel itself.
  function ownsWheel(target, log, dy) {
    for (let el = target; el && el !== document.body; el = el.parentElement) {
      if (el === log || el.tagName === "TEXTAREA" || el.classList.contains("side")) return true;
      if (canScroll(el, dy)) return true;
    }
    return false;
  }

  document.addEventListener("wheel", (e) => {
    const log = document.getElementById("log");
    // Zoom (Ctrl+wheel) and sideways scrolls stay native.
    if (!log || e.ctrlKey || e.deltaY === 0 || Math.abs(e.deltaX) > Math.abs(e.deltaY)) return;
    const target = e.target instanceof Element ? e.target : null;
    if (!target || ownsWheel(target, log, e.deltaY)) return;
    const dy = toPixels(e, log);
    if (!canScroll(log, dy)) return;
    e.preventDefault();
    log.scrollTop += dy;
  }, { passive: false });
})();
