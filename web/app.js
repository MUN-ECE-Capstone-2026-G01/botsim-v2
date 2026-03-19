// botsim-v2 — Fleet Control UI
//
// WebSocket /ws/ui receives:
//   {type:"state",   positions:{id:{x,y,theta,last_seen}}}
//   {type:"log",     message:string}

// ---------------------------------------------------------------------------
// Theme toggle
// ---------------------------------------------------------------------------

function isLight() {
  return document.documentElement.getAttribute('data-theme') === 'light';
}

// Script is at end of <body> so DOM is already loaded — no DOMContentLoaded needed
const _themeBtn = document.getElementById('btn-theme');
if (_themeBtn) {
  _themeBtn.textContent = isLight() ? '☀️' : '🌙';
  _themeBtn.addEventListener('click', () => {
    const light = !isLight();
    document.documentElement.setAttribute('data-theme', light ? 'light' : 'dark');
    localStorage.setItem('theme', light ? 'light' : 'dark');
    _themeBtn.textContent = light ? '☀️' : '🌙';
    renderMap();
  });
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let fleetConfig = [];       // [{id, host, online, color, position}]  from GET /robots
const robotColors = {};     // id → resolved hex color

const state = {
  robots:    {},            // id → {x, y, theta, online}
  algorithm: null,
};

// Trail state (client-side only)
const trails    = {};       // id → [{x, y}]
const arrivedAt = {};       // id → timestamp ms when robot arrived, or null

let trajectoryCleanupDelay = 3; // seconds — from GET /config

const TRAIL_MAX        = 300;
const ARRIVE_THRESHOLD = 0.10;  // metres
const PENTAGON_RADIUS  = 0.5;   // metres — must match pentagon.py
const WORLD_RANGE      = 2.5;   // ±metres on map

// Shapes algorithm vertex counts (must match shapes.py)
const SHAPE_VERTEX_COUNT = {
  point: 1, line: 2, triangle: 3, square: 4, pentagon: 5, hexagon: 6,
};

// Active shapes params (set when Run is pressed with shapes algorithm)
let activeShapeParams = null; // {shape, center_x, center_y, radius} or null

// ---------------------------------------------------------------------------
// Color utilities
// ---------------------------------------------------------------------------

function hexToRgb(hex) {
  return [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));
}

function trailColor(hex) {
  const [r, g, b] = hexToRgb(hex);
  return `rgba(${r},${g},${b},0.35)`;
}

function targetColor(hex) {
  const [r, g, b] = hexToRgb(hex).map(c => Math.round(c * 0.6));
  return `rgb(${r},${g},${b})`;
}

// ---------------------------------------------------------------------------
// WebSocket
// ---------------------------------------------------------------------------

let ws = null;

function connectWS() {
  ws = new WebSocket(`ws://${location.host}/ws/ui`);

  ws.onopen = () => {
    setWsStatus(true);
    appendLog('Connected to broker.', 'info');
  };

  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'state') {
      mergePositions(msg.positions);
      updateTrails();
      updateFleetCells();
      renderMap();
    } else if (msg.type === 'log') {
      appendLog(msg.message);
    }
  };

  ws.onclose = () => {
    setWsStatus(false);
    appendLog('Disconnected — reconnecting in 3 s…', 'err');
    setTimeout(connectWS, 3000);
  };

  ws.onerror = () => ws.close();
}

function setWsStatus(online) {
  const el = document.getElementById('ws-status');
  el.className = `ws-badge ${online ? 'ws-online' : 'ws-offline'}`;
  el.querySelector('.ws-label').textContent = online ? 'connected' : 'disconnected';
}

// ---------------------------------------------------------------------------
// Position state
// ---------------------------------------------------------------------------

function mergePositions(positions) {
  for (const id of Object.keys(state.robots)) {
    state.robots[id].online = false;
  }
  for (const [id, pos] of Object.entries(positions)) {
    state.robots[id] = { ...pos, online: true };
  }
}

// ---------------------------------------------------------------------------
// Trail tracking
// ---------------------------------------------------------------------------

