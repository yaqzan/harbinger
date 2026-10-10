"""Phone-width check for web/: loads both pages at phone sizes and fails on layout faults.

    py -3.11 ops/mobile_check.py [--base http://127.0.0.1:5006] [--shots DIR]

Needs Playwright for Python (`pip install playwright`, then its Chromium); it is not a project
dependency. Checks every state a phone user reaches (Shelf, Board, detail sheet, open sections,
library grid and list) at four phone sizes upright and one on its side, and fails if:

- the page scrolls sideways (something sticks out past the viewport, outside a scroller),
- an input or select has text under 16px (iOS Safari zooms in on focus),
- a control is smaller than 44px, or a tappable table row shorter than 40px,
- the page throws a script error.

--shots writes a PNG per state for a human to look at (full page, or the screen with a sheet open).
"""

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

SIZES = ((320, 568), (360, 800), (390, 844), (430, 932), (844, 390))  # four phones upright, one on its side
CONTROL = 44
ROW = 40

# Runs in the page. Returns a list of fault strings.
PROBE = """([CONTROL, ROW]) => {
  const out = [];
  const W = document.documentElement.clientWidth;
  if (document.documentElement.scrollWidth > W + 1) {
    // name the culprits: visible elements past the right edge that aren't inside a sideways scroller
    const inScroller = (n) => { for (let p = n.parentElement; p; p = p.parentElement) {
      const o = getComputedStyle(p).overflowX; if (o === "auto" || o === "scroll" || o === "hidden") return true; } return false; };
    const wide = [...document.querySelectorAll("body *")].filter((n) => {
      const r = n.getBoundingClientRect(); return r.width && r.right > W + 1 && !inScroller(n);
    }).slice(0, 5).map((n) => `${n.tagName.toLowerCase()}${n.id ? "#" + n.id : ""}.${[...n.classList].join(".")}`);
    out.push(`page scrolls sideways: ${document.documentElement.scrollWidth}px > ${W}px (${wide.join(", ")})`);
  }
  const visible = (n) => { const r = n.getBoundingClientRect(); const s = getComputedStyle(n);
    return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && !n.closest("[hidden]"); };
  const name = (n) => (n.getAttribute("aria-label") || n.textContent || n.id || n.tagName).trim().replace(/\\s+/g, " ").slice(0, 40);
  // inside an open modal only the dialog counts; the page behind is inert
  const scope = document.querySelector("dialog[open]") || document;
  scope.querySelectorAll("input, select").forEach((n) => {
    if (!visible(n) || n.type === "checkbox") return;
    const f = parseFloat(getComputedStyle(n).fontSize);
    if (f < 16) out.push(`${n.tagName.toLowerCase()} ${name(n)}: text ${f}px < 16px`);
  });
  scope.querySelectorAll("button, a[href], select, input, summary, label.chk").forEach((n) => {
    if (!visible(n) || n.closest(".sources, footer, .prose")) return;
    if (n.matches("input[type=checkbox]") && n.closest("label.chk")) return;  // the label is the target
    const r = n.getBoundingClientRect();
    if (Math.min(r.width, r.height) < CONTROL - 0.5) out.push(`control "${name(n)}": ${Math.round(r.width)}x${Math.round(r.height)} < ${CONTROL}px`);
  });
  const short = [...scope.querySelectorAll("tr[tabindex]")].filter(visible).map((n) => n.getBoundingClientRect().height).filter((h) => h < ROW - 0.5);
  if (short.length) out.push(`${short.length} tappable rows under ${ROW}px tall (shortest ${Math.round(Math.min(...short))}px)`);
  return out;
}"""


def go(url):
    def run(page):
        page.goto(url)
        page.wait_for_load_state("networkidle")
    return run


def click(sel):
    def run(page):
        page.locator(sel).first.click()
        page.wait_for_timeout(150)
    return run


def filters(page):
    """Open the folded filters (phones only; wider screens show them inline)."""
    if page.locator("#fbtn").is_visible():
        click("#fbtn")(page)


def open_all_details(page):
    page.evaluate("document.querySelectorAll('details').forEach((d) => d.open = true)")


# (label, steps): each list of steps drives a fresh page into one state
STATES = [
    ("leaving-board", [go("/")]),
    ("leaving-board-detail", [go("/"), click("#board .m-row")]),
    ("leaving-sections", [go("/"), open_all_details]),
    ("leaving-filters", [go("/"), filters]),
    # last per page: the switch is remembered for the rest of the context
    ("leaving-played", [go("/"), filters, click("label:has(#sp)")]),
    ("library-grid", [go("/library")]),
    ("library-grid-detail", [go("/library"), click("#grid .tile")]),
    ("library-filters", [go("/library"), filters]),
    ("library-played", [go("/library"), filters, click("label:has(#sp)")]),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="http://127.0.0.1:5006")
    ap.add_argument("--shots", type=Path, help="write a screenshot per state here")
    args = ap.parse_args()
    if args.shots:
        args.shots.mkdir(parents=True, exist_ok=True)

    faults = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for w, h in SIZES:
            ctx = browser.new_context(base_url=args.base, viewport={"width": w, "height": h},
                                      is_mobile=True, has_touch=True, device_scale_factor=2)
            for label, steps in STATES:
                # a fresh page per state: a full-page screenshot drops the touch emulation on the page
                # it was taken from, and a hash-only change wouldn't reload the view
                page = ctx.new_page()
                errors = []
                page.on("pageerror", lambda e: errors.append(f"script error: {e}"))
                for step in steps:
                    step(page)
                found = page.evaluate(PROBE, [CONTROL, ROW]) + errors
                for f in dict.fromkeys(found):  # same fault on 40 tiles reads once
                    print(f"{w}px {label}: {f}")
                faults += len(set(found))
                if args.shots:
                    page.screenshot(path=args.shots / f"{w}-{label}.png", full_page="detail" not in label)  # a sheet is fixed to the screen
                page.close()
            ctx.close()
        browser.close()
    print(f"{faults} fault{'s' if faults != 1 else ''}" if faults else "ok: no faults at " + ", ".join(f"{w}x{h}" for w, h in SIZES))
    return 1 if faults else 0


if __name__ == "__main__":
    sys.exit(main())
