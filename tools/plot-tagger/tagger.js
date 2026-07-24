// Standalone plot-tagging tool. No build step, no dependencies — open index.html
// directly (or serve the folder) to digitize a cluster: load a master-plan crop,
// click to drop pins, type the plot number/type read directly off the drawing,
// export a cluster JSON that matches src/data/types.ts#RawClusterData exactly.

const state = {
  image: null,
  scale: 1,
  offsetX: 0,
  offsetY: 0,
  units: [], // RawUnit[]
  legend: {}, // { code: { color, label } }
  clusterId: 'portofino',
  editingId: null, // id of unit currently open in the form, or null when creating
  pendingImageCoords: null, // {x,y} for a not-yet-saved new pin
};

const DEFAULT_LEGEND = {
  'BL-5-E': { color: '#7B3FA0', label: '5BR Townhouse (End)' },
  'BL-3-M': { color: '#7FD4E8', label: '3BR Townhouse (Middle)' },
  'BL-4-M': { color: '#D9B98A', label: '4BR Townhouse (Middle)' },
  'BL-VD1': { color: '#F0A94E', label: 'Large Villa (bedroom count unconfirmed)' },
  'BL-V75': { color: '#F2B4D6', label: 'Signature Villa (bedroom count unconfirmed)' },
};
state.legend = { ...DEFAULT_LEGEND };

const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');
const wrap = document.getElementById('canvas-wrap');
const zoomIndicator = document.getElementById('zoom-indicator');
const pinForm = document.getElementById('pin-form');
const statusLine = document.getElementById('status-line');

function resizeCanvas() {
  canvas.width = wrap.clientWidth;
  canvas.height = wrap.clientHeight;
  render();
}
window.addEventListener('resize', resizeCanvas);

function imageToScreen(x, y) {
  return { x: x * state.scale + state.offsetX, y: y * state.scale + state.offsetY };
}
function screenToImage(x, y) {
  return { x: (x - state.offsetX) / state.scale, y: (y - state.offsetY) / state.scale };
}

function fitToWindow() {
  if (!state.image) return;
  const scale = Math.min(canvas.width / state.image.width, canvas.height / state.image.height) * 0.95;
  state.scale = scale;
  state.offsetX = (canvas.width - state.image.width * scale) / 2;
  state.offsetY = (canvas.height - state.image.height * scale) / 2;
  render();
}

function zoomAt(factor, cx, cy) {
  if (!state.image) return;
  const before = screenToImage(cx, cy);
  state.scale = Math.min(Math.max(state.scale * factor, 0.02), 12);
  const after = imageToScreen(before.x, before.y);
  state.offsetX -= after.x - cx;
  state.offsetY -= after.y - cy;
  render();
}

function render() {
  ctx.fillStyle = '#050505';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  if (state.image) {
    ctx.imageSmoothingEnabled = true;
    ctx.drawImage(
      state.image,
      state.offsetX,
      state.offsetY,
      state.image.width * state.scale,
      state.image.height * state.scale,
    );
    zoomIndicator.textContent = `${state.image.width}×${state.image.height}px source · ${(state.scale * 100).toFixed(0)}% zoom · ${state.units.length} pins`;
  } else {
    zoomIndicator.textContent = 'no image loaded';
  }

  for (const unit of state.units) {
    const p = imageToScreen(unit.planPx[0], unit.planPx[1]);
    if (p.x < -20 || p.y < -20 || p.x > canvas.width + 20 || p.y > canvas.height + 20) continue;
    const color = state.legend[unit.typeCode]?.color ?? '#ff0033';
    const isEditing = unit.id === state.editingId;

    ctx.beginPath();
    ctx.arc(p.x, p.y, isEditing ? 7 : 5, 0, Math.PI * 2);
    ctx.fillStyle = unit.verified ? color : '#666';
    ctx.fill();
    ctx.lineWidth = isEditing ? 2.5 : 1.5;
    ctx.strokeStyle = isEditing ? '#ff0033' : '#000';
    ctx.stroke();

    if (state.scale > 0.35) {
      ctx.font = '11px sans-serif';
      ctx.fillStyle = '#fff';
      ctx.strokeStyle = 'rgba(0,0,0,0.85)';
      ctx.lineWidth = 3;
      ctx.strokeText(unit.id, p.x + 8, p.y - 8);
      ctx.fillText(unit.id, p.x + 8, p.y - 8);
    }
  }

  if (state.pendingImageCoords) {
    const p = imageToScreen(state.pendingImageCoords.x, state.pendingImageCoords.y);
    ctx.beginPath();
    ctx.arc(p.x, p.y, 7, 0, Math.PI * 2);
    ctx.strokeStyle = '#ff0033';
    ctx.lineWidth = 2;
    ctx.stroke();
  }
}

