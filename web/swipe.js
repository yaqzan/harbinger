// Swipe between the two tabs on a touch screen: left on the Board opens the Library, right on the
// Library opens the Board. The other page waits in a hidden frame and slides in under your finger,
// so a swipe can stop half way. Past a third of the screen (or a flick) it finishes and opens the
// real page; short of that it springs back. Shared by index.html and library.html.
(() => {
  if (window.self !== window.top) return;  // the preview frame itself
  const lib = location.pathname.startsWith("/library");
  const target = lib ? "/" : "/library", dir = lib ? 1 : -1;  // the finger's direction that goes there
  const wrap = document.querySelector(".wrap");
  if (!wrap) return;
  wrap.style.touchAction = "pan-y pinch-zoom";  // horizontal drags stay ours; scrolling stays the browser's
  const EASE = "transform .22s cubic-bezier(.2, .7, .3, 1)";

  let frame = null;
  const preview = () => {
    if (frame) return frame;
    frame = document.createElement("iframe");
    frame.src = target;
    frame.tabIndex = -1;
    frame.setAttribute("aria-hidden", "true");
    frame.title = "";
    Object.assign(frame.style, {
      position: "fixed", inset: "0", width: "100%", height: "100%", border: "0", zIndex: "50",
      pointerEvents: "none", visibility: "hidden", background: getComputedStyle(document.body).backgroundColor,
      transform: `translateX(${-dir * 100}%)`, boxShadow: "0 0 24px rgba(0, 0, 0, .25)",
    });
    document.documentElement.appendChild(frame);  // outside .wrap, which moves
    return frame;
  };
  // Touch screens get the other page loaded once this one settles, so the first swipe isn't blank.
  if (matchMedia("(pointer: coarse)").matches) {
    addEventListener("load", () => setTimeout(() => (window.requestIdleCallback || setTimeout)(preview), 1500));
  }

  const place = (dx, animate) => {
    const w = innerWidth;
    wrap.style.transition = frame.style.transition = animate ? EASE : "none";
    wrap.style.transform = dx ? `translateX(${dx}px)` : "";
    frame.style.transform = `translateX(${dx - dir * w}px)`;
    frame.style.visibility = dx || animate ? "visible" : "hidden";
  };
  const done = (fn) => {
    let called = false;
    const go = () => { if (!called) { called = true; fn(); } };
    wrap.addEventListener("transitionend", go, { once: true });
    setTimeout(go, 300);  // transitionend never comes when nothing had to move
  };

  // Not from controls, open sheets, sideways scrollers (the region chips, wide tables) or the screen
  // edges, where the phone's own back and forward swipes live.
  const scrollsSideways = (n) => {
    for (; n && n !== wrap; n = n.parentElement) {
      if (n.scrollWidth > n.clientWidth + 1 && /auto|scroll/.test(getComputedStyle(n).overflowX)) return true;
    }
    return false;
  };
  const eligible = (e) => e.pointerType === "touch" && e.isPrimary && !document.querySelector("dialog[open]")
    && e.clientX > 20 && e.clientX < innerWidth - 20 && (!window.visualViewport || visualViewport.scale < 1.01)
    && !e.target.closest("input, select, textarea") && !scrollsSideways(e.target);

  let quietUntil = 0;
  addEventListener("click", (c) => { if (c.timeStamp < quietUntil) { c.stopPropagation(); c.preventDefault(); } }, true);

  let g = null;  // the gesture: start point, lock ("x" sideways, "y" a scroll), last move for the flick
  wrap.addEventListener("pointerdown", (e) => {
    g = eligible(e) ? { id: e.pointerId, x0: e.clientX, y0: e.clientY, lock: "", dx: 0, t: e.timeStamp, v: 0 } : null;
  });
  wrap.addEventListener("pointermove", (e) => {
    if (!g || e.pointerId !== g.id || g.lock === "y") return;
    const dx = e.clientX - g.x0, dy = e.clientY - g.y0;
    if (!g.lock) {
      if (Math.abs(dx) < 10 && Math.abs(dy) < 10) return;
      g.lock = Math.abs(dx) > Math.abs(dy) * 1.2 ? "x" : "y";
      if (g.lock === "y") return;
      preview();
      wrap.setPointerCapture(e.pointerId);
    }
    const w = innerWidth;
    // toward the other page it follows the finger; the wrong way it barely gives
    const d = dx * dir > 0 ? Math.min(Math.abs(dx), w) * dir : dx * 0.08;
    g.v = (d - g.dx) / Math.max(1, e.timeStamp - g.t);
    g.dx = d;
    g.t = e.timeStamp;
    place(d, false);
  });
  const release = (e) => {
    if (!g || e.pointerId !== g.id) return;
    const was = g;
    g = null;
    if (was.lock !== "x") return;
    const v = e.timeStamp - was.t < 100 ? was.v : 0;  // a finger that paused before lifting isn't flicking
    const go = e.type === "pointerup" && (was.dx * dir > innerWidth / 3 || (v * dir > 0.45 && was.dx * dir > 30));
    quietUntil = e.timeStamp + 400;  // the lift must not also open the row under the finger
    if (go) {
      place(innerWidth * dir, true);
      // the new page fades in from this frame's picture instead of flashing blank (pagereveal in the html)
      try { sessionStorage.setItem("harbinger.swiped", "1"); } catch (x) {}
      done(() => location.assign(target));
    } else {
      place(0, true);
      done(() => place(0, false));
    }
  };
  wrap.addEventListener("pointerup", release);
  wrap.addEventListener("pointercancel", release);
  // back from the other page via the bfcache: put this one back where it was
  addEventListener("pageshow", (e) => { if (e.persisted && frame) place(0, false); });
})();
