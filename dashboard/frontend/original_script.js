
// ============================================================
// State
// ============================================================
const MAX_BARS     = 500;
const MAX_LINE_PTS = 500;

let barIntervalSec = 10;
let selectedTicker = null;
let tickersReady   = false;

// Per-ticker data store
// { ohlc: { current, history[] }, vwap: [], ema: [], markers: [], lastSigDir,
//   latestSnap, latestSig, latestPos, latestRisk }
const TD = {};

function ensureTD(t) {
  if (!TD[t]) TD[t] = {
    ohlc: { current: null, history: [] },
    vwap: [], ema: [], markers: [],
    lastSigDir: null,
    latestSnap: null, latestSig: null, latestPos: null, latestRisk: null,
  };
}

// ============================================================
// Lightweight Charts instances
// ============================================================
let mainChart = null, candleSeries = null, vwapLine = null, emaLine = null;
let pfChart = null, pfEquitySeries = null;
let pfLastTime = 0;

const C = {
  bg:     '#f0f2f5',
  panel:  '#ffffff',
  border: '#e2e8f0',
  text:   '#475569',
  green:  '#16a34a',
  red:    '#dc2626',
  accent: '#2563eb',
  yellow: '#d97706',
};

function initMainChart() {
  const el = document.getElementById('main-chart-container');
  if (!el) return;

  mainChart = LightweightCharts.createChart(el, {
    width:  el.clientWidth,
    height: 330,
    layout: { background: { color: C.bg }, textColor: C.text },
    grid:   { vertLines: { color: C.border }, horzLines: { color: C.border } },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    rightPriceScale: { borderColor: C.border },
    timeScale: { borderColor: C.border, timeVisible: true, secondsVisible: true },
  });

  candleSeries = mainChart.addCandlestickSeries({
    upColor:        C.green, downColor:        C.red,
    borderUpColor:  C.green, borderDownColor:  C.red,
    wickUpColor:    C.green, wickDownColor:    C.red,
  });

  vwapLine = mainChart.addLineSeries({
    color: C.yellow, lineWidth: 1, title: 'VWAP',
    priceLineVisible: false, lastValueVisible: true,
  });

  emaLine = mainChart.addLineSeries({
    color: C.green, lineWidth: 1,
    lineStyle: LightweightCharts.LineStyle.Dashed,
    title: 'EMA', priceLineVisible: false, lastValueVisible: true,
  });

  new ResizeObserver(() => {
    if (mainChart && el.clientWidth > 0)
      mainChart.applyOptions({ width: el.clientWidth });
  }).observe(el);
}

function initPfChart() {
  const el = document.getElementById('pf-chart-container');
  if (!el) return;

  pfChart = LightweightCharts.createChart(el, {
    width:  el.clientWidth,
    height: 80,
    layout: { background: { color: C.panel }, textColor: C.text },
    grid:   { vertLines: { color: 'transparent' }, horzLines: { color: C.border } },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    rightPriceScale: { borderColor: C.border },
    timeScale: { borderColor: C.border, timeVisible: true, secondsVisible: false },
    handleScroll: false, handleScale: false,
  });

  pfEquitySeries = pfChart.addAreaSeries({
    lineColor:   C.accent,
    topColor:    'rgba(79,142,247,0.18)',
    bottomColor: 'rgba(79,142,247,0.02)',
    lineWidth: 1.5,
    title: 'Equity',
    priceLineVisible: false,
    lastValueVisible: true,
  });

  new ResizeObserver(() => {
    if (pfChart && el.clientWidth > 0)
      pfChart.applyOptions({ width: el.clientWidth });
  }).observe(el);
}

// ============================================================
// OHLC bar aggregation
// ============================================================
function currentBarTime() {
  const nowSec = Math.floor(Date.now() / 1000);
  return Math.floor(nowSec / barIntervalSec) * barIntervalSec;
}

function pushOrUpdateLine(arr, t, value) {
  if (arr.length > 0 && arr[arr.length - 1].time === t) {
    arr[arr.length - 1].value = value;
  } else {
    arr.push({ time: t, value });
    if (arr.length > MAX_LINE_PTS) arr.shift();
  }
}