function getActiveTargets(onlineRobots) {
  if (state.algorithm === 'pentagon') return getPentagonVertices(onlineRobots);
  if (state.algorithm === 'shapes' && activeShapeParams) {
    const { shape, center_x, center_y, radius } = activeShapeParams;
    return getShapeVertices(shape, center_x, center_y, radius);
  }
  return null;
}

function updateTrails() {
  if (!state.algorithm || state.algorithm === 'idle') return;

  const onlineRobots = Object.entries(state.robots)
    .filter(([, p]) => p.online)
    .map(([id, p]) => ({ id, x: p.x, y: p.y }));

  const targets    = getActiveTargets(onlineRobots);
  const assignment = targets ? assignTargets(onlineRobots, targets) : {};

  for (const [id, pos] of Object.entries(state.robots)) {
    if (!pos.online) continue;

    if (!trails[id]) trails[id] = [];
    trails[id].push({ x: pos.x, y: pos.y });
    if (trails[id].length > TRAIL_MAX) trails[id].shift();

    // Arrival detection
    const vIdx   = assignment[id];
    const target = (vIdx !== undefined && targets) ? targets[vIdx] : null;

    if (target) {
      const dist = Math.hypot(pos.x - target.x, pos.y - target.y);
      if (dist < ARRIVE_THRESHOLD) {
        if (!arrivedAt[id]) arrivedAt[id] = Date.now();
      } else {
        arrivedAt[id] = null;
      }
    } else {
      arrivedAt[id] = null;
    }

    // Clear trail once arrived AND cleanup delay has elapsed
    if (arrivedAt[id] && (Date.now() - arrivedAt[id]) >= trajectoryCleanupDelay * 1000) {
      trails[id]    = [];
      arrivedAt[id] = null;
    }
  }
}

// ---------------------------------------------------------------------------
// Formation geometry
// ---------------------------------------------------------------------------

function getPentagonVertices(robots) {
  if (robots.length === 0) return null;
  const cx = robots.reduce((s, r) => s + r.x, 0) / robots.length;
  const cy = robots.reduce((s, r) => s + r.y, 0) / robots.length;
  return Array.from({ length: 5 }, (_, i) => {
    const angle = (2 * Math.PI * i / 5) - Math.PI / 2;
    return {
      x: cx + PENTAGON_RADIUS * Math.cos(angle),
      y: cy + PENTAGON_RADIUS * Math.sin(angle),
    };
  });
}

function getShapeVertices(shape, cx, cy, radius) {
  const n = SHAPE_VERTEX_COUNT[shape] ?? 3;
  if (n === 1) return [{ x: cx, y: cy }];
  if (n === 2) return [{ x: cx, y: cy + radius }, { x: cx, y: cy - radius }];
  return Array.from({ length: n }, (_, i) => {
    const angle = Math.PI / 2 - i * (2 * Math.PI / n);
    return { x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle) };
  });
}

// Optimal assignment — brute-force N robots to best N of M vertices.
// Equivalent to scipy.optimize.linear_sum_assignment for N ≤ 6.
function assignTargets(robots, vertices) {
  const nr = robots.length;
  const nv = vertices.length;
  if (nr === 0 || nv === 0) return {};
  // If more robots than vertices, only assign robots up to vertex count
  if (nr > nv) return assignTargets(robots.slice(0, nv), vertices);

  const cost = robots.map(r => vertices.map(v => Math.hypot(r.x - v.x, r.y - v.y)));

  let bestCost   = Infinity;
  let bestAssign = null;

  // Choose nr columns from nv, then enumerate all permutations of that subset
  function chooseCols(chosen, start) {
    if (chosen.length === nr) {
      const perm = [...chosen];
      function permute(s) {
        if (s === perm.length) {
          const c = perm.reduce((acc, vi, bi) => acc + cost[bi][vi], 0);
          if (c < bestCost) { bestCost = c; bestAssign = [...perm]; }
          return;
        }
        for (let i = s; i < perm.length; i++) {
          [perm[s], perm[i]] = [perm[i], perm[s]];
          permute(s + 1);
          [perm[s], perm[i]] = [perm[i], perm[s]];
        }
      }
      permute(0);
      return;
    }
    for (let i = start; i < nv; i++) {
      chooseCols([...chosen, i], i + 1);
    }
  }

  chooseCols([], 0);

  const assignment = {};
  robots.forEach((r, bi) => { assignment[r.id] = bestAssign[bi]; });
  return assignment;
}

