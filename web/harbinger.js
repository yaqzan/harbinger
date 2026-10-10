// Harbinger page: reads /data.json and draws the board (a metro line of leaving games) and the tables
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
    $("meta").textContent = "No data yet. The first ingest hasn't run.";
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
      p: null, odds: "Reported", band: "Reported", hours: c.hours, why: c.note, progress: c.progress || "", art: c.art, unverified: c.note, mark: c.mark });
  });
  const RANK = { Confirmed: 0, Reported: 1, Likely: 1, Possible: 2, Thin: 3 };
  const rank = (r) => RANK[r.band] ?? 4;
  const svc = (r) => (r.service.startsWith("PS") ? "ps" : "xbox");
  const isClaim = (r) => r.state === "claim";
  const oddsLabel = (r) => (isClaim(r) ? "Claim" : r.unverified && r.band === "Reported" ? "Reported" : r.band === "Confirmed" ? "Confirmed" : r.p != null ? `${Math.round(r.p * 100)}%` : "");
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

  // ── top: the confirmed exit dates ────────────────────────────────
  const svcName = (r) => (svc(r) === "ps" ? "PS Plus" : "Game Pass");
  const queued = new Set((data.queue || []).map((q) => `${q.service.split(" ")[0]}|${q.key}`));
  const watching = (r) => queued.has(`${r.service.split(" ")[0]}|${r.key}`);
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
    body.appendChild(el("span", "lose", rest.length ? `lose ${rest.length}` : "all covered"));  // the phone's pill
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
    if (r.mark) facts.push(["You", MARK[r.mark]]);
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

  // ── filters ────────────────────────────────────────────────────
  const ctl = { q: $("q"), fs: $("fs"), fb: $("fb"), fr: $("fr"), so: $("so"), sb: $("sb"), sp: $("sp") };
  // a backup is either a game you own (bought, disc, claimed, every trophy) or one the other service also has
  const owned = (r) => r.backup && !r.backup.startsWith("Also on");
  // played or dropped (your notes, or `harbinger played`): hidden until the switch shows them
  const done = (r) => r.mark === "played" || r.mark === "dropped";
  const MARK = { playing: "Playing", played: "Played", dropped: "Dropped" };
  ["fs", "fb", "fr"].forEach((k) => { ctl[k].value = store.get(k, ctl[k].value); });
  // dimmed games (you have them elsewhere) start hidden; each switch remembers its own state
  ctl.so.checked = store.get("so", "0") === "1";
  ctl.sb.checked = store.get("sb", "0") === "1";
  ctl.sp.checked = store.get("sp", "0") === "1";
  if (!items.some(done)) ctl.sp.parentElement.hidden = true;
  if (one.ps_tier === "none") { ctl.fs.hidden = true; ctl.sb.parentElement.hidden = true; }
  const shown = (withDone = ctl.sp.checked) => {
    const q = ctl.q.value.trim().toLowerCase(), fs = ctl.fs.value, fb = +ctl.fb.value, fr = +ctl.fr.value;
    return items.filter((r) => (!q || r.game.toLowerCase().includes(q)) && (!fs || r.service.startsWith(fs))
      && rank(r) < fb && days(r) <= fr && (!r.backup || (owned(r) ? ctl.so.checked : ctl.sb.checked))
      && (!done(r) || withDone)
      && (r.hours != null || isClaim(r)));  // no hours, no place on a timeline: research it into titles.toml [hours]
  };

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

  // The board's stop on the line: just the fit colour. Odds and certainty live on the cover's halo.
  const lamp = (r) => {
    const l = el("span", "lamp");
    l.style.background = hsl(fitHue(r), r.backup ? 0.45 : 1);
    return l;
  };

  // Keys for the switch animation: which element is which game across a redraw, and which
  // switch hides it.
  const tag = (n, r) => {
    n.dataset.k = `${svc(r)}|${r.key || r.game}|${r.wave}`;
    const b = [r.backup ? (owned(r) ? "so" : "sb") : "", done(r) ? "sp" : ""].filter(Boolean).join(" ");
    if (b) n.dataset.b = b;
  };

  // What to do about a game, in the board's words.
  const remark = (r) => {
    if (r.backup) return r.backup;
    const when = fmt(t(r.wave));
    if (isClaim(r)) return `Claim by ${when}`;
    if (r.unverified && r.band === "Reported") return `Reported for ${when}`;
    if (r.hours != null && r.hours > avail(r)) return `Leaves ${when} · short ${Math.round(r.hours - avail(r))} h`;
    return `Leaves ${when}, ${inDays(days(r))}`;
  };
  // The board runs in order of the last day to start, not the exit date: a 2 h game leaving in
  // two weeks and a 120 h game leaving in three months can be due the same week. Start-by is
  // model.start_by (exit, minus the weeks of play, minus the buffer); claims are due on their date.
  const startGroup = (r) => {
    if (isClaim(r)) return { key: String(t(r.wave)), at: t(r.wave), label: fmt(t(r.wave)), sub: `start by, ${inDays(days(r))}` };
    // Won't fit sits above Start now: the page lands on Start now and peeks at it (landOnStart)
    if (r.hours > avail(r)) return { key: "late", at: -2, label: "Won't fit", sub: "not even starting today" };
    const sb = startBy(r);
    if (sb <= T0) return { key: "now", at: -1, label: "Start now", sub: "the start-by date has passed" };
    return { key: String(sb), at: sb, label: fmt(sb), sub: `start by, ${inDays(Math.round((sb - T0) / DAY))}` };
  };
  // Metacritic in Metacritic's own colours: green 75+, yellow 50 to 74, red under 50
  const mcBox = (r) => {
    if (r.mc == null) return el("span", "mc none", "--");
    const n = Math.round(r.mc), b = el("span", `mc ${n >= 75 ? "good" : n >= 50 ? "mixed" : "bad"}`, String(n));
    b.title = "Metacritic";
    return b;
  };
  const facts = (r) => [
    isClaim(r) ? "Monthly game" : r.band === "Confirmed" ? "Confirmed" : r.band === "Reported" ? "Reported" : `${r.band} ${oddsLabel(r)}`,
    r.rating != null ? `Steam ${r.rating}%` : r.us != null ? `PS users ${r.us.toFixed(1)}` : "",
    [r.genre, r.year].filter(Boolean).join(" "),
    watching(r) ? "In your queue" : "",
  ].filter(Boolean).join(" · ");
  // hours needed against the hours you have before it leaves, in one bar
  const fitCell = (r) => {
    const c = el("div", "m-fit"), left = Math.round(avail(r));
    if (isClaim(r)) { c.appendChild(el("span", "ft", "claim to keep it")); return c; }
    const bar = el("span", "bar"), i = el("i");
    if (r.hours == null) bar.classList.add("unk");
    else { i.style.width = `${Math.min(100, (r.hours / Math.max(1, avail(r))) * 100)}%`; i.style.background = hsl(fitHue(r)); }
    bar.appendChild(i); c.appendChild(bar);
    const ft = el("span", "ft");
    ft.appendChild(el("span", "fl", `needs ${r.hours ?? "?"} h · ${left} h left`));
    ft.appendChild(el("span", "fs", `${r.hours ?? "?"} of ${left} h`));  // the smallest phones
    c.appendChild(ft);
    return c;
  };
  const drawBoard = (rows) => {
    const host = $("board"), groups = new Map();
    rows.forEach((r) => {
      const g = startGroup(r);
      if (!groups.has(g.key)) groups.set(g.key, { ...g, its: [] });
      groups.get(g.key).its.push(r);
    });
    host.replaceChildren(...[...groups.values()].sort((a, b) => a.at - b.at).map((gr0) => {
      const its = gr0.its.sort((a, b) => !!a.backup - !!b.backup || a.wave.localeCompare(b.wave) || (b.p ?? 0) - (a.p ?? 0));
      const grp = el("div", "m-group"), head = el("div", "m-date");
      head.dataset.k = `h|${gr0.key}`;
      head.appendChild(el("b", null, gr0.label));
      head.appendChild(el("span", null, gr0.sub));
      grp.appendChild(head);
      const line = el("div", "m-line");
      its.forEach((r) => {
        const row = el("div", `m-row${r.backup || done(r) ? " dim" : ""}`);
        tag(row, r);
        row.tabIndex = 0;
        row.appendChild(lamp(r));
        const c = cover(r, "cv m-cv"); halo(r, c); row.appendChild(c);  // the halo, on the poster
        const info = el("div", "m-info"), top = el("div", "m-title");
        top.appendChild(mcBox(r));
        top.appendChild(el("span", "gn", r.game));
        if (r.mark) top.appendChild(el("span", `mk ${r.mark}`, MARK[r.mark]));
        top.appendChild(places(r, r.backup ? r.places : [svc(r) === "ps" ? "playstation" : "xbox"]));
        info.appendChild(top);
        info.appendChild(el("div", "m-facts", facts(r)));
        row.appendChild(info);
        row.appendChild(fitCell(r));
        const rm = el("div", "m-rm"), say = remark(r);
        if (say.startsWith("Leaves ")) { rm.appendChild(el("span", "lv", "Leaves ")); rm.appendChild(document.createTextNode(say.slice(7))); }
        else rm.textContent = say;  // the smallest phones drop the word "Leaves" (.lv) for the hours text
        if (!r.backup && !done(r) && fitHue(r) != null) rm.style.color = hsl(fitHue(r));  // same colour as the light
        row.appendChild(rm);
        row.addEventListener("click", () => open(r));
        row.addEventListener("keydown", (e) => { if (e.key === "Enter") open(r); });
        line.appendChild(row);
      });
      grp.appendChild(line);
      return grp;
    }));
    const late = groups.get("late");
    if (late && groups.size > 1) {  // the hint the page lands on: Won't fit is just above
      const peek = el("button", "m-peek", `↑ ${late.its.length} won't fit before ${late.its.length === 1 ? "it leaves" : "they leave"}`);
      peek.type = "button";
      peek.addEventListener("click", () => host.firstChild.scrollIntoView({ behavior: still.matches ? "auto" : "smooth", block: "start" }));
      host.firstChild.after(peek);
    }
  };
  // Open on Start now, not on the games you can't finish: scroll once so the peek sits at the top edge.
  let landed = false;
  const landOnStart = () => {
    if (landed) return;
    landed = true;
    const peek = $("board").querySelector(".m-peek");
    if (peek) scrollTo({ top: peek.getBoundingClientRect().top + scrollY - 6 });
  };

  // On a phone the filters fold behind one button; its badge counts the ones changed from the default.
  $("fbtn").addEventListener("click", () => $("fbtn").setAttribute("aria-expanded", String($("ctl").classList.toggle("open"))));
  const draw = () => {
    $("fbtn").dataset.n = [ctl.fs.value !== "", ctl.fb.value !== "2", ctl.fr.value !== "56", ctl.so.checked, ctl.sb.checked, ctl.sp.checked].filter(Boolean).length;
    const rows = shown();
    const hid = ctl.sp.checked ? 0 : shown(true).length - rows.length;
    $("count").textContent = `${rows.length} game${rows.length === 1 ? "" : "s"}${hid ? ` · ${hid} played hidden` : ""}`;
    $("empty").hidden = rows.length > 0;
    $("board").hidden = !rows.length;
    $("legend").hidden = !rows.length;
    drawBoard(rows);
    landOnStart();
  };
  // The switches animate: hiding shrinks the dimmed games away and slides the rest together;
  // showing slides the rest apart and grows the dimmed games in (FLIP on every keyed element).
  const still = matchMedia("(prefers-reduced-motion: reduce)");
  const EASE = "cubic-bezier(.2, .8, .2, 1)";
  const animatedDraw = async (hiding) => {
    const host = $("board");
    if (still.matches || !host.animate) return draw();
    if (hiding) {
      const out = [...host.querySelectorAll(`[data-b~="${hiding}"]`)];
      await Promise.all(out.map((n) => n.animate([{ opacity: 1, transform: "none" }, { opacity: 0, transform: "scale(.8)" }],
        { duration: 200, easing: "ease-in", fill: "forwards" }).finished));
    }
    const before = new Map([...host.querySelectorAll("[data-k]")].map((n) => [n.dataset.k, n.getBoundingClientRect()]));
    draw();
    host.querySelectorAll("[data-k]").forEach((n) => {
      const a = before.get(n.dataset.k), b = n.getBoundingClientRect();
      if (a) {
        const dx = a.left - b.left, dy = a.top - b.top;
        if (dx || dy) n.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: "none" }], { duration: 360, easing: EASE });
      } else {
        n.animate([{ opacity: 0, transform: "scale(.8)" }, { opacity: 1, transform: "none" }], { duration: 340, delay: 120, easing: EASE, fill: "backwards" });
      }
    });
  };
  Object.entries(ctl).forEach(([k, n]) => n.addEventListener("input", () => {
    if (k !== "q") store.set(k, n.type === "checkbox" ? (n.checked ? "1" : "0") : n.value);
    if (n.type === "checkbox") animatedDraw(n.checked ? null : k); else draw();
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
