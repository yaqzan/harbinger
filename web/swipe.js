// Swipe between the two tabs on a touch screen: left on the Board opens the Library, right on the
// Library opens the Board. The other page is loaded once, in a hidden frame, and slides in under the
// finger, so a swipe can stop half way. Past a third of the screen (or a flick) it finishes, and
// nothing reloads: the frame simply becomes the visible page (the address bar follows through
// history.pushState) and the page you left waits underneath for the swipe back. Short of a third it
// springs back. Shared by index.html and library.html; inside the frame this script only reports the
// finger to its parent. If the frame isn't loaded yet the swipe falls back to a normal navigation.
(() => {
  const framed = window.self !== window.top;
  const lib = location.pathname.startsWith("/library");
  const target = lib ? "/" : "/library", own = location.pathname;
  const dir = lib ? 1 : -1;  // the finger's direction that goes to the other tab
  const wrap = document.querySelector(".wrap");
  if (!wrap) return;
  wrap.style.touchAction = "pan-y pinch-zoom";  // horizontal drags stay ours; scrolling stays the browser's
  const EASE = "transform .22s cubic-bezier(.2, .7, .3, 1)";
  const isOther = (p) => (lib ? !p.startsWith("/library") : p.startsWith("/library"));

  // the theme toggle in one document reaches the other through localStorage
  addEventListener("storage", (e) => {
    if (e.key !== "theme" || !e.newValue) return;
    document.documentElement.dataset.theme = e.newValue;
    document.querySelectorAll("meta[name=theme-color]").forEach((m) => { m.content = e.newValue === "dark" ? "#131311" : "#fcfcfa"; });
  });

  // ── the top page: owns the frame and the two positions ─────────────
  let frame = null, ready = false, view = "page", busy = false;
  const pageTitle = document.title;
  const dirNow = () => (view === "page" ? dir : -dir);
  const els = () => (view === "page" ? [wrap, frame] : [frame, wrap]);

  const preview = () => {
    if (frame) return frame;
    frame = document.createElement("iframe");
    frame.src = target;
    frame.tabIndex = -1;
    frame.setAttribute("aria-hidden", "true");
    frame.title = "";
    frame.addEventListener("load", () => { ready = true; });
    Object.assign(frame.style, {
      position: "fixed", inset: "0", width: "100%", height: "100%", border: "0", zIndex: "50",
      pointerEvents: "none", visibility: "hidden", background: getComputedStyle(document.body).backgroundColor,
      transform: `translateX(${-dir * 100}%)`, boxShadow: "0 0 24px rgba(0, 0, 0, .25)",
    });
    document.documentElement.appendChild(frame);  // outside .wrap, which moves
    return frame;
  };
  // Touch screens get the other page loaded once this one settles, so the first swipe isn't blank.
  if (!framed && matchMedia("(pointer: coarse)").matches) {
    addEventListener("load", () => setTimeout(() => (window.requestIdleCallback || setTimeout)(preview), 1500));
  }

  // dx is how far the page in front has moved toward the other one; the other trails one width behind
  const place = (dx, animate) => {
    const [front, back] = els(), w = innerWidth;
    front.style.transition = back.style.transition = animate ? EASE : "none";
    front.style.transform = dx ? `translateX(${dx}px)` : "";
    back.style.transform = `translateX(${dx - dirNow() * w}px)`;
    frame.style.visibility = wrap.style.visibility = "visible";
  };
  // the resting states: exactly one page visible, the other parked
  const setView = (v) => {
    view = v;
    const f = v === "frame";
    wrap.style.transition = frame.style.transition = "none";
    frame.style.visibility = f ? "visible" : "hidden";
    frame.style.transform = f ? "" : `translateX(${-dir * innerWidth}px)`;
    frame.style.pointerEvents = f ? "auto" : "none";
    frame.inert = !f;
    wrap.style.visibility = f ? "hidden" : "visible";
    wrap.style.transform = "";
    wrap.inert = f;
    document.documentElement.style.overflow = f ? "hidden" : "";
    try { document.title = f ? frame.contentDocument.title || pageTitle : pageTitle; } catch (e) {}
  };

  const done = (fn) => {
    let called = false;
    const go = () => { if (!called) { called = true; fn(); } };
    els()[0].addEventListener("transitionend", go, { once: true });
    setTimeout(go, 300);  // transitionend never comes when nothing had to move
  };
  const settle = (go) => {
    if (!frame) return;
    if (go && !ready) {  // not loaded yet: navigate, the landing fades in from this frame's picture
      try { sessionStorage.setItem("harbinger.swiped", String(Date.now())); } catch (x) {}
      place(innerWidth * dirNow(), true);
      done(() => location.assign(view === "page" ? target : own));
    } else if (go) {
      busy = true;
      place(innerWidth * dirNow(), true);
      done(() => {
        const next = view === "page" ? "frame" : "page";
        setView(next);
        history.pushState(null, "", next === "frame" ? target : own);
        busy = false;
      });
    } else {
      place(0, true);
      done(() => setView(view));
    }
  };
  // a tap on the other tab's link slides the same way
  const slide = () => {
    if (!frame || !ready || busy) return false;
    place(0, false);
    void wrap.offsetWidth;
    settle(true);
    return true;
  };

  if (!framed) {
    addEventListener("message", (e) => {
      if (!frame || e.source !== frame.contentWindow || e.origin !== location.origin || view !== "frame" || busy) return;
      const m = e.data || {};
      if (m.t === "move") place(m.d, false);
      else if (m.t === "end") settle(!!m.go);
      else if (m.t === "go") slide();
    });
    addEventListener("popstate", () => { if (frame && ready) setView(isOther(location.pathname) ? "frame" : "page"); });
    addEventListener("pageshow", (e) => { if (e.persisted && frame) setView(view); });  // back from another site via the bfcache
  }

  // ── links to the other tab never reload ────────────────────────────
  addEventListener("click", (e) => {
    const a = e.target.closest && e.target.closest("a[href]");
    if (!a || e.defaultPrevented || e.button || e.metaKey || e.ctrlKey || e.shiftKey || a.target) return;
    const u = new URL(a.href, location.href);
    if (u.origin !== location.origin) return;
    if (framed) {
      if (isOther(u.pathname)) { e.preventDefault(); parent.postMessage({ t: "go" }, location.origin); }
      else if (u.pathname === own) e.preventDefault();
    } else if (isOther(u.pathname) && slide()) {
      e.preventDefault();
    }
  }, true);

  // ── the finger ─────────────────────────────────────────────────────
  // Not from controls, open sheets, sideways scrollers (the region chips, wide tables) or the screen
  // edges, where the phone's own back and forward swipes live.
  const scrollsSideways = (n) => {
    for (; n && n !== wrap; n = n.parentElement) {
      if (n.scrollWidth > n.clientWidth + 1 && /auto|scroll/.test(getComputedStyle(n).overflowX)) return true;
    }
    return false;
  };
  const eligible = (e) => e.pointerType === "touch" && e.isPrimary && !document.querySelector("dialog[open]") && !busy
    && e.clientX > 20 && e.clientX < innerWidth - 20 && (!window.visualViewport || visualViewport.scale < 1.01)
    && !e.target.closest("input, select, textarea") && !scrollsSideways(e.target);

  let quietUntil = 0;
  addEventListener("click", (c) => { if (c.timeStamp < quietUntil) { c.stopPropagation(); c.preventDefault(); } }, true);

  const move = (d) => { if (framed) parent.postMessage({ t: "move", d }, location.origin); else place(d, false); };
  const end = (go) => { if (framed) parent.postMessage({ t: "end", go }, location.origin); else settle(go); };

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
      if (!framed) preview();
      wrap.setPointerCapture(e.pointerId);
    }
    const w = innerWidth;
    // toward the other page it follows the finger; the wrong way it barely gives
    const d = dx * dir > 0 ? Math.min(Math.abs(dx), w) * dir : dx * 0.08;
    g.v = (d - g.dx) / Math.max(1, e.timeStamp - g.t);
    g.dx = d;
    g.t = e.timeStamp;
    move(d);
  });
  const release = (e) => {
    if (!g || e.pointerId !== g.id) return;
    const was = g;
    g = null;
    if (was.lock !== "x") return;
    const v = e.timeStamp - was.t < 100 ? was.v : 0;  // a finger that paused before lifting isn't flicking
    const go = e.type === "pointerup" && (was.dx * dir > innerWidth / 3 || (v * dir > 0.45 && was.dx * dir > 30));
    quietUntil = e.timeStamp + 400;  // the lift must not also open the row under the finger
    end(go);
  };
  wrap.addEventListener("pointerup", release);
  wrap.addEventListener("pointercancel", release);
})();
