// botsim-v2 UI
//
// WebSocket: ws://<host>/ws/ui  (same host:port as the page)
// Receives:
//   {"type": "state",     "positions": {id: {x, y, theta, last_seen}}}
//   {"type": "log",       "message": "..."}
// REST calls against the same origin.

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const state = {
  robots:    {},   // id → {x, y, theta, last_seen, online}
  algorithm: null, // last algorithm sent
};

// ---------------------------------------------------------------------------
// WebSocket
// ---------------------------------------------------------------------------

let ws = null;
let wsReconnectTimer = null;

function connectWS() {
  const url = `ws://${location.host}/ws/ui`;
  ws = new WebSocket(url);

  ws.onopen = () => {
    setWsStatus(true);
    log("Connected to broker", "info");
  };

  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === "state") {
      mergePositions(msg.positions);
      renderFleet();
      renderMap();
    } else if (msg.type === "log") {
      log(msg.message);
    }
  };

  ws.onclose = () => {
    setWsStatus(false);
    log("Disconnected — reconnecting in 3s…", "err");
    wsReconnectTimer = setTimeout(connectWS, 3000);
  };

  ws.onerror = () => ws.close();
}

function setWsStatus(online) {
  const el = document.getElementById("ws-status");
  el.textContent = online ? "connected" : "disconnected";
  el.className = `badge ${online ? "badge-ws-ok" : "badge-offline"}`;
}

// ---------------------------------------------------------------------------
// Position state
// ---------------------------------------------------------------------------

function mergePositions(positions) {
  // Mark all currently-tracked robots as offline first, then re-mark online
  for (const id of Object.keys(state.robots)) {
    state.robots[id].online = false;
  }
  for (const [id, pos] of Object.entries(positions)) {
    state.robots[id] = { ...pos, online: true };
  }
}

// ---------------------------------------------------------------------------
// Fleet table
//
// Two-phase rendering to avoid destroying buttons on every position update:
//   buildFleetRows()  — builds rows once (called on init and fleet config change)
//   updateFleetCells() — updates only status/position cells in-place (called on state message)
// ---------------------------------------------------------------------------

function buildFleetRows() {
  const tbody = document.querySelector("#fleet-table tbody");
  tbody.innerHTML = "";
  for (const r of fleetConfig) {
    const tr = document.createElement("tr");
    tr.id = `row-${r.id}`;
    tr.innerHTML = `
      <td>${r.id}</td>
      <td id="status-${r.id}"><span class="badge badge-offline">offline</span></td>
      <td id="pos-${r.id}" class="pos-cell">—</td>
      <td class="action-btns">
        <button class="btn-sm btn-neutral" onclick="robotAction('${r.id}','deploy')">Deploy</button>
        <button class="btn-sm"            onclick="robotAction('${r.id}','start')">Start</button>
        <button class="btn-sm btn-danger" onclick="robotAction('${r.id}','stop')">Stop</button>
      </td>
    `;
    tbody.appendChild(tr);
  }
}

function updateFleetCells() {
  for (const r of fleetConfig) {
    const pos    = state.robots[r.id];
    const online = pos ? pos.online : false;

    const statusEl = document.getElementById(`status-${r.id}`);
    const posEl    = document.getElementById(`pos-${r.id}`);
    if (!statusEl || !posEl) continue;

    statusEl.innerHTML = `<span class="badge ${online ? "badge-online" : "badge-offline"}">${online ? "online" : "offline"}</span>`;
    posEl.textContent  = pos ? `${pos.x.toFixed(2)}, ${pos.y.toFixed(2)}, ${pos.theta.toFixed(2)}` : "—";
  }
}

// Keep renderFleet as a convenience alias used in init
function renderFleet() { updateFleetCells(); }

// ---------------------------------------------------------------------------
// Map canvas
// ---------------------------------------------------------------------------

const WORLD_RANGE = 2.5;  // ±2.5 m from origin
const ROBOT_COLORS = ["#6366f1", "#f59e0b", "#10b981", "#ef4444", "#3b82f6", "#8b5cf6"];

function renderMap() {
  const canvas = document.getElementById("map");
  const ctx    = canvas.getContext("2d");
  const W = canvas.width;
  const H = canvas.height;
  const scale = W / (2 * WORLD_RANGE);  // px per metre

  ctx.clearRect(0, 0, W, H);

  // Background grid
  drawGrid(ctx, W, H, scale);

  // Formation targets (pentagon vertices) if pentagon algorithm is active
  if (state.algorithm === "pentagon") {
    drawPentagonTargets(ctx, W, H, scale);
  }

  // Robots
  const robots = Object.entries(state.robots).filter(([, p]) => p.online);
  robots.forEach(([id, pos], i) => {
    const cx = W / 2 + pos.x * scale;
    const cy = H / 2 - pos.y * scale;
    const color = ROBOT_COLORS[i % ROBOT_COLORS.length];

    // Heading line
    const headLen = 0.18 * scale;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + headLen * Math.cos(pos.theta), cy - headLen * Math.sin(pos.theta));
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.stroke();

    // Robot dot
    ctx.beginPath();
    ctx.arc(cx, cy, 7, 0, 2 * Math.PI);
    ctx.fillStyle = color;
    ctx.fill();

    // Label
    ctx.fillStyle = "#18181b";
    ctx.font = "bold 11px system-ui";
    ctx.fillText(id, cx + 10, cy - 6);
  });
}

