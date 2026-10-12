// The detail sheet: every close (x, backdrop, Esc, swipe) plays the opening animation backwards, and on
// a touch screen the sheet follows your finger down and leaves when you let go past a short pull.
(() => {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)");
  const nativeClose = HTMLDialogElement.prototype.close;

  const finish = (d) => {
    if (!d.classList.contains("closing")) return;
    d.classList.remove("closing");
    d.style.transform = d.style.transition = "";
    nativeClose.call(d);
  };

  HTMLDialogElement.prototype.close = function (returnValue) {
    if (!this.open || this.classList.contains("closing")) return;
    if (reduce.matches) { nativeClose.call(this, returnValue); return; }
    this.classList.add("closing");
    this.addEventListener("animationend", () => finish(this), { once: true });
    setTimeout(() => finish(this), 450);
  };

  for (const d of document.querySelectorAll("dialog")) {
    d.addEventListener("cancel", (e) => { e.preventDefault(); d.close(); });
    d.addEventListener("click", (e) => {
      if (e.target.closest(".x")) { e.preventDefault(); d.close(); }
    });

    let y0 = null, dy = 0, drag = false, t0 = 0;
    d.addEventListener("touchstart", (e) => {
      if (e.touches.length !== 1 || d.classList.contains("closing") || d.scrollTop > 0) { y0 = null; return; }
      y0 = e.touches[0].clientY; dy = 0; drag = false; t0 = e.timeStamp;
    }, { passive: true });
    d.addEventListener("touchmove", (e) => {
      if (y0 === null) return;
      dy = e.touches[0].clientY - y0;
      if (!drag) {
        if (dy < -4 || d.scrollTop > 0) { y0 = null; return; }
        if (dy < 8) return;
        drag = true; d.style.transition = "none";
      }
      e.preventDefault();
      d.style.transform = `translateY(${Math.max(0, dy)}px)`;
    }, { passive: false });
    const release = (e) => {
      if (!drag) { y0 = null; return; }
      const fast = dy / Math.max(1, e.timeStamp - t0) > 0.6;
      const gone = dy > 90 || fast;
      drag = false; y0 = null;
      d.style.transition = reduce.matches ? "none" : "transform .22s cubic-bezier(.2, .8, .2, 1)";
      if (gone) {
        d.classList.add("closing");
        d.style.transform = `translateY(${d.offsetHeight + 40}px)`;
        d.addEventListener("transitionend", () => finish(d), { once: true });
        setTimeout(() => finish(d), 450);
      } else {
        d.style.transform = "";
      }
    };
    d.addEventListener("touchend", release);
    d.addEventListener("touchcancel", release);
  }
})();