// ---------------- image / json loading ----------------

document.getElementById('image-input').addEventListener('change', (e) => {
  const file = e.target.files?.[0];
  if (!file) return;
  const url = URL.createObjectURL(file);
  const img = new Image();
  img.onload = () => {
    state.image = img;
    fitToWindow();
    setStatus(`Loaded ${file.name} (${img.width}×${img.height}px).`);
  };
  img.src = url;
});

document.getElementById('json-input').addEventListener('change', (e) => {
  const file = e.target.files?.[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const data = JSON.parse(String(reader.result));
      state.clusterId = data.cluster ?? state.clusterId;
      document.getElementById('cluster-id').value = state.clusterId;
      if (data.legend) state.legend = { ...state.legend, ...data.legend };
      state.units = Array.isArray(data.units) ? data.units : [];
      renderLegendList();
      renderTable();
      render();
      setStatus(`Loaded ${state.units.length} existing units from ${file.name}. Load the same base image to continue tagging in the same coordinate space.`);
    } catch (err) {
      setStatus('Could not parse JSON: ' + err.message, true);
    }
  };
  reader.readAsText(file);
});

// ---------------- pan / zoom / click ----------------

let panning = false;
let panStart = null;
let didDrag = false;

canvas.addEventListener('contextmenu', (e) => e.preventDefault());

canvas.addEventListener('mousedown', (e) => {
  if (e.button === 2 || e.ctrlKey || e.metaKey) {
    panning = true;
    didDrag = false;
    panStart = { x: e.clientX, y: e.clientY, offX: state.offsetX, offY: state.offsetY };
    wrap.classList.add('panning');
  }
});

window.addEventListener('mousemove', (e) => {
  if (panning && panStart) {
    const dx = e.clientX - panStart.x;
    const dy = e.clientY - panStart.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) didDrag = true;
    state.offsetX = panStart.offX + dx;
    state.offsetY = panStart.offY + dy;
    render();
  }
});

window.addEventListener('mouseup', () => {
  panning = false;
  wrap.classList.remove('panning');
});

canvas.addEventListener('wheel', (e) => {
  e.preventDefault();
  const rect = canvas.getBoundingClientRect();
  const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
  zoomAt(factor, e.clientX - rect.left, e.clientY - rect.top);
}, { passive: false });

canvas.addEventListener('click', (e) => {
  if (didDrag) { didDrag = false; return; }
  if (!state.image) return;
  const rect = canvas.getBoundingClientRect();
  const sx = e.clientX - rect.left;
  const sy = e.clientY - rect.top;

  const hit = hitTestUnit(sx, sy);
  if (hit) {
    openEditForm(hit, sx, sy);
    return;
  }
  const imgCoords = screenToImage(sx, sy);
  openCreateForm(imgCoords, sx, sy);
});

function hitTestUnit(sx, sy) {
  let best = null;
  let bestDist = 12;
  for (const unit of state.units) {
    const p = imageToScreen(unit.planPx[0], unit.planPx[1]);
    const d = Math.hypot(p.x - sx, p.y - sy);
    if (d < bestDist) { bestDist = d; best = unit; }
  }
  return best;
}

// ---------------- pin form ----------------

const els = {
  id: document.getElementById('pin-id'),
  type: document.getElementById('pin-type'),
  tier: document.getElementById('pin-tier'),
  rowgroup: document.getElementById('pin-rowgroup'),
  bedrooms: document.getElementById('pin-bedrooms'),
  deleteBtn: document.getElementById('pin-delete'),
};

