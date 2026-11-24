'use strict';

const byId = id => document.getElementById(id);
const map = byId('map');
const ctx = map.getContext('2d');
const current = {
  panel: null, settings: null, config: null, mode: 'coverage', view: 'marked',
  tool: 'point', first: null, pin: null, saved: null, image: null,
  drawing: 0, computing: 0, reading: 0, opening: 0, meta: null,
};
const columns = {
  expected_px: '版图像素', transfer_px: '转移像素', gap_px: '缺箔像素', coverage_pct: '覆盖 %',
  expected_mm2: '版图 mm²', gap_mm2: '缺箔 mm²', index: '序号', pixels: '像素数', area_mm2: '面积 mm²',
  width_mm: '宽 mm', height_mm: '高 mm', x: '源 X', y: '源 Y', distance_mm: '距离 mm',
  score: '箔色', expected: '版图', foil: '照片', reference: '参照', low_score: '第 10 百分位',
  median_score: '中位数', high_score: '第 90 百分位', foil_pct: '检出 %', lower: '下界',
  upper: '上界', die_px: '版图像素', paper_px: '留白像素', kind: '落点',
};
const directions = {point: '点图面可读源照片像素。', inspect: '点选检查窗的两个角。',
  gold: '圈一处已确认转移的箔色作为参照。', paper: '圈一处确认留白的纸色作为参照。',
  line: '在图面上点选剖线的两端。'};
const inputKeys = ['threshold', 'mm_per_pixel', 'min_pixels'];

function square(value) {
  return Math.round(value * 100) / 100;
}

function status(message, error = false) {
  const element = byId('status');
  element.textContent = message;
  element.toggleAttribute('data-error', error);
}

function safe(action) {
  return async event => {
    try {
      await action(event);
    } catch (error) {
      status(error.message, true);
    }
  };
}

async function response(path, method = 'GET', data) {
  const options = {method};
  if (data instanceof FormData) {
    options.body = data;
  } else if (data !== undefined) {
    options.body = JSON.stringify(data);
    options.headers = {'Content-Type': 'application/json'};
  }
  const reply = await fetch(path, options);
  if (!reply.ok) {
    const problem = await reply.json().catch(() => ({}));
    throw Error(problem.error || '读取检查服务失败。');
  }
  return reply;
}

async function json(path, method, data) {
  return (await response(path, method, data)).json();
}

function endpoint(suffix = '') {
  return '/foil/panels/' + current.panel.id + suffix;
}

function sourceUrl(layer, download = false) {
  const query = new URLSearchParams();
  if (current.saved) query.set('report', current.saved.id);
  if (download) query.set('download', '1');
  return endpoint('/source/' + layer + '.png') + (query.size ? '?' + query.toString() : '');
}

function reportUrl(suffix = '') {
  return endpoint('/reports/' + current.saved.id + suffix);
}

function snapshot() {
  return {settings: current.settings, mode: current.mode, revision: current.panel.revision};
}

function selected(button, active) {
  button.classList.toggle('active', active);
  button.setAttribute('aria-pressed', String(active));
}

function announceMap(message) {
  byId('map-note').textContent = message;
}

function describeLabel(meta) {
  const label = meta?.label;
  if (!label) {
    const pieces = [meta?.reason || '检查窗内还没有贴位。'];
    if (meta?.unviewable?.ranges?.length) {
      pieces.push('安全边超出照片，无法核对：' + meta.unviewable.ranges
        .map(item => item.side + '侧还差 ' + square(item.width_mm) + ' mm').join('，')
        + '，共占安全边 ' + meta.unviewable.pct + '%');
    }
    return pieces.join(' ');
  }
  const where = '贴位 X ' + label.x0 + '–' + label.x1 + ' px，宽 ' + square(label.width_mm) + ' mm';
  const offset = label.offset_side === '居中' ? '横带正中'
    : '较窗中心' + label.offset_side + ' ' + square(label.offset_mm) + ' mm';
  const clear = '实际净距 ' + square(label.clearance_mm) + ' mm / 要求 ' + square(label.requested_mm)
    + ' mm' + (label.meets ? '' : '（未达要求）')
    + '，最近箔 ' + (label.nearest_inside ? '在窗内' : '在窗外') + ' (' + label.nearest_x + ', ' + label.nearest_y + ')';
  const view = meta.unviewable?.ranges?.length
    ? '安全边超出照片，无法核对：' + meta.unviewable.ranges
      .map(item => item.side + '侧还差 ' + square(item.width_mm) + ' mm').join('，')
      + '，共占安全边 ' + meta.unviewable.pct + '%'
    : '安全边完整落在照片内';
  const pieces = [where, offset, clear, view];
  if (label.alternative) {
    pieces.push('若愿离开窗中心，X ' + label.alternative.x0 + '–' + label.alternative.x1
      + ' px 可留 ' + square(label.alternative.clearance_mm) + ' mm 净距');
  }
  return (label.adopted ? '已采用：' : '建议：') + pieces.join('；') + '。';
}

