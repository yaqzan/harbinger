// Harbinger page: reads /data.json and draws the shelf, the departures board and the tables
// below them. Data is untrusted text: everything goes in through textContent, never innerHTML.
// Day counts, hours and start-by dates are worked out here against the viewer's today, with the
// same rules as harbinger/model.py (hours_available, verdict, start_by, urgency).
(async () => {
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  };
  const ago = (iso) => {
    if (!iso) return "never";
    const s = (Date.now() - new Date(iso)) / 1000;
    if (s < 3600) return `${Math.max(1, Math.round(s / 60))}m ago`;
    if (s < 86400) return `${Math.round(s / 3600)}h ago`;
    const d = Math.round(s / 86400);
    return d === 1 ? "yesterday" : `${d} days ago`;
  };
  const store = {
    get: (k, d) => { try { return localStorage.getItem(`harbinger.${k}`) ?? d; } catch (e) { return d; } },
    set: (k, v) => { try { localStorage.setItem(`harbinger.${k}`, v); } catch (e) {} },
  };

  // theme toggle (same storage key as yaqzan.dev)
  $("theme").addEventListener("click", () => {
    const root = document.documentElement;
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    // the phone's browser bar follows the page, not the system setting
    document.querySelectorAll("meta[name=theme-color]").forEach((m) => { m.content = dark ? "#fcfcfa" : "#131311"; });
    try { localStorage.setItem("theme", root.dataset.theme); } catch (e) {}
  });

  let data;
  try {
    const r = await fetch("/data.json", { cache: "no-cache" });
    if (!r.ok) throw new Error(r.status);
    data = await r.json();
  } catch (e) {
    $("start-note").textContent = "No data yet. The first ingest hasn't run.";
    return;
  }

  // ── time, on the viewer's clock ──────────────────────────────────
  const DAY = 864e5;
  const now = new Date();
  const T0 = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  const t = (s) => Date.UTC(+s.slice(0, 4), +s.slice(5, 7) - 1, +s.slice(8, 10));
  const fmt = (ms) => new Date(ms).toLocaleDateString("en-US", {
    month: "short", day: "numeric", timeZone: "UTC", ...(new Date(ms).getUTCFullYear() !== new Date(T0).getUTCFullYear() ? { year: "numeric" } : {}),
  });
  const play = data.play || { hours_per_week: 9, buffer_weeks: 2, doable_share: 0.75, soon_weeks: 4 };
  const HPW = play.hours_per_week;
  const days = (r) => Math.round((t(r.wave) - T0) / DAY);
  const avail = (r) => Math.max(0, days(r)) / 7 * HPW;
  const startBy = (r) => t(r.wave) - (Math.ceil(r.hours / HPW) + play.buffer_weeks) * 7 * DAY;
  const fit = (r) => (r.hours == null ? "unk" : r.hours <= avail(r) * play.doable_share ? "ok" : r.hours <= avail(r) ? "tight" : "late");
  const urgency = (r) => {
    if (r.hours == null) return "Hours unknown";
    if (r.hours > avail(r)) return "Too late";
    const sb = startBy(r);
    if (sb <= T0) return "Start now";
    if (sb <= T0 + play.soon_weeks * 7 * DAY) return `Start within ${play.soon_weeks} wks`;
    return "Comfortable";
  };
  const round = (h) => Math.round(h * 10) / 10;
  const inDays = (n) => (n === 0 ? "today" : n === 1 ? "tomorrow" : `in ${n} days`);

  // ── one list: games on one service, plus the dimmed ones you have elsewhere ──
  const one = data.one_service || { rows: [], backups: [], ps_tier: "none" };
  const items = [...one.rows, ...(one.backups || [])].filter((r) => r.wave && t(r.wave) >= T0);
  const byKey = new Map(items.map((r) => [`${r.service.split(" ")[0]}|${r.key}`, r]));
  (data.confirmed || []).filter((c) => !c.verified && t(c.wave) >= T0).forEach((c) => {
    const known = byKey.get(`Game|${c.key}`);
    if (known) { known.unverified = c.note; return; }
    items.push({ game: c.game, key: c.key, service: "Game Pass", platform: c.platform, state: "reported", wave: c.wave,
      p: null, odds: "Reported", band: "Reported", hours: c.hours, why: c.note, progress: c.progress || "", art: c.art, unverified: c.note });
  });
  const RANK = { Confirmed: 0, Reported: 1, Likely: 1, Possible: 2, Thin: 3 };
  const rank = (r) => RANK[r.band] ?? 4;
  const svc = (r) => (r.service.startsWith("PS") ? "ps" : "xbox");
  const isClaim = (r) => r.state === "claim";
  const oddsLabel = (r) => (isClaim(r) ? "Claim" : r.unverified && r.band === "Reported" ? "Reported" : r.band === "Confirmed" ? "Confirmed" : r.p != null ? `${Math.round(r.p * 100)}%` : "");
  const bandCls = (r) => (isClaim(r) ? "claim" : r.band === "Reported" ? "rep" : (r.band || "none").toLowerCase());
  // ?v= busts browser caches: Cloudflare turns a 404's no-cache into a 4-hour max-age, so a cover
  // that 404'd once (server older than the art route, 2026-10-09) stays broken until the URL changes.
  const ART_V = 2;
  const coverUrl = (r) => (/^\/art\/[0-9a-f]{16}\.(jpg|png)$/.test(r.art || "") ? `${r.art}?v=${ART_V}` : null);
  const cover = (r, cls) => {
    const box = el("div", cls);
    const url = coverUrl(r);
    if (url) { const i = el("img"); i.src = url; i.alt = ""; i.loading = "lazy"; box.appendChild(i); }
    else { box.classList.add("blank"); box.appendChild(el("span", null, r.game)); }
    return box;
  };
  const order = (a, b) => a.wave.localeCompare(b.wave) || rank(a) - rank(b) || !!a.backup - !!b.backup || (b.p ?? 0) - (a.p ?? 0) || a.game.localeCompare(b.game);
  items.sort(order);

  // ── top: what to start, then the confirmed exit dates ────────────
  const svcName = (r) => (svc(r) === "ps" ? "PS Plus" : "Game Pass");
  const queued = new Set((data.queue || []).map((q) => `${q.service.split(" ")[0]}|${q.key}`));
  const watching = (r) => queued.has(`${r.service.split(" ")[0]}|${r.key}`);
  // A pick still fits before it leaves and is confirmed, reported or likely to go (or in your
  // queue at any odds), with a start-by inside the next 8 weeks. Overdue starts tie at today,
  // so among those the one that leaves first comes first.
  const PICK_WEEKS = 8, PICK_CAP = 5;
  const due = (r) => Math.max(T0, startBy(r));
  const picks = items.filter((r) => !r.backup && !isClaim(r) && r.hours != null && fit(r) !== "late"
    && (rank(r) <= 1 || watching(r)) && startBy(r) <= T0 + PICK_WEEKS * 7 * DAY)
    .sort((a, b) => due(a) - due(b) || a.wave.localeCompare(b.wave) || rank(a) - rank(b) || (b.p ?? 0) - (a.p ?? 0));
  $("start-note").textContent = picks.length
    ? `Games that may leave soon and still fit at ${HPW} hours a week. Most urgent first.`
    : `Nothing you'd lose needs starting in the next ${PICK_WEEKS} weeks.`;
  $("picks").replaceChildren(...picks.slice(0, PICK_CAP).map((r) => {
    const li = el("li"), b = el("button", "pick");
    b.type = "button";
    b.appendChild(cover(r, "pk-cv"));
    const txt = el("span", "pk-t");
    const nm = el("span", "nm", r.game);
    if (watching(r)) nm.appendChild(el("span", "tag", "In your queue"));
    txt.appendChild(nm);
    const when = `${svcName(r)} ${fmt(t(r.wave))}`;
    const why = r.band === "Confirmed" ? `Leaves ${when}` : r.band === "Reported" ? `Reported to leave ${when}` : `${oddsLabel(r)} chance it leaves ${when}`;
    txt.appendChild(el("span", "sub", `${why} · ${r.hours} h to finish`));
    b.appendChild(txt);
    const sb = startBy(r);
    b.appendChild(el("span", `by${sb <= T0 ? " now" : ""}`, sb <= T0 ? "Start now" : `Start by ${fmt(sb)}`));
    b.addEventListener("click", () => open(r));
    li.appendChild(b);
    return li;
  }));
  if (picks.length > PICK_CAP) $("picks").appendChild(el("li", "more-note", `${picks.length - PICK_CAP} more on the shelf below.`));

  const hard = items.filter((r) => r.band === "Confirmed" && !isClaim(r) && !r.unverified);
  const exits = [...new Set(hard.map((r) => `${r.wave}|${svcName(r)}`))].slice(0, 3);
  $("exits").replaceChildren(...exits.map((k) => {
    const [w, name] = k.split("|");
    const on = hard.filter((r) => r.wave === w && svcName(r) === name), rest = on.filter((r) => !r.backup);
    const fits = rest.filter((r) => fit(r) === "ok" || fit(r) === "tight").length;
    const li = el("li"), d = el("div", "d", fmt(t(w)));
    d.appendChild(el("small", null, inDays(days(on[0]))));
    li.appendChild(d);
    const body = el("div");
    body.appendChild(el("span", "nm", `${name} · ${on.length} game${on.length === 1 ? "" : "s"}`));
    const h = round(avail(on[0]));
    body.appendChild(el("span", "sub", !rest.length ? "You have all of them elsewhere."
      : `You'd lose ${rest.length}. ${fits ? `${fits} of them still fit` : rest.length === 1 ? "It doesn't fit" : "None of them fit"} in your ${h} h.`));
    li.appendChild(body);
    return li;
  }));
  if (!exits.length) $("exits").appendChild(el("li", "more-note", "Nothing is confirmed to leave yet."));
  const notice = data.summary?.next_notice;
  $("notice").textContent = notice ? `Next Game Pass leaving list expected ${notice}.` : "";
  $("notice").hidden = !notice;

  const src = data.sources;
  $("meta").textContent = `Updated ${ago(data.generated_at)}`;
  $("synced").textContent = `Page built ${ago(data.generated_at)} · sheet read ${ago(src.sheet_fetched)}${src.ps_sheet_fetched ? ` · PS Plus sheet read ${ago(src.ps_sheet_fetched)}` : ""} · forecast checked ${ago(src.forecast_checked)} · Steam synced ${ago(src.steam_synced)}${src.psn_synced ? ` · PSN synced ${ago(src.psn_synced)}` : ""}`;
  $("how-play").textContent = `Hours to play assume ${HPW} hours a week. Start by is the exit, minus the weeks of play, minus a ${play.buffer_weeks}-week buffer. A green bar fits with room to spare, amber is tight, red won't fit even if you start today.`;

  // ── detail sheet ─────────────────────────────────────────────────
  const dlg = $("detail");
  const open = (r) => {
    const big = cover(r, "big"); halo(r, big);
    $("d-cover").replaceChildren(big);
    $("d-name").textContent = r.game;
    $("d-svc").textContent = [r.service, r.platform].filter(Boolean).join(" · ");
    $("d-backup").textContent = r.backup ? `${r.backup}, so this exit costs you nothing.` : "";
    const facts = [
      ["Leaves", `${fmt(t(r.wave))}, ${inDays(days(r))}`],
      ["Odds", isClaim(r) ? "Monthly game: claim it to keep it" : r.unverified ? `Reported only: ${r.unverified}` : r.band === "Confirmed" ? "Confirmed" : `${oddsLabel(r)}, ${r.band}`],
      ["To 100%", r.hours == null ? "Unknown" : `${r.hours} h`],
      ["Hours you have", `${round(avail(r))} h before it leaves`],
    ];
    if (r.hours != null && !isClaim(r)) {
      facts.push(urgency(r) === "Too late" ? ["Start by", `Too late: ${Math.round(r.hours - avail(r))} h short even starting today`]
        : ["Start by", startBy(r) <= T0 ? `Now (${urgency(r).toLowerCase()})` : `${fmt(startBy(r))} (${urgency(r).toLowerCase()})`]);
    }
    if (r.progress) facts.push(["Progress", r.progress]);
    if (r.mc != null) facts.push(["Metacritic", String(Math.round(r.mc))]);
    if (r.rating != null) facts.push(["Steam reviews", `${r.rating}% positive of ${r.reviews.toLocaleString()}`]);
    if (r.us != null) facts.push(["PlayStation users", `${r.us.toFixed(1)} of 10`]);
    if (r.genre) facts.push(["Genre", r.genre]);
    if (r.year) facts.push(["Released", String(r.year)]);
    if (r.why) facts.push(["Why", r.why]);
    $("d-facts").replaceChildren(...facts.flatMap(([k, v]) => [el("dt", null, k), el("dd", null, v)]));
    dlg.showModal();
  };
  dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });

  // ── filters and view ─────────────────────────────────────────────
  const ctl = { q: $("q"), fs: $("fs"), fb: $("fb"), fr: $("fr"), fk: $("fk") };
  ["fs", "fb", "fr"].forEach((k) => { ctl[k].value = store.get(k, ctl[k].value); });
  ctl.fk.checked = store.get("fk", "1") === "1";
  if (one.ps_tier === "none") ctl.fs.hidden = true;
  const shown = () => {
    const q = ctl.q.value.trim().toLowerCase(), fs = ctl.fs.value, fb = +ctl.fb.value, fr = +ctl.fr.value;
    return items.filter((r) => (!q || r.game.toLowerCase().includes(q)) && (!fs || r.service.startsWith(fs))
      && rank(r) < fb && days(r) <= fr && (ctl.fk.checked || !r.backup));
  };
  const expanded = new Set();
  const CAP = 15;

  // Halo: how bright the glow is says how likely the game leaves; a confirmed exit is a solid
  // ring instead. The colour says whether you can still finish it, from s = hours you have /
  // hours needed (owner, 2026-10-10): green at 1.5x and up, yellowing to pure yellow at 1.0x
  // (just enough), then orange to red at 0.5x and below. Grey for hours unknown and backups.
  const GREEN = 140, YELLOW = 55;
  const fitHue = (r) => {
    if (r.backup || r.hours == null) return null;
    if (isClaim(r)) return GREEN;
    const s = avail(r) / Math.max(0.1, r.hours);
    if (s >= 1.5) return GREEN;
    if (s >= 1) return Math.round(YELLOW + (GREEN - YELLOW) * (s - 1) / 0.5);
    if (s > 0.5) return Math.round(YELLOW * (s - 0.5) / 0.5);
    return 0;
  };
  const hsl = (h, a = 1) => (h == null ? `hsl(40 6% 62% / ${a})` : `hsl(${h} 85% 55% / ${a})`);
  const halo = (r, c) => {
    const h = fitHue(r);
    if (r.unverified && r.band === "Reported") { c.style.outline = `2px dashed ${hsl(h)}`; c.style.outlineOffset = "1px"; return; }
    if (r.band === "Confirmed") { c.style.boxShadow = `0 0 0 3px ${hsl(h, r.backup ? 0.55 : 1)}, 0 0 10px 1px ${hsl(h, r.backup ? 0.15 : 0.45)}`; return; }
    const k = Math.min(1, (r.p ?? 0) / 0.6);  // 60% and up glows at full strength
    c.style.boxShadow = `0 0 ${Math.round(4 + 18 * k)}px ${Math.round(3 * k)}px ${hsl(h, (r.backup ? 0.1 : 0.2) + (r.backup ? 0.25 : 0.7) * k)}`;
  };

  // Mini logos for where you can still play a dimmed game. Paths: Simple Icons (CC0), 24x24.
  const LOGO = {
    xbox: ["Xbox", "M4.102 21.033C6.211 22.881 8.977 24 12 24c3.026 0 5.789-1.119 7.902-2.967 1.877-1.912-4.316-8.709-7.902-11.417-3.582 2.708-9.779 9.505-7.898 11.417zm11.16-14.406c2.5 2.961 7.484 10.313 6.076 12.912C23.002 17.48 24 14.861 24 12.004c0-3.34-1.365-6.362-3.57-8.536 0 0-.027-.022-.082-.042-.063-.022-.152-.045-.281-.045-.592 0-1.985.434-4.805 3.246zM3.654 3.426c-.057.02-.082.041-.086.042C1.365 5.642 0 8.664 0 12.004c0 2.854.998 5.473 2.661 7.533-1.401-2.605 3.579-9.951 6.08-12.91-2.82-2.813-4.216-3.245-4.806-3.245-.131 0-.223.021-.281.046v-.002zM12 3.551S9.055 1.828 6.755 1.746c-.903-.033-1.454.295-1.521.339C7.379.646 9.659 0 11.984 0H12c2.334 0 4.605.646 6.766 2.085-.068-.046-.615-.372-1.52-.339C14.946 1.828 12 3.545 12 3.545v.006z"],
    playstation: ["PlayStation", "M8.984 2.596v17.547l3.915 1.261V6.688c0-.69.304-1.151.794-.991.636.18.76.814.76 1.505v5.875c2.441 1.193 4.362-.002 4.362-3.152 0-3.237-1.126-4.675-4.438-5.827-1.307-.448-3.728-1.186-5.39-1.502zm4.656 16.241l6.296-2.275c.715-.258.826-.625.246-.818-.586-.192-1.637-.139-2.357.123l-4.205 1.5V14.98l.24-.085s1.201-.42 2.913-.615c1.696-.18 3.785.03 5.437.661 1.848.601 2.04 1.472 1.576 2.072-.465.6-1.622 1.036-1.622 1.036l-8.544 3.107V18.86zM1.807 18.6c-1.9-.545-2.214-1.668-1.352-2.32.801-.586 2.16-1.052 2.16-1.052l5.615-2.013v2.313L4.205 17c-.705.271-.825.632-.239.826.586.195 1.637.15 2.343-.12L8.247 17v2.074c-.12.03-.256.044-.39.073-1.939.331-3.996.196-6.038-.479z"],
    steam: ["Steam", "M11.979 0C5.678 0 .511 4.86.022 11.037l6.432 2.658c.545-.371 1.203-.59 1.912-.59.063 0 .125.004.188.006l2.861-4.142V8.91c0-2.495 2.028-4.524 4.524-4.524 2.494 0 4.524 2.031 4.524 4.527s-2.03 4.525-4.524 4.525h-.105l-4.076 2.911c0 .052.004.105.004.159 0 1.875-1.515 3.396-3.39 3.396-1.635 0-3.016-1.173-3.331-2.727L.436 15.27C1.862 20.307 6.486 24 11.979 24c6.627 0 11.999-5.373 11.999-12S18.605 0 11.979 0zM7.54 18.21l-1.473-.61c.262.543.714.999 1.314 1.25 1.297.539 2.793-.076 3.332-1.375.263-.63.264-1.319.005-1.949s-.75-1.121-1.377-1.383c-.624-.26-1.29-.249-1.878-.03l1.523.63c.956.4 1.409 1.5 1.009 2.455-.397.957-1.497 1.41-2.454 1.012H7.54zm11.415-9.303c0-1.662-1.353-3.015-3.015-3.015-1.665 0-3.015 1.353-3.015 3.015 0 1.665 1.35 3.015 3.015 3.015 1.663 0 3.015-1.35 3.015-3.015zm-5.273-.005c0-1.252 1.013-2.266 2.265-2.266 1.249 0 2.266 1.014 2.266 2.266 0 1.251-1.017 2.265-2.266 2.265-1.253 0-2.265-1.014-2.265-2.265z"],
  };
  const places = (r, list = r.places) => {
    const box = el("span", "plats");
    (list || []).filter((p) => LOGO[p]).forEach((p) => {
      const NS = "http://www.w3.org/2000/svg", svg = document.createElementNS(NS, "svg"), path = document.createElementNS(NS, "path");
      svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("aria-hidden", "true");
      path.setAttribute("d", LOGO[p][1]); svg.appendChild(path);
      const c = el("span", `plat ${p}`); c.title = `You can play it on ${LOGO[p][0]}`; c.appendChild(svg); box.appendChild(c);
    });
    return box;
  };

  // The board's status light: the halo's rules on a small lamp. Colour = fit, glow = odds,
  // solid lit lamp with a ring = confirmed, dashed = reported only, grey = hours unknown or a backup.
  const lamp = (r) => {
    const l = el("span", "lamp"), h = fitHue(r);
    if (r.unverified && r.band === "Reported") { l.style.border = `1.5px dashed ${hsl(h)}`; return l; }
    if (r.band === "Confirmed") {
      l.style.background = hsl(h, r.backup ? 0.45 : 1);
      l.style.boxShadow = r.backup ? "none" : `0 0 0 2px ${hsl(h, 0.35)}, 0 0 10px 2px ${hsl(h, 0.6)}`;
      return l;
    }
    const k = Math.min(1, (r.p ?? 0) / 0.6);
    l.style.background = hsl(h, (r.backup ? 0.15 : 0.2) + (r.backup ? 0.2 : 0.65) * k);
    if (!r.backup) l.style.boxShadow = `0 0 ${Math.round(3 + 9 * k)}px ${Math.round(2 * k)}px ${hsl(h, 0.15 + 0.6 * k)}`;
    return l;
  };

  const tile = (r) => {
    const b = el("button", `tile ${svc(r)}${r.backup ? " dim" : ""}`);
    b.type = "button";
    b.title = r.game;
    const c = cover(r, "cv");
    if (r.band !== "Confirmed" || isClaim(r)) c.appendChild(el("span", `odds ${bandCls(r)}`, oddsLabel(r)));  // the solid ring says confirmed
    c.appendChild(el("span", `dot ${svc(r)}`));
    if (r.backup) { c.appendChild(places(r)); b.setAttribute("aria-label", `${r.game}, ${r.backup}`); }
    halo(r, c);
    b.appendChild(c);
    if (!isClaim(r) && !r.backup) {
      const bar = el("span", `hb ${fit(r)}`), i = el("i");
      i.style.width = r.hours == null ? "100%" : `${Math.min(100, (r.hours / Math.max(1, avail(r))) * 100)}%`;
      if (r.hours != null) i.style.background = hsl(fitHue(r));
      bar.appendChild(i); b.appendChild(bar);
    }
    b.appendChild(el("span", "nm", r.game));
    const sub = isClaim(r) ? "claim to keep" : r.backup ? `${r.hours ?? "?"} h` : r.hours == null ? "? h" : fit(r) === "late" ? `${r.hours} h · short ${Math.round(r.hours - avail(r))} h` : `${r.hours} h`;
    b.appendChild(el("span", "sub", sub));
    b.addEventListener("click", () => open(r));
    return b;
  };

  const drawShelf = (rows) => {
    const host = $("shelf");
    const waves = [...new Set(rows.map((r) => r.wave))];
    host.replaceChildren(...waves.map((w) => {
      const its = rows.filter((r) => r.wave === w), col = el("div", "col");
      const h = el("h3", null, fmt(t(w)));
      h.appendChild(el("small", null, inDays(days(its[0]))));
      col.appendChild(h);
      const kinds = [...new Set(its.map(svc))];
      const cap = el("p", "cap");
      kinds.forEach((k) => { cap.appendChild(el("span", `dot ${k}`)); });
      cap.appendChild(document.createTextNode(`${kinds.length > 1 ? "Both" : kinds[0] === "ps" ? "PS Plus" : "Game Pass"} · ${round(avail(its[0]))} h to play`));
      col.appendChild(cap);
      const g = el("div", "tiles");
      const all = expanded.has(w);
      its.slice(0, all ? its.length : CAP).forEach((r) => g.appendChild(tile(r)));
      col.appendChild(g);
      if (its.length > CAP) {
        const more = el("button", "more", all ? "Show fewer" : `Show ${its.length - CAP} more`);
        more.type = "button";
        more.addEventListener("click", () => { all ? expanded.delete(w) : expanded.add(w); draw(); });
        col.appendChild(more);
      }
      return col;
    }));
  };

  // What to do about a game, in the board's words.
  const remark = (r) => {
    if (r.backup) return r.backup;
    if (isClaim(r)) return `Claim by ${fmt(t(r.wave))}`;
    if (r.unverified && r.band === "Reported") return "Unverified report";
    const u = urgency(r);
    if (u === "Hours unknown") return "Hours unknown";
    if (u === "Too late") return `Short ${Math.round(r.hours - avail(r))} h`;
    if (u === "Start now") return "Boarding · start now";
    return `${u === "Comfortable" ? "On time" : "Board soon"} · start ${fmt(startBy(r))}`;
  };
  const scoreCell = (r) => {
    const c = el("div", "m-score");
    if (r.mc != null) { const b = el("span", "mc", String(Math.round(r.mc))); b.title = "Metacritic"; c.appendChild(b); }
    else c.appendChild(el("span", "mc none", "--"));
    const user = r.rating != null ? `Steam ${r.rating}%` : r.us != null ? `PS ${r.us.toFixed(1)}` : "";
    if (user) c.appendChild(el("span", "user", user));
    return c;
  };
  // hours needed against the hours you have before it leaves, in one bar
  const fitCell = (r) => {
    const c = el("div", "m-fit"), left = Math.round(avail(r));
    if (isClaim(r)) { c.appendChild(el("span", "ft", "claim to keep it")); return c; }
    const bar = el("span", "bar"), i = el("i");
    if (r.hours == null) bar.classList.add("unk");
    else { i.style.width = `${Math.min(100, (r.hours / Math.max(1, avail(r))) * 100)}%`; i.style.background = hsl(fitHue(r)); }
    bar.appendChild(i); c.appendChild(bar);
    c.appendChild(el("span", "ft", `needs ${r.hours ?? "?"} h · ${left} h left`));
    return c;
  };
  const drawBoard = (rows) => {
    const host = $("board");
    host.replaceChildren(...[...new Set(rows.map((r) => r.wave))].map((w) => {
      const its = rows.filter((r) => r.wave === w), grp = el("div", "m-group"), head = el("div", "m-date");
      head.appendChild(el("b", null, fmt(t(w))));
      head.appendChild(el("span", null, `${inDays(days(its[0]))} · ${round(avail(its[0]))} h to play`));
      grp.appendChild(head);
      const line = el("div", "m-line");
      its.forEach((r) => {
        const row = el("div", `m-row${r.backup ? " dim" : ""}`);
        row.tabIndex = 0;
        row.appendChild(lamp(r));
        const g = el("div", "m-game");
        g.appendChild(cover(r, "cv"));
        const nm = el("span", "gn", r.game); g.appendChild(nm);
        g.appendChild(places(r, r.backup ? r.places : [svc(r) === "ps" ? "playstation" : "xbox"]));
        row.appendChild(g);
        row.appendChild(el("div", "m-odds", isClaim(r) ? "Monthly game" : r.band === "Confirmed" ? "Confirmed" : r.band === "Reported" ? "Reported" : `${r.band} ${oddsLabel(r)}`));
        row.appendChild(scoreCell(r));
        row.appendChild(fitCell(r));
        const rm = el("div", "m-rm", remark(r));
        if (!r.backup && fitHue(r) != null) rm.style.color = hsl(fitHue(r));  // same colour as the light
        row.appendChild(rm);
        row.addEventListener("click", () => open(r));
        row.addEventListener("keydown", (e) => { if (e.key === "Enter") open(r); });
        line.appendChild(row);
      });
      grp.appendChild(line);
      return grp;
    }));
  };

  let view = location.hash === "#board" ? "board" : location.hash === "#shelf" ? "shelf" : store.get("view", "shelf");
  const draw = () => {
    const rows = shown();
    $("count").textContent = `${rows.length} game${rows.length === 1 ? "" : "s"}`;
    $("empty").hidden = rows.length > 0;
    $("shelf").hidden = view !== "shelf" || !rows.length;
    $("board").hidden = view !== "board" || !rows.length;
    $("legend").hidden = !rows.length;
    document.querySelectorAll(".views button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.view === view)));
    if (view === "shelf") drawShelf(rows); else drawBoard(rows);
  };
  document.querySelectorAll(".views button").forEach((b) => b.addEventListener("click", () => {
    view = b.dataset.view; store.set("view", view); history.replaceState(null, "", `#${view}`); draw();
  }));
  Object.entries(ctl).forEach(([k, n]) => n.addEventListener("input", () => {
    if (k !== "q") store.set(k, k === "fk" ? (n.checked ? "1" : "0") : n.value);
    draw();
  }));
  draw();

  // ── the tables below ─────────────────────────────────────────────
  const fill = (tbodyId, rows, build) => {
    const tb = document.querySelector(`#${tbodyId} tbody`);
    // each cell carries its column name, shown as a label when a phone stacks the row
    const heads = [...document.querySelectorAll(`#${tbodyId} thead th`)].map((th) => th.textContent);
    tb.replaceChildren(...rows.map((r) => {
      const tr = el("tr");
      build(r, tr).forEach((td, i) => { td.dataset.label = heads[i] || ""; tr.appendChild(td); });
      return tr;
    }));
  };
  const td = (text, cls) => el("td", cls, text);
  const gameTd = (r) => {
    const c = td(null, "game");
    if (coverUrl(r)) { const i = el("img", "art"); i.src = coverUrl(r); i.alt = ""; i.loading = "lazy"; i.width = 24; i.height = 36; c.appendChild(i); }
    c.appendChild(document.createTextNode(r.game));
    return c;
  };
  const hrs = (h) => (h === null || h === undefined ? "?" : String(h));

  fill("t-queue", data.queue, (r) => [gameTd(r), td(r.state, "nowrap"), td(r.next_check, "nowrap"), td(r.odds, "nowrap"), td(r.note, "why")]);
  if (!data.queue.length) {
    $("queue").querySelector(".note").textContent = "No watched games yet. List the games you're playing or plan to play under [queue] in config.local.toml (config.local.example.toml explains it), and they show up here with the next date each could leave.";
    $("t-queue").hidden = true;
  }
  fill("t-surv", data.survivors, (r) => [td(r.game, "game"), td(r.checkpoint, "nowrap"), td(r.near_term), td(r.why, "why")]);
  fill("t-ubi", data.ubisoft, (r) => [td(r.game, "game"), td(r.checkpoint, "nowrap"), td(hrs(r.hours), "num")]);
  fill("t-cal", data.calibration, (r) => [td(r.measure), td(r.value, "nowrap"), td(r.n, "nowrap"), td(r.source, "why")]);
  fill("t-hist", data.history || [], (r) => [td(new Date(r.at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }), "nowrap"),
    td(r.confirmed, "num"), td(r.likely, "num"), td(r.possible, "num"), td(r.note, "why")]);

  const ul = $("sources");
  const covers = src.forecast_covers.length ? src.forecast_covers.join(", ") : "none yet";
  ul.appendChild(el("li", null, `Pure Xbox forecast months covered: ${covers}`));
  (src.forecast_sources || []).forEach((x) => {
    const li = el("li");
    if (/^https:\/\//.test(x.url || "")) { const a = el("a", null, x.title || x.url); a.href = x.url; a.rel = "noopener"; li.appendChild(a); }
    else li.textContent = x.title || "";
    if (x.published) li.appendChild(document.createTextNode(` · ${x.published}`));
    ul.appendChild(li);
  });
})();
