// Library page: reads /library.json (every game on Game Pass, your PS Plus tier, Steam or PlayStation)
// and draws it as a grid of posters, sorted by a score and filtered by where the game lives.
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

  // ── halo and platform logos: the same rules as the leaving page (harbinger.js) ──
  // Paths: Simple Icons (CC0), 24x24.
  const LOGO = {
    xbox: ["Xbox", "M4.102 21.033C6.211 22.881 8.977 24 12 24c3.026 0 5.789-1.119 7.902-2.967 1.877-1.912-4.316-8.709-7.902-11.417-3.582 2.708-9.779 9.505-7.898 11.417zm11.16-14.406c2.5 2.961 7.484 10.313 6.076 12.912C23.002 17.48 24 14.861 24 12.004c0-3.34-1.365-6.362-3.57-8.536 0 0-.027-.022-.082-.042-.063-.022-.152-.045-.281-.045-.592 0-1.985.434-4.805 3.246zM3.654 3.426c-.057.02-.082.041-.086.042C1.365 5.642 0 8.664 0 12.004c0 2.854.998 5.473 2.661 7.533-1.401-2.605 3.579-9.951 6.08-12.91-2.82-2.813-4.216-3.245-4.806-3.245-.131 0-.223.021-.281.046v-.002zM12 3.551S9.055 1.828 6.755 1.746c-.903-.033-1.454.295-1.521.339C7.379.646 9.659 0 11.984 0H12c2.334 0 4.605.646 6.766 2.085-.068-.046-.615-.372-1.52-.339C14.946 1.828 12 3.545 12 3.545v.006z"],
    playstation: ["PlayStation", "M8.984 2.596v17.547l3.915 1.261V6.688c0-.69.304-1.151.794-.991.636.18.76.814.76 1.505v5.875c2.441 1.193 4.362-.002 4.362-3.152 0-3.237-1.126-4.675-4.438-5.827-1.307-.448-3.728-1.186-5.39-1.502zm4.656 16.241l6.296-2.275c.715-.258.826-.625.246-.818-.586-.192-1.637-.139-2.357.123l-4.205 1.5V14.98l.24-.085s1.201-.42 2.913-.615c1.696-.18 3.785.03 5.437.661 1.848.601 2.04 1.472 1.576 2.072-.465.6-1.622 1.036-1.622 1.036l-8.544 3.107V18.86zM1.807 18.6c-1.9-.545-2.214-1.668-1.352-2.32.801-.586 2.16-1.052 2.16-1.052l5.615-2.013v2.313L4.205 17c-.705.271-.825.632-.239.826.586.195 1.637.15 2.343-.12L8.247 17v2.074c-.12.03-.256.044-.39.073-1.939.331-3.996.196-6.038-.479z"],
    steam: ["Steam", "M11.979 0C5.678 0 .511 4.86.022 11.037l6.432 2.658c.545-.371 1.203-.59 1.912-.59.063 0 .125.004.188.006l2.861-4.142V8.91c0-2.495 2.028-4.524 4.524-4.524 2.494 0 4.524 2.031 4.524 4.527s-2.03 4.525-4.524 4.525h-.105l-4.076 2.911c0 .052.004.105.004.159 0 1.875-1.515 3.396-3.39 3.396-1.635 0-3.016-1.173-3.331-2.727L.436 15.27C1.862 20.307 6.486 24 11.979 24c6.627 0 11.999-5.373 11.999-12S18.605 0 11.979 0zM7.54 18.21l-1.473-.61c.262.543.714.999 1.314 1.25 1.297.539 2.793-.076 3.332-1.375.263-.63.264-1.319.005-1.949s-.75-1.121-1.377-1.383c-.624-.26-1.29-.249-1.878-.03l1.523.63c.956.4 1.409 1.5 1.009 2.455-.397.957-1.497 1.41-2.454 1.012H7.54zm11.415-9.303c0-1.662-1.353-3.015-3.015-3.015-1.665 0-3.015 1.353-3.015 3.015 0 1.665 1.35 3.015 3.015 3.015 1.663 0 3.015-1.35 3.015-3.015zm-5.273-.005c0-1.252 1.013-2.266 2.265-2.266 1.249 0 2.266 1.014 2.266 2.266 0 1.251-1.017 2.265-2.266 2.265-1.253 0-2.265-1.014-2.265-2.265z"],
  };
  const logos = (r) => {
    const box = el("span", "plats");
    const list = [];
    if (r.gp) list.push(["xbox", "Game Pass"]);
    if (r.ps) list.push(["playstation", psName(r)]);
    else if (r.psn) list.push(["playstation", "Owned on PlayStation"]);
    if (r.steam) list.push(["steam", "Owned on Steam"]);
    list.forEach(([p, title]) => {
      const svg = document.createElementNS(NS, "svg"), path = document.createElementNS(NS, "path");
      svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("aria-hidden", "true");
      path.setAttribute("d", LOGO[p][1]); svg.appendChild(path);
      const c = el("span", `plat ${p}`); c.title = title; c.appendChild(svg); box.appendChild(c);
    });
    return box;
  };

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
  const play = lib.play || { hours_per_week: 9 };
  // Colour = hours you have / hours needed before it leaves (green 1.5x, yellow 1.0x, red 0.5x and
  // below, grey when hours are unknown or you have it elsewhere). Brightness = odds it leaves;
  // a confirmed exit is a solid ring.
  const GREEN = 140, YELLOW = 55;
  const hsl = (h, a = 1) => (h == null ? `hsl(40 6% 62% / ${a})` : `hsl(${h} 85% 55% / ${a})`);
  const fitHue = (r, lv, backup) => {
    if (backup || r.hours == null) return null;
    const have = Math.max(0, Math.round((lv.ms - T0) / DAY)) / 7 * play.hours_per_week;
    const s = have / Math.max(0.1, r.hours);
    if (s >= 1.5) return GREEN;
    if (s >= 1) return Math.round(YELLOW + (GREEN - YELLOW) * (s - 1) / 0.5);
    if (s > 0.5) return Math.round(YELLOW * (s - 0.5) / 0.5);
    return 0;
  };
  // you have it elsewhere: owned, or the other service holds it and isn't dropping it
  const hasElsewhere = (r, lv) => !!(r.steam || r.psn || (lv.svc === "Game Pass" ? r.ps && !r.ps_leaves : r.gp && !r.gp_leaves));
  const halo = (r, c) => {
    const lv = leaves(r)[0];
    if (!lv) return;
    const backup = hasElsewhere(r, lv), h = fitHue(r, lv, backup);
    if (lv.band === "Confirmed") { c.style.boxShadow = `0 0 0 3px ${hsl(h, backup ? 0.55 : 1)}, 0 0 10px 1px ${hsl(h, backup ? 0.15 : 0.45)}`; return; }
    const k = Math.min(1, (lv.p ?? 0) / 0.6);
    c.style.boxShadow = `0 0 ${Math.round(4 + 18 * k)}px ${Math.round(3 * k)}px ${hsl(h, (backup ? 0.1 : 0.2) + (backup ? 0.25 : 0.7) * k)}`;
  };
  // Metacritic's own bands: green 75 and up, yellow 50 to 74, red under 50
  const mcCls = (n) => (n >= 75 ? "good" : n >= 50 ? "mixed" : "bad");

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
    r.rating != null ? `Steam ${r.rating}%` : "",
    r.hours != null ? `${r.hours} h` : "",
  ].filter(Boolean).join(" · ") || r.genre || "";

  const tile = (r) => {
    const b = el("button", "tile lib");
    b.type = "button";
    b.title = r.game;
    const c = cover(r, "cv");
    const sc = scoreOf(r);
    if (sc) c.appendChild(el("span", `odds sc-${sc[1]}${sc[1] === "mc" ? ` ${mcCls(r.mc)}` : ""}`, sc[0]));
    c.appendChild(logos(r));
    const lv = leaves(r)[0];
    if (lv) c.appendChild(el("span", "rib", lv.band === "Confirmed" ? `Leaves ${fmt(lv.ms)}` : `${lv.band} · ${fmt(lv.ms)}`));
    halo(r, c);
    b.appendChild(c);
    b.appendChild(el("span", "nm", r.game));
    b.appendChild(el("span", "sub", sub(r)));
    b.addEventListener("click", () => open(r));
    return b;
  };

  const dlg = $("detail");
  const open = (r) => {
    const big = cover(r, "big"); halo(r, big);
    $("d-cover").replaceChildren(big);
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
    if (r.mc != null) facts.push(["Metacritic", String(Math.round(r.mc)), `mcs ${mcCls(Math.round(r.mc))}`]);
    if (r.rating != null) facts.push(["Steam reviews", `${r.rating}% positive of ${r.reviews.toLocaleString()}`]);
    if (r.us != null) facts.push(["PlayStation users", `${r.us.toFixed(1)} of 10`]);
    if (r.hours != null) facts.push(["To 100%", `${r.hours} h`]);
    if (r.played) facts.push(["You played", `${r.played} h`]);
    if (r.genre) facts.push(["Genre", r.genre]);
    if (r.year) facts.push(["Released", String(r.year)]);
    leaves(r).forEach((x) => facts.push([`On ${x.svc}`, leaveText(x)]));
    if (!facts.length) facts.push(["Scores", "None on file yet"]);
    $("d-facts").replaceChildren(...facts.flatMap(([k, v, cls]) => {
      const dd = el("dd");
      dd.appendChild(cls ? el("span", cls, v) : document.createTextNode(v));
      return [el("dt", null, k), dd];
    }));
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

  // On a phone the filters fold behind one button; its badge counts the ones changed from the default.
  $("fbtn").addEventListener("click", () => $("fbtn").setAttribute("aria-expanded", String($("ctl").classList.toggle("open"))));
  const draw = (keepPage) => {
    $("fbtn").dataset.n = [ctl.sort.value !== "mc", ctl.genre.value !== "", ctl.rated.checked].filter(Boolean).length;
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
    $("grid").hidden = !out.length;
    $("more").hidden = out.length <= shown;
    $("more").textContent = `Show ${Math.min(STEP, out.length - shown)} more of ${out.length - shown}`;
    const page = out.slice(0, shown);
    $("grid").replaceChildren(...page.map(tile));
    drawRegions();
  };

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