// ---------------------------------------------------------------------------
// Fleet table — two-phase render
// buildFleetRows(): called once on init (builds DOM with stable buttons)
// updateFleetCells(): called on every state update (only touches text/badge)
// ---------------------------------------------------------------------------

function buildFleetRows() {
  const tbody = document.querySelector('#fleet-table tbody');
  tbody.innerHTML = '';
  for (const r of fleetConfig) {
    const color = robotColors[r.id] || '#6366f1';
    const tr    = document.createElement('tr');
    tr.id = `row-${r.id}`;
    tr.innerHTML = `
      <td>
        <div class="robot-id-cell">
          <span class="robot-dot" style="background:${color};box-shadow:0 0 7px ${color}55"></span>
          <span class="robot-name">${r.id}</span>
        </div>
      </td>
      <td id="status-${r.id}">
        <span class="status-badge status-offline"><span class="s-dot"></span>offline</span>
      </td>
      <td id="pos-${r.id}" class="pos-cell">—</td>
      <td class="action-cell">
        <button class="btn btn-sm btn-neutral" onclick="robotAction('${r.id}','deploy')">Deploy</button>
        <button class="btn btn-sm btn-primary" onclick="robotAction('${r.id}','start')">Start</button>
        <button class="btn btn-sm btn-danger"  onclick="robotAction('${r.id}','stop')">Stop</button>
      </td>
    `;
    tbody.appendChild(tr);
  }
}

function updateFleetCells() {
  let onlineCount = 0;
  for (const r of fleetConfig) {
    const pos    = state.robots[r.id];
    const online = pos ? pos.online : false;
    if (online) onlineCount++;

    const statusEl = document.getElementById(`status-${r.id}`);
    const posEl    = document.getElementById(`pos-${r.id}`);
    if (!statusEl || !posEl) continue;

    statusEl.innerHTML = online
      ? `<span class="status-badge status-online"><span class="s-dot"></span>online</span>`
      : `<span class="status-badge status-offline"><span class="s-dot"></span>offline</span>`;

    posEl.textContent = (pos && pos.online)
      ? `${pos.x.toFixed(2)}, ${pos.y.toFixed(2)}, ${(pos.theta * 180 / Math.PI).toFixed(1)}°`
      : '—';
  }
  document.getElementById('online-count').textContent = `${onlineCount} online`;
}

// ---------------------------------------------------------------------------
// Map canvas
// ---------------------------------------------------------------------------