function positionForm(sx, sy) {
  const formW = 240, formH = 340;
  let left = sx + 16;
  let top = sy - 20;
  if (left + formW > wrap.clientWidth) left = sx - formW - 16;
  if (top + formH > wrap.clientHeight) top = wrap.clientHeight - formH - 10;
  if (top < 10) top = 10;
  pinForm.style.left = left + 'px';
  pinForm.style.top = top + 'px';
}

function openCreateForm(imgCoords, sx, sy) {
  state.editingId = null;
  state.pendingImageCoords = imgCoords;
  els.id.value = '';
  els.type.value = '';
  els.tier.value = '3';
  els.rowgroup.value = lastRowGroup ?? '';
  els.bedrooms.value = '';
  els.deleteBtn.style.display = 'none';
  positionForm(sx, sy);
  pinForm.classList.add('visible');
  render();
  els.id.focus();
}

function openEditForm(unit, sx, sy) {
  state.editingId = unit.id;
  state.pendingImageCoords = null;
  els.id.value = unit.id;
  els.type.value = unit.typeCode;
  els.tier.value = String(unit.tier);
  els.rowgroup.value = unit.rowGroup ?? '';
  els.bedrooms.value = unit.bedrooms ?? '';
  els.deleteBtn.style.display = 'block';
  positionForm(sx, sy);
  pinForm.classList.add('visible');
  render();
}

function closeForm() {
  pinForm.classList.remove('visible');
  state.pendingImageCoords = null;
  state.editingId = null;
  render();
}

let lastRowGroup = '';

document.getElementById('pin-cancel').addEventListener('click', closeForm);

document.getElementById('pin-save').addEventListener('click', () => {
  const id = els.id.value.trim();
  const typeCode = els.type.value.trim();
  const tier = Number(els.tier.value);
  const rowGroup = els.rowgroup.value.trim();
  const bedroomsRaw = els.bedrooms.value.trim();
  const bedrooms = bedroomsRaw ? Number(bedroomsRaw) : null;

  if (!id) { setStatus('Plot ID is required.', true); return; }
  if (!typeCode) { setStatus('Type code is required.', true); return; }

  lastRowGroup = rowGroup;

  if (state.editingId) {
    const unit = state.units.find((u) => u.id === state.editingId);
    if (unit) {
      if (id !== unit.id && state.units.some((u) => u.id === id)) {
        setStatus(`A unit with id "${id}" already exists.`, true);
        return;
      }
      unit.id = id;
      unit.typeCode = typeCode;
      unit.tier = tier;
      unit.rowGroup = rowGroup;
      unit.bedrooms = bedrooms;
      unit.bedroomsConfirmed = bedrooms !== null;
    }
  } else {
    if (!state.pendingImageCoords) return;
    if (state.units.some((u) => u.id === id)) {
      setStatus(`A unit with id "${id}" already exists.`, true);
      return;
    }
    state.units.push({
      id,
      cluster: state.clusterId,
      rowGroup,
      typeCode,
      tier,
      bedrooms,
      bedroomsConfirmed: bedrooms !== null,
      planPx: [Math.round(state.pendingImageCoords.x), Math.round(state.pendingImageCoords.y)],
      verified: true,
      notes: null,
    });
  }

  if (!state.legend[typeCode]) {
    state.legend[typeCode] = { color: '#ff0033', label: typeCode };
    renderLegendList();
  }

  closeForm();
  renderTable();
  setStatus(`Saved ${id}.`);
});

document.getElementById('pin-delete').addEventListener('click', () => {
  if (!state.editingId) return;
  state.units = state.units.filter((u) => u.id !== state.editingId);
  closeForm();
  renderTable();
});

// ---------------- legend ----------------

