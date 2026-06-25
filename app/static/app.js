/* Sentinel dashboard — live WebSocket client + Chart.js rendering. */
(() => {
  "use strict";

  const MAX_POINTS = 90;
  const COLORS = {
    latency: "#36b3ff", error: "#f5b651", traffic: "#38e0c0",
    ema: "rgba(215,226,238,.45)", anomaly: "#ff5470",
  };
  let cfg = { iforest_threshold: 0.68, zscore_threshold: 3.5 };

  const $ = (id) => document.getElementById(id);
  const fmt = (n, d = 0) =>
    n == null || Number.isNaN(n) ? "–" :
    Number(n).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });

  /* ---------- charts ---------- */
  Chart.defaults.color = "#54616f";
  Chart.defaults.font.family = "JetBrains Mono, ui-monospace, monospace";
  Chart.defaults.font.size = 10;

  function makeChart(canvasId, color) {
    return new Chart($(canvasId).getContext("2d"), {
      type: "line",
      data: {
        labels: [],
        datasets: [
          {
            data: [], borderColor: color, borderWidth: 1.6, tension: 0.32,
            fill: { target: "origin", above: hexFade(color) },
            pointRadius: [], pointBackgroundColor: [], pointBorderColor: [],
            pointBorderWidth: 1.5, pointHoverRadius: 5,
          },
          {
            data: [], borderColor: COLORS.ema, borderWidth: 1, borderDash: [4, 4],
            tension: 0.32, pointRadius: 0, fill: false,
          },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        interaction: { intersect: false, mode: "index" },
        scales: {
          x: { display: false, grid: { display: false } },
          y: {
            grid: { color: "rgba(28,39,52,.6)" }, ticks: { maxTicksLimit: 5, padding: 6 },
            border: { display: false },
          },
        },
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
      },
    });
  }

  function hexFade(hex) {
    const r = parseInt(hex.slice(1, 3), 16), g = parseInt(hex.slice(3, 5), 16), b = parseInt(hex.slice(5, 7), 16);
    return `rgba(${r},${g},${b},.07)`;
  }

  const charts = {
    latency_ms: makeChart("chartLatency", COLORS.latency),
    error_rate: makeChart("chartError", COLORS.error),
    traffic_rps: makeChart("chartTraffic", COLORS.traffic),
  };
  const SCALE = { latency_ms: 1, error_rate: 100, traffic_rps: 1 }; // error shown as %
  let dirty = false;

  function pushPoint(metric, value, ema, isAnom) {
    const c = charts[metric];
    const v = value * SCALE[metric];
    const ds = c.data.datasets[0];
    c.data.labels.push("");
    ds.data.push(v);
    ds.pointRadius.push(isAnom ? 4 : 0);
    ds.pointBackgroundColor.push(COLORS.anomaly);
    ds.pointBorderColor.push("#1b0d12");
    c.data.datasets[1].data.push(ema * SCALE[metric]);
    if (ds.data.length > MAX_POINTS) {
      c.data.labels.shift(); ds.data.shift();
      ds.pointRadius.shift(); ds.pointBackgroundColor.shift(); ds.pointBorderColor.shift();
      c.data.datasets[1].data.shift();
    }
    dirty = true;
  }

  function renderLoop() {
    if (dirty) {
      for (const m in charts) charts[m].update("none");
      dirty = false;
    }
    requestAnimationFrame(renderLoop);
  }
  requestAnimationFrame(renderLoop);

  /* ---------- stat rows ---------- */
  const STAT_EL = { latency_ms: "statLatency", error_rate: "statError", traffic_rps: "statTraffic" };
  function renderStats(stats) {
    for (const s of stats) {
      const el = $(STAT_EL[s.name]);
      if (!el) continue;
      const pct = s.name === "error_rate";
      const scale = pct ? 100 : 1;
      const u = pct ? "%" : "";
      const zHot = Math.abs(s.zscore) >= cfg.zscore_threshold ? "z-hot" : "";
      el.innerHTML =
        `p50 <b>${fmt(s.p50 * scale, pct ? 2 : 0)}${u}</b>` +
        `p95 <b>${fmt(s.p95 * scale, pct ? 2 : 0)}${u}</b>` +
        `p99 <b>${fmt(s.p99 * scale, pct ? 2 : 0)}${u}</b>` +
        `ema <b>${fmt(s.ema * scale, pct ? 2 : 0)}${u}</b>` +
        `<span class="${zHot}">z <b class="${zHot}">${fmt(s.zscore, 1)}σ</b></span>`;
    }
  }

  /* ---------- KPIs ---------- */
  let lastEvents = null, lastT = performance.now(), rateEMA = 0;
  function renderKpis(r) {
    $("kpiEvents").textContent = fmt(r.events_processed);
    $("kpiAnoms").textContent = fmt(r.anomalies_total);
    const arate = r.events_processed ? (r.anomalies_total / r.events_processed) * 100 : 0;
    $("kpiAnomRate").textContent = `${fmt(arate, 1)}% of stream`;
    $("kpiUnique").textContent = fmt(r.cardinality.unique_total);
    $("kpiUniqueWin").textContent = `window: ${fmt(r.cardinality.unique_window)}`;

    const now = performance.now();
    if (lastEvents === null) {            // seed without emitting a bogus first rate
      lastEvents = r.events_processed; lastT = now;
    } else if (now - lastT > 0.5) {
      const inst = (r.events_processed - lastEvents) / ((now - lastT) / 1000);
      rateEMA = rateEMA ? rateEMA * 0.7 + inst * 0.3 : inst;
      $("kpiRate").textContent = `${fmt(rateEMA, 1)} /s`;
      lastEvents = r.events_processed; lastT = now;
    }

    const iso = r.isolation_score || 0;
    $("isoVal").textContent = fmt(iso, 2);
    $("isoFill").style.width = `${Math.min(100, iso * 100)}%`;
    const alarm = iso >= cfg.iforest_threshold;
    $("isoState").textContent = alarm ? "OUTLIER" : "nominal";
    document.querySelector(".kpi-gauge").classList.toggle("alarm", alarm);
  }

  /* ---------- top endpoints ---------- */
  function renderEndpoints(eps) {
    const el = $("topEndpoints");
    if (!eps || !eps.length) return;
    const max = Math.max(...eps.map((e) => e.fraction), 0.0001);
    el.innerHTML = eps.map((e) => {
      const pctTxt = (e.fraction * 100).toFixed(1);
      const hot = e.fraction >= 0.45 ? "hot" : "";
      return `<li class="${hot}">
        <span class="ep-name">${e.key}</span>
        <span class="ep-count">${pctTxt}% · ${fmt(e.count)}</span>
        <span class="track"><i style="width:${(e.fraction / max) * 100}%"></i></span>
      </li>`;
    }).join("");
  }

  /* ---------- alerts ---------- */
  const alertsEl = $("alerts");
  let alertTotal = 0, hasAlerts = false;
  function addAlert(a, animate = true) {
    if (!hasAlerts) { alertsEl.innerHTML = ""; hasAlerts = true; }
    const li = document.createElement("li");
    li.className = `alert sev-${a.severity}` + (animate ? "" : " no-anim");
    const t = new Date((a.timestamp || Date.now() / 1000) * 1000).toLocaleTimeString();
    li.innerHTML =
      `<div class="alert-top">
         <span class="badge sev-${a.severity}">${a.severity}</span>
         <span class="alert-method">${a.method}</span>
       </div>
       <div class="alert-msg">${a.message}</div>
       <div class="alert-time">${t}</div>`;
    alertsEl.prepend(li);
    while (alertsEl.children.length > 40) alertsEl.removeChild(alertsEl.lastChild);
  }
  function bumpAlerts(n) {
    alertTotal += n;
    $("alertCount").textContent = fmt(alertTotal);
  }

  /* ---------- message handling ---------- */
  function handleResult(r) {
    for (const s of r.stats) {
      const ev = r.event[s.name];
      pushPoint(s.name, ev, s.ema, r.is_anomaly);
    }
    renderStats(r.stats);
    renderKpis(r);
    renderEndpoints(r.top_endpoints);
    if (r.anomalies && r.anomalies.length) {
      r.anomalies.forEach((a) => addAlert(a));
      bumpAlerts(r.anomalies.length);
      if (r.severity === "critical" || r.severity === "high") {
        document.body.classList.remove("flash");
        void document.body.offsetWidth;
        document.body.classList.add("flash");
      }
    }
  }

  function hydrate(snap) {
    if (snap.history) {
      snap.history.forEach((h) => {
        pushPoint("latency_ms", h.latency_ms, h.latency_ms, false);
        pushPoint("error_rate", h.error_rate, h.error_rate, false);
        pushPoint("traffic_rps", h.traffic_rps, h.traffic_rps, false);
      });
    }
    if (snap.alerts) {
      snap.alerts.slice().reverse().forEach((a) => addAlert(a, false));
      bumpAlerts(snap.alerts.length);
    }
    if (snap.latest) handleResult(snap.latest);
    if (snap.snapshot) $("uptime").textContent = `uptime ${fmt(snap.snapshot.uptime_seconds)}s`;
  }

  /* ---------- websocket ---------- */
  function setConn(state, label) {
    const c = $("conn");
    c.className = "conn " + state;
    $("connLabel").textContent = label;
  }

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onopen = () => setConn("live", "streaming");
    ws.onclose = () => { setConn("down", "reconnecting…"); setTimeout(connect, 1500); };
    ws.onerror = () => ws.close();
    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      if (msg.type === "snapshot") hydrate(msg);
      else if (msg.type === "update") handleResult(msg.result);
    };
  }

  fetch("/api/state").then((r) => r.json()).then((d) => {
    if (d.config) cfg = { ...cfg, ...d.config };
    $("busLabel").textContent = `${d.config.bus} bus`;
  }).catch(() => {});

  setConn("", "connecting…");
  connect();
})();