function processTick(ticker, snap) {
  if (!snap || snap.mid_price == null) return;
  const d     = TD[ticker];
  const bTime = currentBarTime();
  const mid   = snap.mid_price;

  // OHLC
  if (!d.ohlc.current || d.ohlc.current.time !== bTime) {
    if (d.ohlc.current) {
      d.ohlc.history.push({ ...d.ohlc.current });
      if (d.ohlc.history.length > MAX_BARS) d.ohlc.history.shift();
    }
    d.ohlc.current = { time: bTime, open: mid, high: mid, low: mid, close: mid };
  } else {
    const c = d.ohlc.current;
    if (mid > c.high) c.high = mid;
    if (mid < c.low)  c.low  = mid;
    c.close = mid;
  }

  // Line overlays
  if (snap.vwap      != null) pushOrUpdateLine(d.vwap, bTime, snap.vwap);
  if (snap.ema_price != null) pushOrUpdateLine(d.ema,  bTime, snap.ema_price);

  // Push live to chart if this is the selected ticker
  if (ticker === selectedTicker && candleSeries) {
    candleSeries.update(d.ohlc.current);
    if (snap.vwap      != null) vwapLine.update({ time: bTime, value: snap.vwap });
    if (snap.ema_price != null) emaLine.update({ time: bTime, value: snap.ema_price });
  }
}

// ============================================================
// Signal markers on chart
// ============================================================
function processSignal(ticker, sig) {
  if (!sig || sig.direction === 'HOLD') return;
  const d = TD[ticker];
  if (sig.direction === d.lastSigDir) return; // no change, skip
  d.lastSigDir = sig.direction;

  const bTime = currentBarTime();
  d.markers.push({
    time:     bTime,
    position: sig.direction === 'BUY' ? 'belowBar' : 'aboveBar',
    color:    sig.direction === 'BUY' ? C.green : C.red,
    shape:    sig.direction === 'BUY' ? 'arrowUp' : 'arrowDown',
    text:     sig.direction,
    size:     1,
  });
  d.markers.sort((a, b) => a.time - b.time);

  if (ticker === selectedTicker && candleSeries)
    candleSeries.setMarkers(d.markers);
}

// ============================================================
// Ticker switching
// ============================================================
function switchTicker(t) {
  if (!t || !TD[t] || !candleSeries) return;
  selectedTicker = t;
  const d = TD[t];

  // Repopulate chart series
  const allBars = [...d.ohlc.history];
  if (d.ohlc.current) allBars.push(d.ohlc.current);
  candleSeries.setData(allBars);
  vwapLine.setData([...d.vwap]);
  emaLine.setData([...d.ema]);
  candleSeries.setMarkers(d.markers);
  mainChart.timeScale().fitContent();

  // Refresh text panels
  if (d.latestSnap) { renderIndicators(d.latestSnap); }
  renderSignal(d.latestSig);
  renderPosition(d.latestPos);
  renderRisk(d.latestRisk);
}

function resetChartData() {
  Object.keys(TD).forEach(t => {
    TD[t].ohlc = { current: null, history: [] };
    TD[t].vwap = []; TD[t].ema = [];
    TD[t].lastSigDir = null; TD[t].markers = [];
  });
  if (candleSeries) { candleSeries.setData([]); candleSeries.setMarkers([]); }
  if (vwapLine)     vwapLine.setData([]);
  if (emaLine)      emaLine.setData([]);
}

// ============================================================
// Portfolio chart
// ============================================================
function updatePfChart(pf) {
  if (!pfEquitySeries || !pf || pf.equity == null) return;
  const t = Math.floor(Date.now() / 1000);
  if (t <= pfLastTime) return;
  pfLastTime = t;
  try { pfEquitySeries.update({ time: t, value: pf.equity }); } catch(_) {}
}

// ============================================================
// Helpers
// ============================================================
const $ = id => document.getElementById(id);
const fmt  = (n, d=2) => n == null ? '—' : Number(n).toFixed(d);
const fmtK = n => n == null ? '—' : '$' + Number(n).toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2});
const pctCls = v => v > 0 ? 'pos' : v < 0 ? 'neg' : 'neu';
const pctStr = v => v == null ? '—' : (v > 0 ? '+' : '') + fmt(v, 2) + '%';

// ============================================================
// Render helpers — all target fixed IDs (single-ticker view)
// ============================================================
function renderBook(snap) {
  const el = $('book-content');
  if (!el || !snap) return;

  const midEl = $('ticker-mid-display');
  if (midEl) midEl.textContent = `$${fmt(snap.mid_price, 4)}  sprd $${fmt(snap.spread, 4)}`;

  const bids = (snap.bids || []).slice(0, 5);
  const asks = (snap.asks || []).slice(0, 5);
  el.innerHTML = `
    <div class="book-grid">
      <div>
        <div class="col-hdr"><span>BID</span><span>SHARES</span></div>
        ${bids.map(([p,s]) => `<div class="book-row bid"><span class="price">$${fmt(p,4)}</span><span class="shares">${s.toLocaleString()}</span></div>`).join('')}
      </div>
      <div>
        <div class="col-hdr"><span>ASK</span><span>SHARES</span></div>
        ${asks.map(([p,s]) => `<div class="book-row ask"><span class="price">$${fmt(p,4)}</span><span class="shares">${s.toLocaleString()}</span></div>`).join('')}
      </div>
    </div>`;
}