function renderPlacement(meta) {
  const note = byId('label-note');
  const button = byId('label-apply');
  const label = meta?.label;
  note.textContent = current.mode === 'leaks' && meta ? describeLabel(meta) : '';
  button.disabled = Boolean(current.saved) || current.mode !== 'leaks' || !label || label.adopted;
  button.textContent = label?.adopted ? '已采用此贴位' : '采用这个贴位';
}

function drawMap() {
  if (!current.image) return;
  ctx.drawImage(current.image, 0, 0, map.width, map.height);
  ctx.strokeStyle = '#a6eddf';
  ctx.lineWidth = Math.max(1, map.width / 800);
  ctx.setLineDash([6, 4]);
  const options = current.saved?.settings || current.settings;
  if (current.view !== 'marked') {
    const [x0, y0, x1, y1] = options.inspect;
    ctx.strokeRect(x0 + 1, y0 + 1, x1 - x0 - 2, y1 - y0 - 2);
  }
  ctx.setLineDash([]);
  const label = current.mode === 'leaks' ? current.meta?.label : null;
  if (label && current.view !== 'design') {
    ctx.strokeStyle = '#f4f1e8';
    ctx.lineWidth = Math.max(2, map.width / 700);
    const [x0, y0, x1, y1] = label.box;
    ctx.strokeRect(x0 + 1, y0 + 1, x1 - x0 - 2, y1 - y0 - 2);
    const spot = current.meta.unviewable || {};
    if (spot.ranges?.length) {
      ctx.strokeStyle = '#ff9fa8';
      ctx.lineWidth = Math.max(2, map.width / 420);
      ctx.strokeRect(1, 1, map.width - 2, map.height - 2);
    }
  }
  const point = current.first || current.pin;
  if (!point) return;
  const [x, y] = point;
  const arm = Math.max(7, map.width / 105);
  ctx.strokeStyle = '#ffffff';
  ctx.beginPath();
  ctx.moveTo(x - arm, y);
  ctx.lineTo(x + arm, y);
  ctx.moveTo(x, y - arm);
  ctx.lineTo(x, y + arm);
  ctx.stroke();
  ctx.strokeStyle = '#121b1b';
  ctx.strokeRect(x - arm, y - arm, arm * 2, arm * 2);
}

async function paint() {
  const sequence = ++current.drawing;
  const settings = current.saved?.settings || current.settings;
  let source = sourceUrl(current.view === 'design' ? 'design' : settings.light);
  let marker;
  if (current.view === 'marked') {
    if (current.saved) {
      source = reportUrl('/overlay.png');
    } else {
      const reply = await response(endpoint('/preview.png'), 'POST', snapshot());
      marker = URL.createObjectURL(await reply.blob());
      source = marker;
    }
  }
  const picture = new Image();
  picture.src = source;
  try {
    await picture.decode();
  } finally {
    if (marker) URL.revokeObjectURL(marker);
  }
  if (sequence !== current.drawing) return;
  current.image = picture;
  drawMap();
}