function renderMap() {
  const canvas = document.getElementById('map');
  const ctx    = canvas.getContext('2d');
  const W = canvas.width;
  const H = canvas.height;
  const scale = W / (2 * WORLD_RANGE);

  const cs = getComputedStyle(document.documentElement);
  const mapBg     = cs.getPropertyValue('--map-bg').trim();
  const mapGrid   = cs.getPropertyValue('--map-grid').trim();
  const mapAxis   = cs.getPropertyValue('--map-axis').trim();
  const mapOrigin = cs.getPropertyValue('--map-origin').trim();
  const mapLabel  = cs.getPropertyValue('--map-label').trim();

  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = mapBg;
  ctx.fillRect(0, 0, W, H);

  drawGrid(ctx, W, H, scale, mapGrid, mapAxis, mapOrigin);

  const onlineRobots = Object.entries(state.robots)
    .filter(([, p]) => p.online)
    .map(([id, p]) => ({ id, ...p }));

  let targets    = null;
  let assignment = {};

  if (state.algorithm === 'pentagon' || state.algorithm === 'shapes') {
    targets    = getActiveTargets(onlineRobots);
    assignment = targets ? assignTargets(onlineRobots, targets) : {};
    if (targets) drawFormationMarkers(ctx, W, H, scale, targets);
  }

  // Trails (drawn under robots)
  for (const robot of onlineRobots) {
    const trail = trails[robot.id];
    if (!trail || trail.length < 2) continue;

    const color = robotColors[robot.id] || '#6366f1';
    ctx.beginPath();
    ctx.strokeStyle = trailColor(color);
    ctx.lineWidth   = 2;
    ctx.lineJoin    = 'round';
    ctx.lineCap     = 'round';

    const p0 = trail[0];
    ctx.moveTo(W / 2 + p0.x * scale, H / 2 - p0.y * scale);
    for (let i = 1; i < trail.length; i++) {
      ctx.lineTo(W / 2 + trail[i].x * scale, H / 2 - trail[i].y * scale);
    }
    ctx.stroke();
  }

  // Target crosses
  if (targets) {
    for (const robot of onlineRobots) {
      const vIdx = assignment[robot.id];
      if (vIdx === undefined) continue;
      const v     = targets[vIdx];
      const sx    = W / 2 + v.x * scale;
      const sy    = H / 2 - v.y * scale;
      const color = robotColors[robot.id] || '#6366f1';
      drawCross(ctx, sx, sy, 9, targetColor(color));
    }
  }

  // Robot dots + heading lines + labels
  for (const robot of onlineRobots) {
    const sx    = W / 2 + robot.x * scale;
    const sy    = H / 2 - robot.y * scale;
    const color = robotColors[robot.id] || '#6366f1';

    // Heading line
    const headLen = 0.18 * scale;
    ctx.beginPath();
    ctx.moveTo(sx, sy);
    ctx.lineTo(sx + headLen * Math.cos(robot.theta), sy - headLen * Math.sin(robot.theta));
    ctx.strokeStyle = color;
    ctx.lineWidth   = 2;
    ctx.lineCap     = 'round';
    ctx.stroke();

    // Glow halo
    ctx.beginPath();
    ctx.arc(sx, sy, 12, 0, 2 * Math.PI);
    ctx.fillStyle = `${color}1a`;
    ctx.fill();

    // Robot dot
    ctx.beginPath();
    ctx.arc(sx, sy, 7, 0, 2 * Math.PI);
    ctx.fillStyle = color;
    ctx.fill();

    // Label
    ctx.font        = '500 10px "JetBrains Mono", monospace';
    ctx.fillStyle   = mapLabel;
    ctx.shadowColor = isLight() ? 'rgba(255,255,255,0.8)' : '#000';
    ctx.shadowBlur  = 4;
    ctx.fillText(robot.id, sx + 11, sy - 5);
    ctx.shadowBlur  = 0;
  }
}

function drawGrid(ctx, W, H, scale, gridColor, axisColor, originColor) {
  const step = 0.5 * scale;

  // Minor grid lines
  ctx.strokeStyle = gridColor;
  ctx.lineWidth   = 1;
  for (let x = W / 2 % step; x < W; x += step) {
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
  }
  for (let y = H / 2 % step; y < H; y += step) {
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
  }

  // Axes
  ctx.strokeStyle = axisColor;
  ctx.lineWidth   = 1;
  ctx.beginPath(); ctx.moveTo(W / 2, 0); ctx.lineTo(W / 2, H); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(0, H / 2); ctx.lineTo(W, H / 2); ctx.stroke();

  // Origin dot
  ctx.beginPath();
  ctx.arc(W / 2, H / 2, 2.5, 0, 2 * Math.PI);
  ctx.fillStyle = originColor;
  ctx.fill();
}

function drawFormationMarkers(ctx, W, H, scale, vertices) {
  ctx.strokeStyle = 'rgba(99,102,241,0.2)';
  ctx.lineWidth   = 1.5;
  for (const v of vertices) {
    const sx = W / 2 + v.x * scale;
    const sy = H / 2 - v.y * scale;
    ctx.beginPath();
    ctx.arc(sx, sy, 5, 0, 2 * Math.PI);
    ctx.stroke();
  }
}

function drawCross(ctx, x, y, size, color) {
  ctx.strokeStyle = color;
  ctx.lineWidth   = 2.5;
  ctx.lineCap     = 'round';
  ctx.beginPath();
  ctx.moveTo(x - size, y - size); ctx.lineTo(x + size, y + size);
  ctx.moveTo(x + size, y - size); ctx.lineTo(x - size, y + size);
  ctx.stroke();
}