function renderIndicators(snap) {
  const el = $('inds-content');
  if (!el || !snap) return;

  const imbal  = snap.order_imbalance ?? 0;
  const clamped = Math.max(-1, Math.min(1, imbal));
  const fillPct  = Math.abs(clamped) * 50;
  const fillLeft = clamped >= 0 ? 50 : (50 - fillPct);
  const fillColor = clamped > 0.1 ? C.green : clamped < -0.1 ? C.red : '#64748b';

  const rows = [
    ['VWAP',   `$${fmt(snap.vwap, 4)}`],
    ['EMA',    `$${fmt(snap.ema_price, 4)}`],
    ['Mom',    fmt(snap.momentum, 4)],
    ['Sprd%',  `${fmt(snap.spread_pct, 3)}%`],
    ['BidVol', (snap.bid_volume  || 0).toLocaleString()],
    ['AskVol', (snap.ask_volume  || 0).toLocaleString()],
  ];

  el.innerHTML = `
    <div class="ind-row">
      <span class="ind-label">Imbal</span>
      <span class="ind-val">${fmt(imbal, 3)}</span>
    </div>
    <div class="imbal-track">
      <div class="imbal-fill" style="left:${fillLeft}%;width:${fillPct}%;background:${fillColor};"></div>
      <div class="imbal-center"></div>
    </div>
    ${rows.map(([l,v]) => `<div class="ind-row"><span class="ind-label">${l}</span><span class="ind-val">${v}</span></div>`).join('')}`;
}

function renderSignal(sig) {
  const el = $('signal-content');
  if (!el) return;
  const dir  = sig?.direction || 'HOLD';
  const conf = sig?.confidence ?? 0;
  const pct  = Math.round(Math.max(0, Math.min(1, conf)) * 100);
  const confColor = conf >= 0.7 ? C.green : conf >= 0.4 ? C.yellow : C.red;
  el.innerHTML = `
    <div class="signal-box">
      <div class="sig-badge sig-${dir}">${dir}</div>
      <div class="sig-conf">conf: ${fmt(conf, 2)}&nbsp;&nbsp;score: ${fmt(sig?.score, 3)}</div>
      <div class="conf-track">
        <div class="conf-fill" style="width:${pct}%;background:${confColor};"></div>
      </div>
      <div class="sig-reason">${sig?.reason || ''}</div>
    </div>`;
}

function renderPosition(pos) {
  const el = $('pos-content');
  if (!el) return;
  if (!pos) { el.innerHTML = `<div class="pos-none">— flat —</div>`; return; }
  const cls = pctCls(pos.unrealized_pnl);
  el.innerHTML = `
    <div class="pos-detail">
      <div class="pos-item"><span class="pi-label">SIDE</span>
        <span class="pi-val" style="color:${pos.side === 'LONG' ? C.green : C.red}">${pos.side}</span></div>
      <div class="pos-item"><span class="pi-label">SHARES</span>  <span class="pi-val">${pos.shares}</span></div>
      <div class="pos-item"><span class="pi-label">ENTRY</span>   <span class="pi-val">$${fmt(pos.entry_price, 4)}</span></div>
      <div class="pos-item"><span class="pi-label">CURRENT</span> <span class="pi-val">$${fmt(pos.current_price, 4)}</span></div>
      <div class="pos-item"><span class="pi-label">UNREAL PNL</span>
        <span class="pi-val ${cls}">$${fmt(pos.unrealized_pnl, 2)}</span></div>
      <div class="pos-item"><span class="pi-label">TRADES</span>  <span class="pi-val">${pos.trade_count}</span></div>
    </div>`;
}

function renderRisk(risk) {
  const el = $('risk-content');
  if (!el || !risk) return;
  el.innerHTML = risk.halted
    ? `<div class="risk-halt">⛔ HALTED</div><div class="risk-reason">${risk.halt_reason}</div>`
    : `<div class="risk-ok">✓ OK &nbsp; dd=${pctStr(risk.drawdown_pct)}</div>`;
}

