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
    try { localStorage.setItem("theme", root.dataset.theme); } catch (e) {}
  });

  let data;
  try {
    const r = await fetch("/data.json", { cache: "no-cache" });
    if (!r.ok) throw new Error(r.status);
    data = await r.json();
  } catch (e) {
    $("takeaway").textContent = "No data yet. The first ingest hasn't run.";
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
  const coverUrl = (r) => (/^\/art\/[0-9a-f]{16}\.(jpg|png)$/.test(r.art || "") ? r.art : null);
  const cover = (r, cls) => {
    const box = el("div", cls);
    const url = coverUrl(r);
    if (url) { const i = el("img"); i.src = url; i.alt = ""; i.loading = "lazy"; box.appendChild(i); }
    else { box.classList.add("blank"); box.appendChild(el("span", null, r.game)); }
    return box;
  };
  const order = (a, b) => a.wave.localeCompare(b.wave) || rank(a) - rank(b) || !!a.backup - !!b.backup || (b.p ?? 0) - (a.p ?? 0) || a.game.localeCompare(b.game);
  items.sort(order);

  // ── hero: the next confirmed exit, live ──────────────────────────
  const hard = items.filter((r) => r.band === "Confirmed" && !isClaim(r) && !r.unverified);
  if (hard.length) {
    const first = hard[0].wave, on = hard.filter((r) => r.wave === first);
    const services = [...new Set(on.map((r) => (svc(r) === "ps" ? "PS Plus" : "Game Pass")))];
    const kept = on.filter((r) => r.backup), rest = on.filter((r) => !r.backup);
    const fits = rest.filter((r) => fit(r) === "ok" || fit(r) === "tight").map((r) => r.game);
    const h = round(avail(on[0]));
    let s = `${on.length} game${on.length > 1 ? "s" : ""} leave${on.length > 1 ? "" : "s"} ${services.length === 1 ? services[0] : "Game Pass and PS Plus"} on ${fmt(t(first))}.`;
    if (kept.length) s += ` You have ${kept.length === on.length ? "all of them" : kept.length} elsewhere.`;
    const them = kept.length ? "the rest" : "them";
    if (rest.length) {
      if (!fits.length) s += ` None of ${them} fits in the ${h} hours you have before then.`;
      else if (fits.length === rest.length) s += ` All of ${them} still fit in your ${h} hours.`;
      else s += ` With ${h} hours to play, ${fits.length === 1 ? "only " : ""}${fits.slice(0, 3).join(", ")}${fits.length > 3 ? ` and ${fits.length - 3} more` : ""} can still be finished.`;
    }
    const next = hard.find((r) => r.wave !== first);
    if (next) {
      const n = hard.filter((r) => r.wave === next.wave).length;
      s += ` Then ${n} on ${svc(next) === "ps" ? "PS Plus" : "Game Pass"} ${fmt(t(next.wave))}.`;
    }
    $("hero-n").textContent = days(on[0]);
    $("hero-l").textContent = `day${days(on[0]) === 1 ? "" : "s"} to ${fmt(t(first))}`;
    $("takeaway").textContent = s;
  } else {
    $("hero-n").textContent = "0";
    $("hero-l").textContent = "confirmed exits";
    $("takeaway").textContent = "Nothing is confirmed to leave yet. The likely ones are below.";
  }
  const src = data.sources;
  $("meta").textContent = `Updated ${ago(data.generated_at)} · sheet read ${ago(src.sheet_fetched)}${src.ps_sheet_fetched ? ` · PS Plus sheet read ${ago(src.ps_sheet_fetched)}` : ""} · forecast checked ${ago(src.forecast_checked)} · Steam synced ${ago(src.steam_synced)}${src.psn_synced ? ` · PSN synced ${ago(src.psn_synced)}` : ""} · ${HPW} hours a week`;
  $("how-play").textContent = `Hours to play assume ${HPW} hours a week. Start by is the exit, minus the weeks of play, minus a ${play.buffer_weeks}-week buffer. A green bar fits with room to spare, amber is tight, red won't fit even if you start today.`;

  // ── detail sheet ─────────────────────────────────────────────────
  const dlg = $("detail");
  const open = (r) => {
    $("d-cover").replaceChildren(cover(r, "big"));
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

  const tile = (r) => {
    const b = el("button", `tile ${svc(r)}${r.backup ? " dim" : ""}`);
    b.type = "button";
    b.title = r.game;
    const c = cover(r, "cv");
    c.appendChild(el("span", `odds ${bandCls(r)}`, oddsLabel(r)));
    c.appendChild(el("span", `dot ${svc(r)}`));
    if (r.backup) c.appendChild(el("span", "rib", r.backup));
    b.appendChild(c);
    if (!isClaim(r) && !r.backup) {
      const bar = el("span", `hb ${fit(r)}`), i = el("i");
      i.style.width = r.hours == null ? "100%" : `${Math.min(100, (r.hours / Math.max(1, avail(r))) * 100)}%`;
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

  const remark = (r) => {
    if (r.backup) return [`Rebooked · ${r.backup}`, "m"];
    if (isClaim(r)) return [`Claim by ${fmt(t(r.wave))}`, "gr"];
    if (r.unverified && r.band === "Reported") return ["Unverified report", "m"];
    const u = urgency(r);
    if (u === "Hours unknown") return ["Hours unknown", "m"];
    if (u === "Too late") return [`Short ${Math.round(r.hours - avail(r))} h`, "r"];
    if (u === "Start now") return ["Boarding", "gr blink"];
    if (u.startsWith("Start within")) return ["Board soon", "gr"];
    return ["On time", ""];
  };
  const drawBoard = (rows) => {
    $("board-title").textContent = `DEPARTURES · GAME PASS${one.ps_tier !== "none" ? ` + PS PLUS ${one.ps_tier.toUpperCase()}` : ""}`;
    $("board-date").textContent = new Date(T0).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" }).toUpperCase();
    const tb = $("board").querySelector("tbody");
    tb.replaceChildren(...rows.map((r) => {
      const tr = el("tr", r.backup ? "dim" : "");
      tr.tabIndex = 0;
      tr.appendChild(el("td", "when", fmt(t(r.wave))));
      const g = el("td", "g");
      g.appendChild(cover(r, "cv"));
      g.appendChild(el("span", `dot ${svc(r)}`));
      g.appendChild(el("span", "gn", r.game));
      tr.appendChild(g);
      tr.appendChild(el("td", `via ${svc(r) === "ps" ? "b" : "gr"}`, svc(r) === "ps" ? "PS Plus" : "Game Pass"));
      const st = isClaim(r) ? "Monthly" : r.band === "Confirmed" ? "Confirmed" : r.band === "Reported" ? "Reported" : `${r.band} ${oddsLabel(r)}`;
      tr.appendChild(el("td", r.band === "Confirmed" && !isClaim(r) ? "r" : r.band === "Thin" ? "m" : "", st));
      tr.appendChild(el("td", "num", r.hours == null ? "--" : `${r.hours} h`));
      tr.appendChild(el("td", "by", r.hours == null || isClaim(r) || r.backup || urgency(r) === "Too late" ? "--" : startBy(r) <= T0 ? "Now" : fmt(startBy(r))));
      const [txt, cls] = remark(r);
      tr.appendChild(el("td", `rm ${cls}`, txt));
      tr.addEventListener("click", () => open(r));
      tr.addEventListener("keydown", (e) => { if (e.key === "Enter") open(r); });
      return tr;
    }));
  };

  let view = location.hash === "#board" ? "board" : location.hash === "#shelf" ? "shelf" : store.get("view", "shelf");
  const draw = () => {
    const rows = shown();
    $("count").textContent = `${rows.length} game${rows.length === 1 ? "" : "s"}`;
    $("empty").hidden = rows.length > 0;
    $("shelf").hidden = view !== "shelf" || !rows.length;
    $("board").hidden = view !== "board" || !rows.length;
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
    tb.replaceChildren(...rows.map((r) => { const tr = el("tr"); build(r, tr).forEach((td) => tr.appendChild(td)); return tr; }));
  };
  const td = (text, cls) => el("td", cls, text);
  const gameTd = (r) => {
    const c = td(null, "game");
    if (coverUrl(r)) { const i = el("img", "art"); i.src = r.art; i.alt = ""; i.loading = "lazy"; i.width = 24; i.height = 36; c.appendChild(i); }
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