function drawGrid(ctx, W, H, scale) {
  ctx.strokeStyle = "#e4e4e7";
  ctx.lineWidth = 1;

  // Grid lines every 0.5 m
  const step = 0.5 * scale;
  for (let x = W / 2 % step; x < W; x += step) {
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, W); ctx.stroke();
  }
  for (let y = H / 2 % step; y < H; y += step) {
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
  }

  // Axes
  ctx.strokeStyle = "#a1a1aa";
  ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(W / 2, 0); ctx.lineTo(W / 2, H); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(0, H / 2); ctx.lineTo(W, H / 2); ctx.stroke();

  // Origin dot
  ctx.beginPath();
  ctx.arc(W / 2, H / 2, 3, 0, 2 * Math.PI);
  ctx.fillStyle = "#a1a1aa";
  ctx.fill();
}

function drawPentagonTargets(ctx, W, H, scale) {
  const positions = Object.values(state.robots).filter(p => p.online);
  if (positions.length === 0) return;

  const cx = positions.reduce((s, p) => s + p.x, 0) / positions.length;
  const cy = positions.reduce((s, p) => s + p.y, 0) / positions.length;
  const r = 0.5; // same radius as pentagon.py

  for (let i = 0; i < 5; i++) {
    const angle = (2 * Math.PI * i / 5) - Math.PI / 2;
    const vx = cx + r * Math.cos(angle);
    const vy = cy + r * Math.sin(angle);
    const sx = W / 2 + vx * scale;
    const sy = H / 2 - vy * scale;

    ctx.beginPath();
    ctx.arc(sx, sy, 6, 0, 2 * Math.PI);
    ctx.strokeStyle = "#6366f1";
    ctx.lineWidth = 2;
    ctx.stroke();
  }
}

// ---------------------------------------------------------------------------
// Log panel
// ---------------------------------------------------------------------------

function log(message, type = "") {
  const panel = document.getElementById("log-panel");
  const p = document.createElement("p");
  p.className = `log-line${type ? " log-" + type : ""}`;
  const ts = new Date().toLocaleTimeString();
  p.textContent = `[${ts}] ${message}`;
  panel.appendChild(p);
  panel.scrollTop = panel.scrollHeight;

  // Cap log at 200 lines
  while (panel.children.length > 200) {
    panel.removeChild(panel.firstChild);
  }
}

// ---------------------------------------------------------------------------
// REST helpers
// ---------------------------------------------------------------------------

async function api(method, path, body) {
  try {
    const opts = { method, headers: {} };
    if (body) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(path, opts);
    return await res.json();
  } catch (e) {
    log(`Request failed: ${e.message}`, "err");
    return null;
  }
}

async function robotAction(robotId, action) {
  log(`[${robotId}] ${action}…`);
  const data = await api("POST", `/robots/${robotId}/${action}`);
  if (data) {
    log(`[${robotId}] ${action}: ${data.message}`, data.ok ? "ok" : "err");
  }
}

// ---------------------------------------------------------------------------
// Group action buttons
// ---------------------------------------------------------------------------

async function groupAction(action) {
  log(`${action}…`);
  const data = await api("POST", `/robots/${action}`);
  if (!data) return;
  for (const r of data) {
    log(`[${r.robot_id}] ${action}: ${r.message}`, r.ok ? "ok" : "err");
  }
}

document.getElementById("btn-deploy-all").addEventListener("click", () => groupAction("deploy_all"));
document.getElementById("btn-start-all").addEventListener("click",  () => groupAction("start_all"));
document.getElementById("btn-stop-all").addEventListener("click",   () => groupAction("stop_all"));

// ---------------------------------------------------------------------------
// Algorithm panel
// ---------------------------------------------------------------------------

document.getElementById("btn-run-algo").addEventListener("click", async () => {
  const name = document.getElementById("algo-select").value;
  const data = await api("POST", "/algorithm", { name });
  if (data && data.ok) {
    state.algorithm = name;
    document.getElementById("algo-active").textContent = name;
    log(`Algorithm set to: ${name}`, "info");
  }
});

// ---------------------------------------------------------------------------
// Boot: load initial fleet config, then open WebSocket
// ---------------------------------------------------------------------------

let fleetConfig = [];

async function init() {
  const data = await api("GET", "/robots");
  if (!data) { log("Failed to load fleet config", "err"); return; }

  fleetConfig = data;

  // Seed state.robots from initial fleet data so table renders before WS connects
  for (const r of fleetConfig) {
    if (r.position) {
      state.robots[r.id] = { ...r.position, online: r.online };
    }
  }

  buildFleetRows();   // build row structure once (buttons stay stable)
  updateFleetCells(); // fill in initial status/position
  renderMap();
  connectWS();
}

init();