function renderPortfolio(pf) {
  if (!pf) return;
  const set = (id, v, cls) => {
    const el = $(id); if (!el) return;
    el.textContent = v; el.className = 'value ' + (cls || 'neu');
  };
  set('p-equity', fmtK(pf.equity));
  set('p-cash',   fmtK(pf.cash));
  set('p-upnl',   (pf.unrealized_pnl >= 0 ? '+' : '') + fmtK(pf.unrealized_pnl), pctCls(pf.unrealized_pnl));
  set('p-rpnl',   (pf.realized_pnl   >= 0 ? '+' : '') + fmtK(pf.realized_pnl),   pctCls(pf.realized_pnl));
  set('p-dd',     pctStr(pf.drawdown_pct), pctCls(pf.drawdown_pct));
  set('p-cap',    fmtK(pf.initial_capital));
}

function renderAgents(ticks) {
  const el = $('agent-grid');
  if (!el || !ticks) return;
  el.innerHTML = Object.entries(ticks).map(([name, count]) => `
    <div class="agent-item">
      <span class="a-ticks">${count.toLocaleString()}</span>
      <span class="a-name">${name}</span>
    </div>`).join('');
}

function renderLog(lines) {
  const el = $('log-box');
  if (!el || !lines) return;
  el.innerHTML = lines.map(l => `<div class="log-line">${l}</div>`).join('');
  el.scrollTop = el.scrollHeight;
}

// ============================================================
// WebSocket
// ============================================================
let ws = null;

function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onopen = () => {
    $('status-pill').textContent = '● LIVE';
    $('status-pill').className   = '';
  };
  ws.onclose = () => {
    $('status-pill').textContent = '● DISCONNECTED';
    $('status-pill').className   = 'disconnected';
    setTimeout(connect, 2000);
  };
  ws.onerror = () => ws.close();

  ws.onmessage = evt => {
    try {
      const data    = JSON.parse(evt.data);
      const tickers = data.tickers || [];

      // Populate ticker dropdown once
      if (!tickersReady && tickers.length > 0) {
        tickersReady = true;
        const sel = $('ticker-select');
        sel.innerHTML = '';
        tickers.forEach(t => {
          ensureTD(t);
          const opt = document.createElement('option');
          opt.value = t; opt.textContent = t;
          sel.appendChild(opt);
        });
        sel.disabled   = false;
        selectedTicker = tickers[0];
        sel.value      = selectedTicker;
      }

      tickers.forEach(t => {
        ensureTD(t);
        const ind = (data.indicators || {})[t];
        const raw_snap = (data.snapshots || {})[t];
        const sig  = (data.signals    || {})[t];
        const pos  = (data.positions  || {})[t];
        const risk = (data.risk       || {})[t];
        const d    = TD[t];

        if (ind) { d.latestSnap = ind; processTick(t, ind); }
        if (sig)  { d.latestSig  = sig;  processSignal(t, sig); }
        if (pos)  { d.latestPos  = pos; }
        if (risk) { d.latestRisk = risk; }

        // Update text panels only for the selected ticker
        if (t === selectedTicker) {
          if (ind) { 
            renderIndicators(ind); 
          }
          if (raw_snap) {
            renderBook(raw_snap);
            update3DBook(raw_snap);
          }
          renderSignal(sig  || d.latestSig);
          renderPosition(pos  || d.latestPos);
          renderRisk(risk || d.latestRisk);
        }
      });

      renderPortfolio(data.portfolio);
      updatePfChart(data.portfolio);
      renderAgents(data.agent_ticks);
      renderLog(data.log || []);
      renderInvestments(data.investments || []);
      if (data.portfolio?.equity != null) {
        recordEquity(data.portfolio.equity);
        updateTargetPanel();
      }

    } catch(e) { console.error('WS parse error', e); }
  };
}

// ============================================================
// Selector controls
// ============================================================
document.getElementById('ticker-select').addEventListener('change', e => {
  switchTicker(e.target.value);
});

document.getElementById('bar-select').addEventListener('change', e => {
  barIntervalSec = parseInt(e.target.value, 10);
  resetChartData();
});

// ============================================================
// Clock
// ============================================================
setInterval(() => {
  $('clock').textContent = new Date().toLocaleTimeString('en-US', { hour12: false });
}, 1000);

// ============================================================
// Target Calculator
// ============================================================
let targetEquity   = null;
const equityHistory = [];   // [{time, equity}]
const MAX_EQ_PTS    = 120;  // ~2 minutes of history

