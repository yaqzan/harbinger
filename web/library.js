// Library page: reads /library.json (every game on Game Pass, your PS Plus tier, Steam or PlayStation)
// and draws it as a grid or list, sorted by a score and filtered by where the game lives.
// Data is untrusted text: everything goes in through textContent, never innerHTML.
(async () => {
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  };
  const NS = "http://www.w3.org/2000/svg";
  const sv = (tag, attrs) => {
    const n = document.createElementNS(NS, tag);
    Object.entries(attrs || {}).forEach(([k, v]) => n.setAttribute(k, v));
    return n;
  };
  const store = {
    get: (k, d) => { try { return localStorage.getItem(`harbinger.lib.${k}`) ?? d; } catch (e) { return d; } },
    set: (k, v) => { try { localStorage.setItem(`harbinger.lib.${k}`, v); } catch (e) {} },
  };
  const ago = (iso) => {
    if (!iso) return "never";
    const s = (Date.now() - new Date(iso)) / 1000;
    if (s < 3600) return `${Math.max(1, Math.round(s / 60))}m ago`;
    if (s < 86400) return `${Math.round(s / 3600)}h ago`;
    const d = Math.round(s / 86400);
    return d === 1 ? "yesterday" : `${d} days ago`;
  };

  $("theme").addEventListener("click", () => {
    const root = document.documentElement;
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    // the phone's browser bar follows the page, not the system setting
    document.querySelectorAll("meta[name=theme-color]").forEach((m) => { m.content = dark ? "#fcfcfa" : "#131311"; });
    try { localStorage.setItem("theme", root.dataset.theme); } catch (e) {}
  });

  let lib;
  try {
    const r = await fetch("/library.json", { cache: "no-cache" });
    if (!r.ok) throw new Error(r.status);
    lib = await r.json();
  } catch (e) {
    $("meta").textContent = "No data yet. The first ingest hasn't run.";
    return;
  }
  const rows = lib.rows;
  const hasPs = lib.ps_tier && lib.ps_tier !== "none";

  // ── time ─────────────────────────────────────────────────────────
  const DAY = 864e5;
  const now = new Date();
  const T0 = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  const t = (s) => Date.UTC(+s.slice(0, 4), +s.slice(5, 7) - 1, +s.slice(8, 10));
  const fmt = (ms) => new Date(ms).toLocaleDateString("en-US", {
    month: "short", day: "numeric", timeZone: "UTC", ...(new Date(ms).getUTCFullYear() !== new Date(T0).getUTCFullYear() ? { year: "numeric" } : {}),
  });

  // ── what each row is ─────────────────────────────────────────────
  const psName = (r) => (r.ps === "Claimed" ? "PS Plus claim" : `PS Plus ${r.ps}`);
  const places = (r) => [r.gp ? "Game Pass" : "", r.ps ? psName(r) : "", r.steam ? "Steam" : "", r.psn ? "PlayStation library" : ""].filter(Boolean);
  const coverUrl = (r) => (/^\/art\/[0-9a-f]{16}\.(jpg|png)$/.test(r.art || "") ? `${r.art}?v=2` : null);
  const cover = (r, cls) => {
    const box = el("div", cls);
    const url = coverUrl(r);
    if (url) { const i = el("img"); i.src = url; i.alt = ""; i.loading = "lazy"; box.appendChild(i); }
    else { box.classList.add("blank"); box.appendChild(el("span", null, r.game)); }
    return box;
  };
  const leaves = (r) => {
    const out = [];
    [["Game Pass", r.gp_leaves], ["PS Plus", r.ps_leaves]].forEach(([svc, lv]) => {
      if (lv && t(lv[0]) >= T0) out.push({ svc, ms: t(lv[0]), band: lv[1], p: lv[2] });
    });
    return out.sort((a, b) => a.ms - b.ms);
  };
  const leaveText = (x) => (x.band === "Confirmed" ? `Leaves ${fmt(x.ms)}` : `${x.band} (${Math.round((x.p || 0) * 100)}%), could go ${fmt(x.ms)}`);
  const soonest = (r) => { const l = leaves(r); return l.length ? l[0].ms : Infinity; };

  // ── the three places, as a Venn ──────────────────────────────────
  // region id = gp*4 + ps*2 + steam; 0 is outside every circle (PlayStation purchases only)
  const region = (r) => (r.gp ? 4 : 0) + (r.ps ? 2 : 0) + (r.steam ? 1 : 0);
  const NAMES = { 4: "Game Pass only", 2: "PS Plus only", 1: "Steam only", 6: "Game Pass and PS Plus", 5: "Game Pass and Steam",
    3: "PS Plus and Steam", 7: "All three", 0: "PlayStation library only" };
  const ORDER = [4, 2, 1, 6, 5, 3, 7, 0];
  const SETS = [{ bit: 4, name: "Game Pass", cls: "xbox", cx: 112, cy: 100 }, { bit: 2, name: "PS Plus", cls: "ps", cx: 188, cy: 100 },
    { bit: 1, name: "Steam", cls: "steam", cx: 150, cy: 160 }];
  const R = 70;
  const sel = new Set((store.get("regions", "") || "").split(",").filter((x) => x !== "").map(Number).filter((n) => n >= 0 && n <= 7));
  const setsOf = (id) => SETS.filter((s) => id & s.bit);

  const venn = $("venn");
  const defs = sv("defs");
  SETS.forEach((s, i) => {
    const cp = sv("clipPath", { id: `cp${i}` });
    cp.appendChild(sv("circle", { cx: s.cx, cy: s.cy, r: R }));
    defs.appendChild(cp);
  });
  // one mask per region: white inside every circle it needs, black inside every circle it must not be in
  ORDER.forEach((id) => {
    const m = sv("mask", { id: `m${id}`, maskUnits: "userSpaceOnUse", x: 0, y: 0, width: 300, height: 250 });
    m.appendChild(sv("rect", { x: 0, y: 0, width: 300, height: 250, fill: "#000" }));
    // white where all needed circles overlap (nested clips), then black over the excluded circles
    let g = m;
    SETS.forEach((s, i) => {
      if (id & s.bit) { const n = sv("g", { "clip-path": `url(#cp${i})` }); g.appendChild(n); g = n; }
    });
    g.appendChild(sv("rect", { x: 0, y: 0, width: 300, height: 250, fill: "#fff" }));
    SETS.forEach((s) => { if (!(id & s.bit)) m.appendChild(sv("circle", { cx: s.cx, cy: s.cy, r: R, fill: "#000" })); });
    defs.appendChild(m);
  });
  venn.appendChild(defs);
  SETS.forEach((s) => venn.appendChild(sv("circle", { cx: s.cx, cy: s.cy, r: R, class: `vc ${s.cls}` })));
  const hl = sv("g", { class: "vhl" });
  venn.appendChild(hl);
  SETS.forEach((s) => venn.appendChild(sv("circle", { cx: s.cx, cy: s.cy, r: R, class: "vo" })));
  const labels = { 4: [88, 80], 2: [212, 80], 1: [150, 198], 6: [150, 74], 5: [124, 134], 3: [176, 134], 7: [150, 118], 0: [30, 232] };
  const counts = {};
  ORDER.forEach((id) => {
    const tx = sv("text", { x: labels[id][0], y: labels[id][1], class: "vt" });
    counts[id] = tx;
    venn.appendChild(tx);
  });
  SETS.forEach((s) => {
    const pos = { 4: [62, 36], 2: [238, 36], 1: [150, 244] }[s.bit];
    const tx = sv("text", { x: pos[0], y: pos[1], class: "vn", "text-anchor": "middle" });
    tx.textContent = s.name;
    venn.appendChild(tx);
  });
  const regionAt = (x, y) => SETS.reduce((id, s) => ((x - s.cx) ** 2 + (y - s.cy) ** 2 <= R * R ? id | s.bit : id), 0);
  venn.addEventListener("click", (e) => {
    const p = venn.createSVGPoint();
    p.x = e.clientX; p.y = e.clientY;
    const q = p.matrixTransform(venn.getScreenCTM().inverse());
    toggle(regionAt(q.x, q.y));
  });

  const toggle = (id) => {
    sel.has(id) ? sel.delete(id) : sel.add(id);
    store.set("regions", [...sel].join(","));
    draw();
  };

  // ── filters ──────────────────────────────────────────────────────
  const ctl = { q: $("q"), sort: $("sort"), genre: $("genre"), rated: $("rated") };
  const genres = [...rows.reduce((m, r) => (r.genre ? m.set(r.genre, (m.get(r.genre) || 0) + 1) : m), new Map())].sort((a, b) => b[1] - a[1]);
  genres.forEach(([g]) => { const o = el("option", null, g); o.value = g; ctl.genre.appendChild(o); });
  ctl.sort.value = store.get("sort", "mc");
  if (ctl.sort.value === "") ctl.sort.value = "mc";
  ctl.genre.value = store.get("genre", "");
  if (ctl.genre.value !== store.get("genre", "")) ctl.genre.value = "";
  ctl.rated.checked = store.get("rated", "0") === "1";
  if (!hasPs) ctl.sort.querySelector('[value="us"]').remove();

  const METRIC = { mc: (r) => r.mc, rating: (r) => r.rating, us: (r) => r.us, hours: (r) => r.hours, hoursd: (r) => r.hours, year: (r) => r.year };
  const SORT = {
    mc: (a, b) => b.mc - a.mc || (b.rating ?? 0) - (a.rating ?? 0),
    rating: (a, b) => b.rating - a.rating || (b.reviews ?? 0) - (a.reviews ?? 0),
    us: (a, b) => b.us - a.us,
    hours: (a, b) => a.hours - b.hours,
    hoursd: (a, b) => b.hours - a.hours,
    year: (a, b) => b.year - a.year,
    leaves: (a, b) => soonest(a) - soonest(b),
    name: () => 0,
  };
  const matches = (r, skipRegion) => {
    const q = ctl.q.value.trim().toLowerCase(), g = ctl.genre.value;
    if (q && !r.game.toLowerCase().includes(q)) return false;
    if (g && r.genre !== g) return false;
    if (ctl.rated.checked && METRIC[ctl.sort.value] && METRIC[ctl.sort.value](r) == null) return false;
    if (ctl.sort.value === "leaves" && ctl.rated.checked && soonest(r) === Infinity) return false;
    return skipRegion || !sel.size || sel.has(region(r));
  };

  // ── drawing ──────────────────────────────────────────────────────
  const STEP = 96;
  let shown = STEP;
  const scoreOf = (r) => {
    const s = ctl.sort.value;
    if (s === "rating" && r.rating != null) return [`${r.rating}%`, "steam"];
    if (s === "us" && r.us != null) return [r.us.toFixed(1), "ps"];
    if (r.mc != null) return [String(Math.round(r.mc)), "mc"];
    if (r.rating != null) return [`${r.rating}%`, "steam"];
    return null;
  };
  const sub = (r) => [
    r.mc != null ? `MC ${Math.round(r.mc)}` : "",
    r.rating != null ? `Steam ${r.rating}%` : "",
    r.hours != null ? `${r.hours} h` : "",
  ].filter(Boolean).join(" · ") || r.genre || "";

  const dots = (r) => {
    const box = el("span", "dots");
    if (r.gp) box.appendChild(el("span", "dot xbox"));
    if (r.ps) box.appendChild(el("span", "dot ps"));
    if (r.steam) box.appendChild(el("span", "dot steam"));
    if (r.psn) box.appendChild(el("span", "dot psn"));
    return box;
  };

  const tile = (r) => {
    const b = el("button", "tile lib");
    b.type = "button";
    b.title = r.game;
    const c = cover(r, "cv");
    const sc = scoreOf(r);
    if (sc) c.appendChild(el("span", `odds sc-${sc[1]}`, sc[0]));
    const lv = leaves(r)[0];
    if (lv) c.appendChild(el("span", "rib", lv.band === "Confirmed" ? `Leaves ${fmt(lv.ms)}` : `${lv.band} · ${fmt(lv.ms)}`));
    b.appendChild(c);
    const row = el("span", "lr");
    row.appendChild(dots(r));
    b.appendChild(row);
    b.appendChild(el("span", "nm", r.game));
    b.appendChild(el("span", "sub", sub(r)));
    b.addEventListener("click", () => open(r));
    return b;
  };

  const num = (v, f) => (v == null ? "" : f ? f(v) : String(v));
  const heads = [...document.querySelectorAll("#list thead th")].map((th) => th.textContent);
  const listRow = (r) => {
    const tr = el("tr");
    tr.tabIndex = 0;
    const g = el("td", "game");
    if (coverUrl(r)) { const i = el("img", "art"); i.src = coverUrl(r); i.alt = ""; i.loading = "lazy"; i.width = 24; i.height = 36; g.appendChild(i); }
    g.appendChild(document.createTextNode(r.game));
    tr.appendChild(g);
    const w = el("td", "nowrap places");
    w.appendChild(dots(r));
    tr.appendChild(w);
    tr.appendChild(el("td", "num", num(r.mc, Math.round)));
    tr.appendChild(el("td", "num", r.rating != null ? `${r.rating}%` : ""));
    tr.appendChild(el("td", "num", num(r.us, (v) => v.toFixed(1))));
    tr.appendChild(el("td", "num h", num(r.hours)));
    tr.appendChild(el("td", "num", num(r.year)));
    const lv = leaves(r)[0];
    tr.appendChild(el("td", "nowrap", lv ? `${lv.band === "Confirmed" ? "" : `${lv.band} `}${fmt(lv.ms)}` : ""));
    // each cell carries its column name, shown as a label when a phone stacks the row
    [...tr.children].forEach((c, i) => { c.dataset.label = heads[i] || ""; });
    tr.addEventListener("click", () => open(r));
    tr.addEventListener("keydown", (e) => { if (e.key === "Enter") open(r); });
    return tr;
  };

  const dlg = $("detail");
  const open = (r) => {
    $("d-cover").replaceChildren(cover(r, "big"));
    $("d-name").textContent = r.game;
    $("d-svc").textContent = places(r).join(" · ") || "Not on a service";
    const link = $("d-link");
    link.replaceChildren();
    if (Number.isInteger(r.appid)) {
      const a = el("a", null, "Steam store page");
      a.href = `https://store.steampowered.com/app/${r.appid}`;
      a.rel = "noopener";
      link.appendChild(a);
    }
    const facts = [];
    if (r.mc != null) facts.push(["Metacritic", String(Math.round(r.mc))]);
    if (r.rating != null) facts.push(["Steam reviews", `${r.rating}% positive of ${r.reviews.toLocaleString()}`]);
    if (r.us != null) facts.push(["PlayStation users", `${r.us.toFixed(1)} of 10`]);
    if (r.hours != null) facts.push(["To 100%", `${r.hours} h`]);
    if (r.played) facts.push(["You played", `${r.played} h`]);
    if (r.genre) facts.push(["Genre", r.genre]);
    if (r.year) facts.push(["Released", String(r.year)]);
    leaves(r).forEach((x) => facts.push([`On ${x.svc}`, leaveText(x)]));
    if (!facts.length) facts.push(["Scores", "None on file yet"]);
    $("d-facts").replaceChildren(...facts.flatMap(([k, v]) => [el("dt", null, k), el("dd", null, v)]));
    dlg.showModal();
  };
  dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });

  const drawRegions = () => {
    const base = rows.filter((r) => matches(r, true));
    const n = {};
    base.forEach((r) => { n[region(r)] = (n[region(r)] || 0) + 1; });
    const box = $("regions");
    box.replaceChildren(...ORDER.filter((id) => (n[id] || 0) > 0 || sel.has(id)).filter((id) => hasPs || !(id & 2)).map((id) => {
      const b = el("button", `chip-r${sel.has(id) ? " on" : ""}`);
      b.type = "button";
      b.setAttribute("aria-pressed", String(sel.has(id)));
      setsOf(id).forEach((s) => b.appendChild(el("span", `dot ${s.cls}`)));
      b.appendChild(document.createTextNode(`${NAMES[id]} `));
      b.appendChild(el("small", null, String(n[id] || 0)));
      b.addEventListener("click", () => toggle(id));
      return b;
    }));
    ORDER.forEach((id) => { counts[id].textContent = n[id] ? String(n[id]) : ""; });
    hl.replaceChildren(...[...sel].map((id) => {
      const g = sv("g", { mask: `url(#m${id})` });
      g.appendChild(sv("rect", { x: 0, y: 0, width: 300, height: 250, class: "vsel" }));
      return g;
    }));
    $("where-note").textContent = sel.size ? `Showing ${[...sel].sort((a, b) => ORDER.indexOf(a) - ORDER.indexOf(b)).map((id) => NAMES[id]).join(", ")}.`
      : "Pick one or more. Nothing picked shows every game.";
  };

  let layout = store.get("layout", "grid") === "list" ? "list" : "grid";
  const draw = (keepPage) => {
    if (!keepPage) shown = STEP;
    const sort = ctl.sort.value;
    const out = rows.filter((r) => matches(r));
    // games without the score go last, then the sort's own order, then the name
    out.sort((a, b) => {
      const m = METRIC[sort];
      const an = m ? m(a) == null : sort === "leaves" ? soonest(a) === Infinity : false;
      const bn = m ? m(b) == null : sort === "leaves" ? soonest(b) === Infinity : false;
      if (an !== bn) return an ? 1 : -1;
      return (an ? 0 : SORT[sort](a, b)) || a.game.localeCompare(b.game);
    });
    $("count").textContent = `${out.length.toLocaleString()} game${out.length === 1 ? "" : "s"}`;
    $("empty").hidden = out.length > 0;
    $("grid").hidden = layout !== "grid" || !out.length;
    $("list").hidden = layout !== "list" || !out.length;
    $("more").hidden = out.length <= shown;
    $("more").textContent = `Show ${Math.min(STEP, out.length - shown)} more of ${out.length - shown}`;
    document.querySelectorAll("[data-layout]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.layout === layout)));
    const page = out.slice(0, shown);
    if (layout === "grid") $("grid").replaceChildren(...page.map(tile));
    else $("list").querySelector("tbody").replaceChildren(...page.map(listRow));
    drawRegions();
  };

  document.querySelectorAll("[data-layout]").forEach((b) => b.addEventListener("click", () => {
    layout = b.dataset.layout; store.set("layout", layout); draw();
  }));
  $("more").addEventListener("click", () => { shown += STEP; draw(true); });
  Object.entries(ctl).forEach(([k, n]) => n.addEventListener("input", () => {
    if (k !== "q") store.set(k, k === "rated" ? (n.checked ? "1" : "0") : n.value);
    draw();
  }));

  const have = (f) => rows.filter((r) => r[f] != null).length;
  $("meta").textContent = `${rows.length.toLocaleString()} games · ${rows.filter((r) => r.gp).length} on Game Pass`
    + `${hasPs ? ` · ${rows.filter((r) => r.ps).length} on PS Plus ${lib.ps_tier}` : ""} · ${rows.filter((r) => r.steam).length} on Steam`
    + ` · Metacritic for ${have("mc")} · Steam reviews for ${have("rating")} · updated ${ago(lib.generated_at)}`;
  draw();
})();