function renderArchive() {
  const holder = byId('archive');
  holder.replaceChildren();
  if (!current.panel.reports.length) {
    const empty = document.createElement('p');
    empty.textContent = '目前没有保存的检查。';
    holder.append(empty);
  }
  for (const report of current.panel.reports) {
    const button = document.createElement('button');
    button.className = 'archive-row';
    const date = document.createElement('small');
    date.textContent = new Date(report.created).toLocaleString('zh-CN', {hour12: false});
    button.append(report.heading, date);
    selected(button, report.id === current.saved?.id);
    button.onclick = safe(() => openReport(report.id));
    holder.append(button);
  }
}

function renderHeader() {
  const panel = current.panel;
  const settings = current.saved?.settings || current.settings;
  const sources = current.saved?.sources || panel.sources;
  byId('title').textContent = panel.title;
  const details = [panel.width + ' × ' + panel.height + ' px'];
  if (panel.synthetic) details.push('合成图像');
  if (sources.b) details.push(sources.b.prepared ? '灯 B 来自照片准备' : '双灯照片');
  details.push(current.config.lights[settings.light]);
  byId('metadata').textContent = details.join(' · ');
  byId('prepare').href = '/prepare?panel=' + panel.id;
  byId('source').href = sourceUrl(settings.light, true);
  byId('desk').hidden = false;
  byId('empty').hidden = true;
  byId('result').hidden = false;
  for (const button of document.querySelectorAll('[data-light]')) {
    selected(button, button.dataset.light === settings.light);
    button.disabled = Boolean(current.saved) || !sources[button.dataset.light];
  }
  for (const button of document.querySelectorAll('[data-view]')) selected(button, button.dataset.view === current.view);
  for (const button of document.querySelectorAll('[data-tool]')) {
    selected(button, button.dataset.tool === current.tool);
    button.disabled = Boolean(current.saved) && button.dataset.tool !== 'point';
  }
  for (const key of inputKeys) {
    byId(key).value = settings[key];
    byId(key).disabled = Boolean(current.saved);
  }
  const label = settings.label || {};
  byId('label-width').value = label.width_mm;
  byId('label-clearance').value = label.clearance_mm;
  byId('label-width').disabled = Boolean(current.saved);
  byId('label-clearance').disabled = Boolean(current.saved);
  for (const button of document.querySelectorAll('[data-mode]')) {
    selected(button, button.dataset.mode === current.mode);
    button.disabled = Boolean(current.saved);
  }
  byId('retain-settings').disabled = Boolean(current.saved);
  byId('save').hidden = Boolean(current.saved);
  byId('return-current').hidden = !current.saved;
  byId('exports').hidden = !current.saved;
  if (current.saved) {
    byId('csv').href = reportUrl('/report.csv');
    byId('overlay').href = reportUrl('/overlay.png?download=1');
  }
  renderArchive();
}

function display(value, key) {
  if (value === null) return '—';
  if (key === 'expected') return value ? '应烫箔' : '留白';
  if (key === 'foil') return value ? '检测到箔色' : '低于门槛';
  return String(value);
}

function renderResult(report) {
  byId('result-heading').textContent = report.heading;
  const [x0, y0, x1, y1] = report.settings.inspect;
  const note = [current.config.lights[report.settings.light], '窗 ' + (x1 - x0) + ' × ' + (y1 - y0) + ' px'];
  if (report.meta.component_count !== undefined) note.push(report.meta.component_count + ' 个斑块');
  if (report.mode === 'leaks' && report.meta.label) {
    note.push('贴位 ' + report.meta.label.x0 + '–' + report.meta.label.x1 + ' px');
  }
  if (current.saved) note.push('已存档');
  byId('result-note').textContent = note.join(' · ');
  const keys = Object.keys(report.rows[0] || {}).filter(key => key !== 'box');
  const header = document.createElement('tr');
  for (const key of keys) {
    const cell = document.createElement('th');
    cell.scope = 'col';
    cell.textContent = columns[key] || key;
    header.append(cell);
  }
  byId('columns').replaceChildren(header);
  const body = document.createDocumentFragment();
  for (const row of report.rows) {
    const entry = document.createElement('tr');
    for (const key of keys) {
      const cell = document.createElement('td');
      cell.textContent = display(row[key], key);
      entry.append(cell);
    }
    if (row.x !== undefined && row.y !== undefined) {
      entry.dataset.sample = 'yes';
      entry.tabIndex = 0;
      entry.onclick = safe(() => inspectPoint(row.x, row.y));
      entry.onkeydown = safe(event => {
        if (event.key === 'Enter') return inspectPoint(row.x, row.y);
      });
    }
    body.append(entry);
  }
  byId('rows').replaceChildren(body);
  byId('empty-rows').hidden = Boolean(report.rows.length);
}