function recordEquity(eq) {
  if (eq == null) return;
  const t = Date.now() / 1000;
  equityHistory.push({ time: t, equity: eq });
  if (equityHistory.length > MAX_EQ_PTS) equityHistory.shift();
}

// Linear regression slope in $/sec over the history window
function equitySlope() {
  const n = equityHistory.length;
  if (n < 5) return null;
  let sumX = 0, sumY = 0, sumXY = 0, sumXX = 0;
  const t0 = equityHistory[0].time;
  for (const p of equityHistory) {
    const x = p.time - t0;
    sumX  += x; sumY  += p.equity;
    sumXY += x * p.equity; sumXX += x * x;
  }
  const denom = n * sumXX - sumX * sumX;
  if (Math.abs(denom) < 1e-9) return 0;
  return (n * sumXY - sumX * sumY) / denom;  // $/sec
}

function fmtDuration(secs) {
  if (!isFinite(secs) || secs < 0) return null;
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = Math.floor(secs % 60);
  if (h > 0)  return `${h}h ${m}m`;
  if (m > 0)  return `${m}m ${s}s`;
  return `${s}s`;
}

function calcTarget() {
  const raw = parseFloat($('target-input').value);
  if (isNaN(raw) || raw <= 0) { alert('Enter a valid positive target amount.'); return; }
  targetEquity = raw;
  $('target-set-display').textContent = 'Target: ' + fmtK(targetEquity);
  updateTargetPanel();
}

function updateTargetPanel() {
  const current  = equityHistory.length ? equityHistory[equityHistory.length - 1].equity : null;
  const slope    = equitySlope();   // $/sec
  const etaEl    = $('tc-eta');
  const remEl    = $('tc-remaining');
  const rateEl   = $('tc-rate');
  const toGoEl   = $('tc-to-go');
  const sugEl    = $('tc-suggestions');

  // Rate display (always show, even without target)
  if (slope !== null) {
    const perMin = slope * 60;
    rateEl.textContent  = (perMin >= 0 ? '+' : '') + fmtK(perMin) + '/min';
    rateEl.style.color  = slope >= 0 ? C.green : C.red;
  } else {
    rateEl.textContent = '— gathering data…';
    rateEl.style.color = C.text;
  }

  if (targetEquity === null || current === null) {
    etaEl.textContent = '—';
    remEl.textContent = 'Set a target to begin projection';
    toGoEl.textContent = '— remaining';
    sugEl.innerHTML = '<span class="suggestion-pill neutral">Enter a target equity amount above</span>';
    return;
  }

  const remaining = targetEquity - current;
  toGoEl.textContent = (remaining >= 0 ? fmtK(remaining) : '−' + fmtK(-remaining)) + ' remaining';

  // Build suggestions
  const pills = [];
  const lastRisk  = selectedTicker && TD[selectedTicker] ? TD[selectedTicker].latestRisk  : null;
  const lastSig   = selectedTicker && TD[selectedTicker] ? TD[selectedTicker].latestSig   : null;
  const ddPct     = lastRisk?.drawdown_pct ?? null;

  // Target already hit?
  if (remaining <= 0) {
    etaEl.textContent = 'REACHED';
    etaEl.style.color = C.green;
    remEl.textContent  = 'Target already achieved!';
    pills.push({ cls: 'good', text: 'Target achieved — consider raising your goal' });
  } else if (slope === null) {
    etaEl.textContent  = '—';
    remEl.textContent  = 'Gathering rate data…';
  } else if (slope <= 0) {
    etaEl.textContent  = 'N/A';
    etaEl.style.color  = C.red;
    remEl.textContent  = 'Portfolio declining — target not reachable at current rate';
    pills.push({ cls: 'bad', text: 'Negative growth — engine may be losing money' });
  } else {
    const secsToTarget = remaining / slope;
    const dur = fmtDuration(secsToTarget);
    const eta = new Date(Date.now() + secsToTarget * 1000);
    const etaStr = eta.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit' })
                 + (secsToTarget > 86400 ? ' (+' + Math.floor(secsToTarget / 86400) + 'd)' : '');
    etaEl.textContent  = etaStr;
    etaEl.style.color  = C.accent;
    remEl.textContent  = dur ? `~${dur} from now` : 'almost there';
    if (secsToTarget > 86400)
      pills.push({ cls: 'warn', text: 'Target is 24h+ away — consider a closer milestone' });
    else if (secsToTarget < 300)
      pills.push({ cls: 'good', text: 'Target very close — less than 5 minutes away' });
  }

  // Risk suggestions
  if (lastRisk?.halted) {
    pills.push({ cls: 'bad', text: 'Engine halted — no trades running (' + (lastRisk.halt_reason || 'unknown') + ')' });
  }
  if (ddPct != null && ddPct < -5) {
    pills.push({ cls: 'warn', text: `Drawdown ${Math.abs(ddPct).toFixed(1)}% — consider reducing position risk` });
  } else if (ddPct != null && ddPct < -2) {
    pills.push({ cls: 'warn', text: `Drawdown ${Math.abs(ddPct).toFixed(1)}% — monitor closely` });
  }

  // Signal suggestions
  if (lastSig?.confidence != null) {
    if (lastSig.confidence < 0.35)
      pills.push({ cls: 'warn', text: 'Signal confidence low — engine is uncertain' });
    else if (lastSig.confidence > 0.75 && lastSig.direction !== 'HOLD')
      pills.push({ cls: 'good', text: 'High-confidence ' + lastSig.direction + ' signal active' });
  }

  // Slope suggestions
  if (slope !== null && slope > 0 && remaining > 0) {
    const perHour = slope * 3600;
    if (perHour < 10)
      pills.push({ cls: 'neutral', text: 'Growth rate is slow — engine may need more market activity' });
  }

  if (pills.length === 0)
    pills.push({ cls: 'neutral', text: 'All systems nominal' });

  sugEl.innerHTML = pills.map(p =>
    `<span class="suggestion-pill ${p.cls}">${p.text}</span>`
  ).join('');
}

