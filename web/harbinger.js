// Harbinger page: reads /data.json and draws every section. Data is untrusted text:
// everything goes in through textContent, never innerHTML.
(async () => {
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  };
  const hrs = (h) => (h === null || h === undefined ? "?" : String(h));
  const ago = (iso) => {
    if (!iso) return "never";
    const s = (Date.now() - new Date(iso)) / 1000;
    if (s < 3600) return `${Math.max(1, Math.round(s / 60))}m ago`;
    if (s < 86400) return `${Math.round(s / 3600)}h ago`;
    const d = Math.round(s / 86400);
    return d === 1 ? "yesterday" : `${d} days ago`;
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

  // header + KPIs
  const s = data.summary;
  $("takeaway").textContent = s.takeaway;
  const src = data.sources;
  $("meta").textContent = `Updated ${ago(data.generated_at)} · sheet read ${ago(src.sheet_fetched)}${src.ps_sheet_fetched ? ` · PS Plus sheet read ${ago(src.ps_sheet_fetched)}` : ""} · forecast checked ${ago(src.forecast_checked)} · Steam synced ${ago(src.steam_synced)}${src.psn_synced ? ` · PSN synced ${ago(src.psn_synced)}` : ""}`;
  document.querySelectorAll(".kpi .n").forEach((n) => { const v = s[n.dataset.k]; n.textContent = v === "" || v === undefined ? "–" : v; });
  $("kpi-wave").textContent = `days to the ${s.next_wave} wave`;

  const fill = (tbodyId, rows, build) => {
    const tb = document.querySelector(`#${tbodyId} tbody`);
    tb.replaceChildren(...rows.map((r) => { const tr = el("tr"); build(r, tr).forEach((td) => tr.appendChild(td)); return tr; }));
  };
  const td = (text, cls) => el("td", cls, text);
  // a game's name cell, with its cover when we have one (path comes from our own data.json)
  const gameTd = (r) => {
    const c = td(null, "game");
    if (/^\/art\/[0-9a-f]{16}\.(jpg|png)$/.test(r.art || "")) {
      const i = el("img", "art"); i.src = r.art; i.alt = ""; i.loading = "lazy"; i.width = 32; i.height = 32;
      c.appendChild(i);
    }
    c.appendChild(document.createTextNode(r.game));
    return c;
  };
  const urgCls = (u) => (u === "Start now" || /^Claim/.test(u || "") ? "urg-now" : u === "Too late" ? "urg-late" : "");

  // confirmed
  const verdictCls = (v) => (v === "Doable" || v === "Tight" ? v : v === "Too late for 100%" ? "late" : "quiet");
  fill("t-conf", data.confirmed, (r) => {
    const g = gameTd(r);
    if (!r.verified) g.appendChild(el("span", "chip unv", "unverified"));
    const v = el("td"); v.appendChild(el("span", `chip ${verdictCls(r.verdict)}`, r.verdict));
    return [g, td(r.wave_label, "nowrap"), td(hrs(r.hours), "num"), v, td(r.platform, "nowrap"),
      td(r.progress ? `${r.note} · ${r.progress}` : r.note, "why")];
  });

  // only on one service: not on Steam, not on the other service
  const one = data.one_service;
  if (one) {
    const tierNote = one.ps_tier === "none"
      ? "Set your PS Plus tier under [playstation] in config.local.toml to add PlayStation."
      : `Game Pass on console and PS Plus ${one.ps_tier}.`;
    $("one-note").textContent = `Games you can only play through one subscription. ${tierNote} Left out: ${one.skipped_owned} you own (Steam, PlayStation or disc), ${one.skipped_both} on both services${one.skipped_claimed ? `, ${one.skipped_claimed} PS Plus games you already claimed` : ""}${one.skipped_finished ? `, ${one.skipped_finished} you finished (every trophy)` : ""}. Confirmed and claim deadlines come first, then Likely, Possible and Thin, each soonest first. PS Plus leaves on the third Monday of the month.`;
    const drawOne = () => {
      const q = $("oq").value.trim().toLowerCase(), fs = $("os").value, fb = $("ob").value;
      const rows = one.rows.filter((r) => (!q || r.game.toLowerCase().includes(q)) && (!fs || r.service.startsWith(fs))
        && (!fb || (fb === "-" ? !r.band : r.band === fb)));
      $("ocount").textContent = `${rows.length} of ${one.rows.length}`;
      fill("t-one", rows.slice(0, 300), (r, tr) => {
        if (r.band === "Thin" || !r.band) tr.className = "thin";
        return [gameTd(r), td(r.service, "nowrap"), td(r.leaves, "nowrap"), td(r.odds, r.band ? `band-${r.band}` : ""),
          td(hrs(r.hours), "num"), td(r.action, `nowrap ${urgCls(r.action)}`), td(r.progress || "", "why"), td(r.why, "why")];
      });
    };
    ["oq", "os", "ob"].forEach((id) => $(id).addEventListener("input", drawOne));
    drawOne();
  } else $("one").hidden = true;

  // waves chart: stacked bars, hand-drawn SVG
  const drawChart = () => {
    const host = $("chart"), tip = $("tip");
    host.querySelectorAll("svg").forEach((n) => n.remove());
    const W = Math.max(280, host.clientWidth), H = 230, m = { l: 30, r: 8, t: 10, b: 26 };
    const bands = ["Confirmed", "Likely", "Possible", "Thin"];
    const fills = { Confirmed: "var(--ink)", Likely: "var(--likely)", Possible: "var(--possible)", Thin: "url(#hatch)" };
    const rows = data.waves;
    const max = Math.max(1, ...rows.map((w) => bands.reduce((a, b) => a + w[b], 0)));
    const step = max <= 5 ? 1 : max <= 12 ? 2 : max <= 30 ? 5 : 10;
    const top = Math.ceil(max / step) * step;
    const y = (v) => H - m.b - (v / top) * (H - m.t - m.b);
    const slot = (W - m.l - m.r) / rows.length, bw = Math.min(70, slot * 0.6);
    const NS = "http://www.w3.org/2000/svg";
    const mk = (tag, attrs) => { const n = document.createElementNS(NS, tag); for (const k in attrs) n.setAttribute(k, attrs[k]); return n; };
    const svg = mk("svg", { width: "100%", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Games per removal wave by evidence band" });
    const defs = mk("defs", {}), pat = mk("pattern", { id: "hatch", width: 6, height: 6, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" });
    pat.appendChild(mk("rect", { width: 6, height: 6, fill: "var(--card)" }));
    pat.appendChild(mk("rect", { width: 3, height: 6, fill: "var(--thin)" }));
    defs.appendChild(pat); svg.appendChild(defs);
    for (let v = 0; v <= top; v += step) {
      svg.appendChild(mk("line", { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), stroke: "var(--rule)" }));
      const t = mk("text", { x: m.l - 6, y: y(v) + 4, "text-anchor": "end" }); t.textContent = v; svg.appendChild(t);
    }
    rows.forEach((w, i) => {
      const x = m.l + slot * i + (slot - bw) / 2;
      let acc = 0;
      bands.forEach((b) => {
        const n = w[b]; if (!n) return;
        const y1 = y(acc + n), y0 = y(acc); acc += n;
        const rect = mk("rect", { x, y: y1, width: bw, height: Math.max(0, y0 - y1 - 1), rx: 2, fill: fills[b] });
        if (b === "Thin") rect.setAttribute("stroke", "var(--thin)");
        rect.addEventListener("mousemove", (ev) => {
          const box = host.getBoundingClientRect();
          tip.replaceChildren(el("b", null, `${w.label} · ${b}: ${n}`), el("span", null, w.games[b].slice(0, 12).join(", ") + (w.games[b].length > 12 ? "…" : "")));
          tip.style.display = "block";
          tip.style.left = Math.min(ev.clientX - box.left + 12, box.width - tip.offsetWidth - 4) + "px";
          tip.style.top = Math.max(0, ev.clientY - box.top - tip.offsetHeight - 8) + "px";
        });
        rect.addEventListener("mouseleave", () => { tip.style.display = "none"; });
        svg.appendChild(rect);
      });
      const t = mk("text", { x: x + bw / 2, y: H - 8, "text-anchor": "middle" }); t.textContent = w.label; svg.appendChild(t);
    });
    host.insertBefore(svg, tip);
  };
  drawChart();
  let rt; addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(drawChart, 150); });

  // watchlist
  const wsel = $("fw");
  data.waves.forEach((w) => wsel.add(new Option(w.label, w.wave)));
  const drawWatch = () => {
    const q = $("q").value.trim().toLowerCase(), fb = $("fb").value, fw = wsel.value, fu = $("fu").value;
    const rows = data.watchlist.filter((r) => (!q || r.game.toLowerCase().includes(q)) && (!fb || r.band === fb) && (!fw || r.wave === fw) && (!fu || r.urgency === fu));
    $("wcount").textContent = `${rows.length} of ${data.watchlist.length}`;
    fill("t-watch", rows, (r, tr) => {
      if (r.band === "Thin") tr.className = "thin";
      const ev = el("td", "ev");
      const bar = el("i", `bar ${r.band}`); bar.style.width = `calc(${Math.round(r.p * 100)}% - 8px)`;
      ev.appendChild(bar); ev.appendChild(el("span", null, r.evidence));
      if (r.delta === "new") ev.appendChild(el("span", "delta", "new"));
      else if (r.delta) ev.appendChild(el("span", `delta ${r.delta > 0 ? "up" : "down"}`, `${r.delta > 0 ? "▲" : "▼"}${Math.abs(r.delta)}`));
      return [gameTd(r), td(r.wave_label, "nowrap"), td(r.notice, "nowrap"), ev, td(r.band, `band-${r.band}`),
        td(hrs(r.hours), "num"), td(r.start_by, "nowrap"), td(r.urgency, `nowrap ${urgCls(r.urgency)}`), td(r.tier, "nowrap"), td(r.why, "why")];
    });
  };
  ["q", "fb", "fw", "fu"].forEach((id) => $(id).addEventListener("input", drawWatch));
  drawWatch();

  // owned elsewhere
  if (data.owned.length) {
    $("owned").hidden = false;
    fill("t-owned", data.owned, (r) => [gameTd(r), td(r.where, "nowrap"), td(hrs(r.hours), "num"), td(r.progress, "why")]);
  }

  fill("t-queue", data.queue, (r) => [gameTd(r), td(r.state, "nowrap"), td(r.next_check, "nowrap"), td(r.odds, "nowrap"), td(r.note, "why")]);
  if (!data.queue.length) {
    $("queue").querySelector(".note").textContent = "No watched games yet. List the Game Pass games you're playing or plan to play under [queue] in config.local.toml (config.local.example.toml explains it), and they show up here with the next date each could leave.";
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