async function refresh() {
  const sequence = ++current.computing;
  renderHeader();
  const computing = current.saved ? null : json(endpoint('/preview'), 'POST', snapshot());
  const report = await (computing || Promise.resolve(current.saved));
  if (sequence !== current.computing) return;
  current.meta = report.meta;
  renderResult(report);
  renderPlacement(report.meta);
  await paint();
}

async function refreshLibrary() {
  const records = await json('/foil/panels');
  const holder = byId('library');
  holder.replaceChildren();
  for (const panel of records) {
    const button = document.createElement('button');
    button.textContent = panel.title;
    selected(button, panel.id === current.panel?.id);
    button.onclick = safe(async () => {
      await openPanel(panel.id);
      status('已打开印样。');
    });
    holder.append(button);
  }
  return records;
}

async function activate(panel) {
  current.opening++;
  current.reading++;
  current.panel = panel;
  current.settings = structuredClone(panel.settings);
  current.mode = 'coverage';
  current.view = 'marked';
  current.first = null;
  current.pin = null;
  current.saved = null;
  current.image = null;
  current.meta = null;
  current.tool = 'point';
  map.width = panel.width;
  map.height = panel.height;
  localStorage.setItem('foilbench-panel', panel.id);
  announceMap(directions.point);
  await Promise.all([refreshLibrary(), refresh()]);
}

async function openPanel(id) {
  const sequence = ++current.opening;
  const panel = await json('/foil/panels/' + id);
  if (sequence === current.opening) await activate(panel);
}

async function openReport(id) {
  const sequence = ++current.opening;
  const report = await json(endpoint('/reports/' + id));
  if (sequence !== current.opening) return;
  current.saved = report;
  current.mode = report.mode;
  current.meta = report.meta;
  current.view = 'marked';
  current.pin = null;
  current.first = null;
  current.tool = 'point';
  current.reading++;
  announceMap('点图面可核对存档使用的源像素。');
  await refresh();
  status('已打开保存的检查。');
}

async function inspectPoint(x, y) {
  const sequence = ++current.reading;
  current.pin = [x, y];
  drawMap();
  const chosen = current.saved ? {report: current.saved.id} : {settings: current.settings};
  const sample = await json(endpoint('/point'), 'POST', {...chosen, point: [x, y]});
  if (sequence !== current.reading) return;
  const description = ['源像素 (' + sample.x + ', ' + sample.y + ')', current.config.lights[sample.light],
    'RGB ' + sample.rgb.join(' / '), '箔色 ' + sample.score, sample.classification];
  announceMap(description.join(' · '));
}

function pointOnMap(event) {
  const bounds = map.getBoundingClientRect();
  const x = (event.clientX - bounds.left - map.clientLeft) * map.width / map.clientWidth;
  const y = (event.clientY - bounds.top - map.clientTop) * map.height / map.clientHeight;
  return [Math.max(0, Math.min(map.width - 1, Math.floor(x))), Math.max(0, Math.min(map.height - 1, Math.floor(y)))];
}

map.onclick = safe(async event => {
  const point = pointOnMap(event);
  if (current.tool === 'point') return inspectPoint(...point);
  if (!current.first) {
    current.first = point;
    drawMap();
    announceMap('已选择第一点。请在图面选择第二点。');
    return;
  }
  const [x0, y0] = current.first;
  const [x1, y1] = point;
  const tool = current.tool;
  const rect = [Math.min(x0, x1), Math.min(y0, y1), Math.max(x0, x1) + 1, Math.max(y0, y1) + 1];
  current.settings[tool] = tool === 'line' ? [x0, y0, x1, y1] : rect;
  if (tool === 'inspect') {
    current.settings.label = current.settings.label || {};
    current.settings.label.x = null;
  }
  current.first = null;
  current.pin = null;
  current.tool = 'point';
  announceMap('已更新' + current.config.tools[tool] + '。' + directions.point);
  await refresh();
});