// ============================================================
// Investment Forecast
// ============================================================
function calcForecast() {
  const amount = parseFloat($('fc-amount').value);
  if (isNaN(amount) || amount <= 0) { alert('Enter a valid positive amount.'); return; }
  const months = parseFloat($('fc-months').value) || 3;
  const slope  = equitySlope();   // $/sec
  const currentEq = equityHistory.length ? equityHistory[equityHistory.length - 1].equity : null;

  if (slope === null || currentEq === null || currentEq <= 0) {
    $('fc-note').textContent = 'Gathering rate data — please wait a few seconds and try again.';
    return;
  }

  const projSecs = months * 30.44 * 86400;
  [
    { id: 'pess', mult: 0.3  },
    { id: 'base', mult: 1.0  },
    { id: 'opti', mult: 2.5  },
  ].forEach(({ id, mult }) => {
    const projEq  = currentEq + slope * mult * projSecs;
    const ratio   = Math.max(0, projEq) / currentEq;
    const projAmt = amount * ratio;
    const roi     = projAmt - amount;
    const roiPct  = (ratio - 1) * 100;

    const valEl = $('fc-' + id + '-val');
    const roiEl = $('fc-' + id + '-roi');
    valEl.textContent = fmtK(Math.max(0, projAmt));
    valEl.className   = 'scenario-value ' + pctCls(roi);
    roiEl.textContent = (roi >= 0 ? '+' : '') + fmtK(roi) + '  (' + (roiPct >= 0 ? '+' : '') + fmt(roiPct, 1) + '%)';
    roiEl.style.color = roi >= 0 ? C.green : C.red;
  });

  const perMin = slope * 60;
  $('fc-note').textContent =
    'Based on current growth rate: ' + (perMin >= 0 ? '+' : '') + fmtK(perMin) + '/min  ·  ' +
    'projecting ' + months + ' month' + (months !== 1 ? 's' : '') + ' forward  ·  ' +
    'not financial advice — simulated engine performance only';
}

// ============================================================
// Live Portfolio Simulator
// ============================================================
async function investNow() {
  const amount = parseFloat($('sim-amount').value);
  if (isNaN(amount) || amount <= 0) { alert('Enter a valid positive amount.'); return; }
  try {
    const res = await fetch('/api/invest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ amount }),
    });
    if (!res.ok) { const e = await res.json(); alert(e.error || 'Failed to invest'); return; }
    $('sim-amount').value = '';
  } catch (e) { alert('Network error: ' + e.message); }
}

async function closeInvestment(id) {
  try {
    await fetch('/api/invest/' + id, { method: 'DELETE' });
  } catch (e) { console.error('Failed to close investment', e); }
}