function renderLegendList() {
  const list = document.getElementById('legend-list');
  list.innerHTML = '';
  const typeOptions = document.getElementById('type-options');
  typeOptions.innerHTML = '';
  for (const [code, entry] of Object.entries(state.legend)) {
    const row = document.createElement('div');
    row.className = 'legend-entry';
    const sw = document.createElement('div');
    sw.className = 'swatch';
    sw.style.background = entry.color;
    row.appendChild(sw);
    const text = document.createElement('span');
    text.textContent = `${code} — ${entry.label}`;
    row.appendChild(text);
    list.appendChild(row);

    const opt = document.createElement('option');
    opt.value = code;
    typeOptions.appendChild(opt);
  }
}
renderLegendList();

document.getElementById('add-legend').addEventListener('click', () => {
  const code = document.getElementById('legend-code').value.trim();
  const color = document.getElementById('legend-color').value;
  const label = document.getElementById('legend-label').value.trim() || code;
  if (!code) return;
  state.legend[code] = { color, label };
  document.getElementById('legend-code').value = '';
  document.getElementById('legend-label').value = '';
  renderLegendList();
});

// ---------------- table ----------------

function renderTable() {
  const tbody = document.getElementById('units-table');
  const filter = document.getElementById('filter-input').value.trim().toLowerCase();
  tbody.innerHTML = '';
  const filtered = state.units.filter(
    (u) => !filter || u.id.toLowerCase().includes(filter) || (u.rowGroup ?? '').toLowerCase().includes(filter),
  );
  for (const unit of filtered) {
    const tr = document.createElement('tr');
    tr.className = 'unit-row' + (unit.verified ? '' : ' unverified');
    tr.innerHTML = `<td>${unit.id}</td><td>${unit.typeCode}</td><td>${unit.tier}</td><td>${unit.rowGroup ?? ''}</td>`;
    const tdActions = document.createElement('td');
    const locateBtn = document.createElement('button');
    locateBtn.className = 'small-btn secondary';
    locateBtn.textContent = 'Locate';
    locateBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      locateUnit(unit);
    });
    tdActions.appendChild(locateBtn);
    tr.appendChild(tdActions);
    tr.addEventListener('click', () => locateUnit(unit, true));
    tbody.appendChild(tr);
  }
  document.getElementById('count-badge').textContent = String(state.units.length);
}
document.getElementById('filter-input').addEventListener('input', renderTable);

function locateUnit(unit, openForm = false) {
  if (!state.image) return;
  state.scale = Math.max(state.scale, 1.2);
  state.offsetX = canvas.width / 2 - unit.planPx[0] * state.scale;
  state.offsetY = canvas.height / 2 - unit.planPx[1] * state.scale;
  render();
  if (openForm) {
    const p = imageToScreen(unit.planPx[0], unit.planPx[1]);
    openEditForm(unit, p.x, p.y);
  }
}

// ---------------- export ----------------

document.getElementById('cluster-id').addEventListener('change', (e) => {
  state.clusterId = e.target.value.trim() || 'portofino';
});

document.getElementById('export-json').addEventListener('click', () => {
  const out = {
    cluster: state.clusterId,
    source: {
      document: 'Damac_Lagoons_Community_Master_Plan_2023.pdf',
      digitizedBy: 'plot-tagger-tool',
      digitizedOn: new Date().toISOString().slice(0, 10),
      method: 'Manual click-to-tag digitization against the master-plan raster using tools/plot-tagger.',
      coverage: 'EDIT ME: describe which part of the cluster this file covers.',
    },
    legend: state.legend,
    units: state.units.map((u) => ({ ...u, cluster: state.clusterId })),
  };
  const blob = new Blob([JSON.stringify(out, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `${state.clusterId}.json`;
  a.click();
  setStatus(`Exported ${state.units.length} units to ${a.download}.`);
});

function setStatus(msg, isError = false) {
  statusLine.textContent = msg;
  statusLine.style.color = isError ? '#ff5577' : '#6a6';
}

document.getElementById('zoom-in').addEventListener('click', () => zoomAt(1.3, canvas.width / 2, canvas.height / 2));
document.getElementById('zoom-out').addEventListener('click', () => zoomAt(1 / 1.3, canvas.width / 2, canvas.height / 2));
document.getElementById('zoom-fit').addEventListener('click', fitToWindow);

resizeCanvas();
renderTable();