// ---------------------------------------------------------------------------
// Log panel
// ---------------------------------------------------------------------------

function appendLog(message, type = '') {
  const panel = document.getElementById('log-panel');
  const p     = document.createElement('p');
  p.className = `log-line${type ? ' log-' + type : ''}`;

  const ts = new Date().toLocaleTimeString('en-GB', { hour12: false });
  p.innerHTML = `<span class="log-ts">${ts}</span>${escapeHtml(message)}`;
  panel.appendChild(p);
  panel.scrollTop = panel.scrollHeight;

  while (panel.children.length > 200) panel.removeChild(panel.firstChild);
}

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

document.getElementById('btn-clear-log').addEventListener('click', () => {
  document.getElementById('log-panel').innerHTML = '';
});

// ---------------------------------------------------------------------------
// REST helpers
// ---------------------------------------------------------------------------

async function api(method, path, body) {
  try {
    const opts = { method, headers: {} };
    if (body) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(path, opts);
    return await res.json();
  } catch (e) {
    appendLog(`Request failed: ${e.message}`, 'err');
    return null;
  }
}

async function robotAction(robotId, action) {
  appendLog(`[${robotId}] ${action}…`);
  const data = await api('POST', `/robots/${robotId}/${action}`);
  if (data) appendLog(`[${robotId}] ${action}: ${data.message}`, data.ok ? 'ok' : 'err');
}

// ---------------------------------------------------------------------------
// Group action buttons
// ---------------------------------------------------------------------------

async function groupAction(action) {
  appendLog(`${action}…`);
  const data = await api('POST', `/robots/${action}`);
  if (!data) return;
  for (const r of data) {
    appendLog(`[${r.robot_id}] ${action}: ${r.message}`, r.ok ? 'ok' : 'err');
  }
}

document.getElementById('btn-deploy-all').addEventListener('click', () => groupAction('deploy_all'));
document.getElementById('btn-start-all').addEventListener('click',  () => groupAction('start_all'));
document.getElementById('btn-stop-all').addEventListener('click',   () => groupAction('stop_all'));

// ---------------------------------------------------------------------------
// Algorithm panel
// ---------------------------------------------------------------------------

// Show/hide shapes params when dropdown changes
document.getElementById('algo-select').addEventListener('change', () => {
  const isShapes = document.getElementById('algo-select').value === 'shapes';
  document.getElementById('shapes-params').classList.toggle('visible', isShapes);
});

document.getElementById('btn-run-algo').addEventListener('click', async () => {
  const name   = document.getElementById('algo-select').value;
  let   params = {};

  if (name === 'shapes') {
    params = {
      shape:    document.getElementById('shape-type').value,
      center_x: parseFloat(document.getElementById('shape-cx').value) || 0,
      center_y: parseFloat(document.getElementById('shape-cy').value) || 0,
      radius:   parseFloat(document.getElementById('shape-r').value)  || 0.5,
    };
  }

  const data = await api('POST', '/algorithm', { name, params });
  if (data && data.ok) {
    state.algorithm   = name;
    activeShapeParams = name === 'shapes' ? params : null;
    document.getElementById('algo-active-tag').textContent = name === 'shapes'
      ? `shapes / ${params.shape}`
      : name;
    appendLog(`Algorithm → ${name}${name === 'shapes' ? ` (${params.shape}, r=${params.radius})` : ''}`, 'info');
    // Reset trails on algorithm switch
    for (const id of Object.keys(trails)) { trails[id] = []; arrivedAt[id] = null; }
    renderMap();
  }
});

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

async function init() {
  const [robotsData, configData] = await Promise.all([
    api('GET', '/robots'),
    api('GET', '/config'),
  ]);

  if (!robotsData) { appendLog('Failed to load fleet config.', 'err'); return; }

  fleetConfig             = robotsData;
  trajectoryCleanupDelay = configData?.trajectory_cleanup_delay ?? 3;

  for (const r of fleetConfig) {
    robotColors[r.id] = r.color || '#6366f1';
    if (r.position) {
      state.robots[r.id] = { ...r.position, online: r.online };
    }
  }

  buildFleetRows();
  updateFleetCells();
  renderMap();
  connectWS();
}

init();