for (const button of document.querySelectorAll('[data-tool]')) {
  button.onclick = safe(() => {
    current.first = null;
    current.pin = null;
    current.tool = button.dataset.tool;
    current.reading++;
    announceMap(directions[current.tool]);
    renderHeader();
    drawMap();
  });
}

for (const button of document.querySelectorAll('[data-light]')) {
  button.onclick = safe(async () => {
    current.settings.light = button.dataset.light;
    current.reading++;
    announceMap(directions[current.tool]);
    await refresh();
  });
}

for (const button of document.querySelectorAll('[data-view]')) {
  button.onclick = safe(async () => {
    current.view = button.dataset.view;
    renderHeader();
    await paint();
  });
}

for (const key of inputKeys) {
  byId(key).onchange = safe(async () => {
    const field = byId(key);
    if (!field.value || !field.checkValidity()) throw Error('请检查设置的数值范围。');
    current.settings[key] = Number(field.value);
    current.reading++;
    announceMap(directions[current.tool]);
    await refresh();
  });
}

for (const key of ['label-width', 'label-clearance']) {
  byId(key).onchange = safe(async () => {
    const field = byId(key);
    if (!field.value || !field.checkValidity()) throw Error('请检查贴位宽度和净距的数值范围。');
    current.settings.label = current.settings.label || {};
    current.settings.label[key === 'label-width' ? 'width_mm' : 'clearance_mm'] = Number(field.value);
    current.reading++;
    await refresh();
  });
}

byId('label-apply').onclick = safe(async () => {
  const label = current.meta?.label;
  if (!label || label.adopted) throw Error('当前检查窗内还没有可采用的贴位建议。');
  current.settings.label = current.settings.label || {};
  current.settings.label.x = label.x0;
  await refresh();
  status('已采用贴位 X ' + label.x0 + '–' + label.x1 + ' px，检查窗保持不变。');
});

byId('demo').onclick = safe(async () => {
  await activate(await json('/foil/demo', 'POST'));
  status('已打开合成练习。');
});

byId('retain-settings').onclick = safe(async () => {
  const panel = await json(endpoint('/settings'), 'PUT', snapshot());
  if (current.panel.id !== panel.id) return;
  current.panel = panel;
  await refresh();
  status('已保留检查设置。');
});

byId('save').onclick = safe(async () => {
  const {panel, report} = await json(endpoint('/reports'), 'POST', snapshot());
  if (current.panel.id !== panel.id) return;
  current.panel = panel;
  await openReport(report.id);
  status('已保存检查。');
});

byId('return-current').onclick = safe(async () => {
  current.saved = null;
  current.pin = null;
  current.meta = null;
  current.reading++;
  announceMap(directions.point);
  await refresh();
  status('已返回当前检查。');
});

const dialog = byId('import-dialog');
byId('open-import').onclick = () => { byId('import-error').textContent = ''; dialog.showModal(); };
byId('close-import').onclick = () => dialog.close();
byId('import-form').onsubmit = async event => {
  event.preventDefault();
  const form = event.currentTarget;
  event.submitter.disabled = true;
  try {
    const panel = await json('/foil/panels', 'POST', new FormData(form));
    dialog.close();
    form.reset();
    await activate(panel);
    status('已导入印样。');
  } catch (error) {
    byId('import-error').textContent = error.message;
  } finally {
    event.submitter.disabled = false;
  }
};

safe(async () => {
  current.config = await json('/foil/config');
  for (const [mode, label] of Object.entries(current.config.modes)) {
    const modeButton = document.createElement('button');
    modeButton.textContent = label;
    modeButton.dataset.mode = mode;
    modeButton.onclick = safe(async () => {
      current.mode = mode;
      await refresh();
    });
    byId('modes').append(modeButton);
  }
  const items = await refreshLibrary();
  const remembered = localStorage.getItem('foilbench-panel');
  if (items.length) await activate(items.find(item => item.id === remembered) || items[0]);
})();