function renderInvestments(invs) {
  const wrap = $('inv-table-wrap');
  if (!wrap) return;
  if (!invs || invs.length === 0) {
    wrap.innerHTML = '<div id="inv-empty">— no active investments — enter an amount above to simulate —</div>';
    return;
  }
  const now = Date.now() / 1000;
  const rows = invs.map((inv, i) => {
    const roiCls = inv.roi_pct >= 0 ? 'pos' : 'neg';
    const age    = Math.round(now - inv.invested_at);
    const ageStr = age < 60 ? age + 's' : Math.floor(age / 60) + 'm ' + (age % 60) + 's';
    return `<tr>
      <td>#${i + 1} <span style="font-size:10px;color:var(--muted);">${ageStr} ago</span></td>
      <td>${fmtK(inv.amount)}</td>
      <td style="color:var(--accent);">${fmtK(inv.current_value)}</td>
      <td class="${roiCls}">${inv.pnl >= 0 ? '+' : ''}${fmtK(inv.pnl)}</td>
      <td class="${roiCls}">${inv.roi_pct >= 0 ? '+' : ''}${fmt(inv.roi_pct, 2)}%</td>
      <td><button class="close-inv-btn" onclick="closeInvestment('${inv.id}')">×</button></td>
    </tr>`;
  }).join('');
  wrap.innerHTML = `
    <table class="inv-table">
      <thead><tr>
        <th style="text-align:left;">Investment</th>
        <th>Invested</th>
        <th>Current Value</th>
        <th>P&amp;L</th>
        <th>ROI</th>
        <th></th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

// ============================================================
// Tab / page switching
// ============================================================
function switchPage(page) {
  document.querySelectorAll('.page-section').forEach(el => {
    el.classList.toggle('visible', el.dataset.page === page);
  });
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.textContent.trim().toLowerCase() === page ||
      btn.getAttribute('onclick').includes("'" + page + "'"));
  });
  // Charts need resize after becoming visible
  if (page === 'market' && mainChart) {
    requestAnimationFrame(() => {
      const el = document.getElementById('main-chart-container');
      if (el) mainChart.applyOptions({ width: el.clientWidth });
      if (selectedTicker) switchTicker(selectedTicker);
    });
  }
  if (page === 'overview' && pfChart) {
    requestAnimationFrame(() => {
      const el = document.getElementById('pf-chart-container');
      if (el) pfChart.applyOptions({ width: el.clientWidth });
    });
  }
  if (page === '3dbook' && renderer) {
    requestAnimationFrame(() => {
      const el = document.getElementById('three-container');
      if (el && el.clientWidth > 0) {
        camera.aspect = el.clientWidth / el.clientHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(el.clientWidth, el.clientHeight);
      }
    });
  }
}

// ============================================================
// 3D Order Book Visualization
// ============================================================
let scene, camera, renderer, bookMesh, controls;
const BOOK_HISTORY_LEN = 50;
const MAX_LEVELS = 10; // 5 bids, 5 asks

function init3DBook() {
  const container = document.getElementById('three-container');
  if (!container) return;

  scene = new THREE.Scene();
  // Deep dark premium background
  scene.background = new THREE.Color('#0b0e14');
  scene.fog = new THREE.Fog('#0b0e14', 40, 100);

  const width = container.clientWidth || window.innerWidth || 800;
  const height = container.clientHeight || 500;

  camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000);
  camera.position.set(20, 30, 45); // More isometric and dynamic angle

  renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
  renderer.setSize(width, height);
  renderer.setPixelRatio(window.devicePixelRatio); // Crisp rendering
  container.appendChild(renderer.domElement);

  // OrbitControls for interactivity
  controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.05;
  controls.maxPolarAngle = Math.PI / 2 - 0.05; // Don't go below ground
  controls.target.set(0, 5, 0);

  // Lighting - dramatic lighting setup
  const ambientLight = new THREE.AmbientLight(0xffffff, 0.4);
  scene.add(ambientLight);
  
  const dirLight = new THREE.DirectionalLight(0xffffff, 0.8);
  dirLight.position.set(20, 40, 20);
  scene.add(dirLight);

  const blueLight = new THREE.PointLight(0x4466ff, 1, 100);
  blueLight.position.set(-20, 10, -20);
  scene.add(blueLight);

  // Grid Helper to act as a floor
  const gridHelper = new THREE.GridHelper(100, 50, 0x334455, 0x112233);
  gridHelper.position.y = 0;
  scene.add(gridHelper);

  // Book material and geometry (InstancedMesh for performance)
  // Use cylinder for a sleeker look
  const geometry = new THREE.BoxGeometry(0.85, 1, 0.85);
  // Give it a slightly metallic and shiny look
  const material = new THREE.MeshStandardMaterial({ 
    color: 0xffffff, 
    roughness: 0.2,
    metalness: 0.5,
    transparent: true, 
    opacity: 0.85 
  });
  
  bookMesh = new THREE.InstancedMesh(geometry, material, BOOK_HISTORY_LEN * MAX_LEVELS);
  bookMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  
  const dummy = new THREE.Object3D();
  const defaultColor = new THREE.Color(0xffffff);
  dummy.position.set(0, 0, 1000);
  dummy.scale.set(0, 0, 0);
  dummy.updateMatrix();
  for(let i=0; i<BOOK_HISTORY_LEN * MAX_LEVELS; i++) {
    bookMesh.setMatrixAt(i, dummy.matrix);
    bookMesh.setColorAt(i, defaultColor);
  }
  bookMesh.instanceMatrix.needsUpdate = true;
  if(bookMesh.instanceColor) bookMesh.instanceColor.needsUpdate = true;
  
  scene.add(bookMesh);

  // Resize handler
  window.addEventListener('resize', () => {
    if (container.clientWidth > 0) {
      camera.aspect = container.clientWidth / container.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(container.clientWidth, container.clientHeight);
    }
  });

  animate3D();
}

function animate3D() {
  requestAnimationFrame(animate3D);
  if (controls) controls.update(); // Required if damping is enabled
  if (renderer && scene && camera) {
    renderer.render(scene, camera);
  }
}

// Store historical snapshots for the 3D view
const bookHistory = [];

function update3DBook(snap) {
  if (!snap || !bookMesh) return;
  
  // Throttle updates to ~10fps to avoid excessive mesh rebuilding overhead
  // while keeping it visually active
  const now = Date.now();
  if (update3DBook.lastUpdate && (now - update3DBook.lastUpdate < 100)) return;
  update3DBook.lastUpdate = now;

  bookHistory.push(snap);
  if (bookHistory.length > BOOK_HISTORY_LEN) bookHistory.shift();

  let maxVol = 1; // Prevent div by zero
  bookHistory.forEach(s => {
    (s.bids || []).forEach(b => { if (b[1] > maxVol) maxVol = b[1]; });
    (s.asks || []).forEach(a => { if (a[1] > maxVol) maxVol = a[1]; });
  });

  const dummy = new THREE.Object3D();
  const color = new THREE.Color();
  
  let i = 0;
  // Iterate history from oldest to newest (z-axis)
  for (let t = 0; t < bookHistory.length; t++) {
    const s = bookHistory[t];
    const bids = (s.bids || []).slice(0, 5);
    const asks = (s.asks || []).slice(0, 5);
    
    // Z-position: newer = closer to 0, older = further back
    const z = (BOOK_HISTORY_LEN - t) - (BOOK_HISTORY_LEN / 2);

    // Bids (left side, negative X)
    bids.forEach((b, idx) => {
      const vol = b[1];
      const h = Math.max(0.1, (vol / maxVol) * 15);
      
      // X-position: closer to mid = closer to 0
      const x = -(5 - idx) * 1.5;
      
      dummy.position.set(x, h/2, z);
      dummy.scale.set(1, h, 1);
      dummy.updateMatrix();
      bookMesh.setMatrixAt(i, dummy.matrix);
      color.setHex(0x00ff88); // Neon Green
      bookMesh.setColorAt(i, color);
      i++;
    });

    // Asks (right side, positive X)
    asks.forEach((a, idx) => {
      const vol = a[1];
      const h = Math.max(0.1, (vol / maxVol) * 15);
      
      const x = (idx + 1) * 1.5;
      
      dummy.position.set(x, h/2, z);
      dummy.scale.set(1, h, 1);
      dummy.updateMatrix();
      bookMesh.setMatrixAt(i, dummy.matrix);
      color.setHex(0xff3355); // Neon Red
      bookMesh.setColorAt(i, color);
      i++;
    });
  }

  // Hide unused instances
  for (; i < BOOK_HISTORY_LEN * MAX_LEVELS; i++) {
    dummy.position.set(0, 0, 1000);
    dummy.scale.set(0, 0, 0);
    dummy.updateMatrix();
    bookMesh.setMatrixAt(i, dummy.matrix);
  }

  bookMesh.instanceMatrix.needsUpdate = true;
  if (bookMesh.instanceColor) bookMesh.instanceColor.needsUpdate = true;
}


// ============================================================
// Bootstrap
// ============================================================
initMainChart();
initPfChart();
init3DBook();
connect();
