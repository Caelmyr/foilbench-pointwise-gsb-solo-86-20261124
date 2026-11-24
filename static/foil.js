'use strict';

const byId = id => document.getElementById(id);
const map = byId('map');
const ctx = map.getContext('2d');
const current = {
  panel: null, settings: null, config: null, mode: 'coverage', view: 'marked',
  tool: 'point', first: null, pin: null, saved: null, image: null,
  suggestion: null, previewing: false,
  drawing: 0, computing: 0, reading: 0, opening: 0,
};
const columns = {
  expected_px: '版图像素', transfer_px: '转移像素', gap_px: '缺箔像素', coverage_pct: '覆盖 %',
  expected_mm2: '版图 mm²', gap_mm2: '缺箔 mm²', out_of_frame_px: '画面外像素',
  out_of_frame_mm2: '画面外 mm²', captured: '画面内', index: '序号', pixels: '像素数',
  area_mm2: '面积 mm²', width_mm: '宽 mm', height_mm: '高 mm', x: '源 X', y: '源 Y',
  distance_mm: '距离 mm', score: '箔色', expected: '版图', foil: '照片', reference: '参照',
  low_score: '第 10 百分位', median_score: '中位数', high_score: '第 90 百分位',
  foil_pct: '检出 %', lower: '下界', upper: '上界', die_px: '版图像素', paper_px: '留白像素',
};
const directions = {point: '点图面可读源照片像素。', inspect: '点选检查窗的两个角。',
  gold: '圈一处已确认转移的箔色作为参照。', paper: '圈一处确认留白的纸色作为参照。',
  line: '在图面上点选剖线的两端。'};
const inputKeys = ['threshold', 'mm_per_pixel', 'min_pixels'];

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

function shiftText(pair) {
  const [dx, dy] = pair;
  const parts = [];
  if (dx > 0) parts.push('右 ' + dx + ' px');
  if (dx < 0) parts.push('左 ' + (-dx) + ' px');
  if (dy > 0) parts.push('下 ' + dy + ' px');
  if (dy < 0) parts.push('上 ' + (-dy) + ' px');
  return parts.length ? parts.join(' · ') : '无需平移';
}

function renderShiftPanel() {
  const box = byId('shift-box');
  if (!current.panel || current.saved) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  const shift = current.settings.shift || [0, 0];
  const adopted = Boolean(shift[0] || shift[1]);
  const suggestion = current.suggestion;
  byId('find-shift').disabled = adopted;
  const panel = byId('shift-panel');
  if (!suggestion && !adopted) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  const lines = [];
  if (adopted) {
    lines.push('已采用：版图' + shiftText(shift) + '。覆盖率与读单点按对齐后计算，画面外边缘不计入。');
  } else {
    lines.push('建议：版图' + shiftText(suggestion.shift) + '（按' +
      current.config.lights[suggestion.light] + '，横竖 ±' + suggestion.limit + ' px 内）。');
  }
  if (suggestion) {
    const parts = [];
    if (suggestion.main) {
      parts.push('主要图案还差 ' + suggestion.main.mismatch_px + ' px（' + suggestion.main.mismatch_pct + '%）');
    }
    if (suggestion.fine) {
      parts.push('细小图案还差 ' + suggestion.fine.mismatch_px + ' px（' + suggestion.fine.mismatch_pct + '%）');
    }
    if (parts.length) lines.push(parts.join('，') + '。');
    if (suggestion.main && suggestion.fine && !suggestion.agree) {
      lines.push('两处各自最优不同（主要：' + shiftText(suggestion.main.best_shift) +
        '；细小：' + shiftText(suggestion.fine.best_shift) + '），已等重折中，未让大块色面单独决定。');
    }
    if (!suggestion.fine) lines.push('检查窗内分不出细小图案，仅按主要图案评估。');
  }
  byId('shift-note').textContent = lines.join('\n');
  byId('preview-shift').hidden = !suggestion || adopted;
  byId('preview-shift').textContent = current.previewing ? '取消预览' : '预览';
  byId('adopt-shift').hidden = !suggestion || adopted;
  byId('drop-shift').hidden = !suggestion || adopted;
  byId('revert-shift').hidden = !adopted;
}

function clearSuggestion() {
  if (!current.suggestion && !current.previewing) return;
  current.suggestion = null;
  current.previewing = false;
  renderShiftPanel();
}

function drawMap() {
  if (!current.image) return;
  ctx.drawImage(current.image, 0, 0, map.width, map.height);
  ctx.strokeStyle = '#a6eddf';
  ctx.lineWidth = Math.max(1, map.width / 800);
  ctx.setLineDash([6, 4]);
  const options = current.saved?.settings || current.settings;
  if (current.view !== 'marked' && !current.previewing) {
    const [x0, y0, x1, y1] = options.inspect;
    ctx.strokeRect(x0 + 1, y0 + 1, x1 - x0 - 2, y1 - y0 - 2);
  }
  ctx.setLineDash([]);
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
  if (current.previewing && current.suggestion && !current.saved) {
    const reply = await response(endpoint('/registration.png'), 'POST',
      {settings: current.settings, shift: current.suggestion.shift});
    marker = URL.createObjectURL(await reply.blob());
    source = marker;
  } else if (current.view === 'marked') {
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
  renderShiftPanel();
  renderArchive();
}

function display(value, key) {
  if (value === null) return '—';
  if (key === 'expected') return value ? '应烫箔' : '留白';
  if (key === 'foil') return value ? '检测到箔色' : '低于门槛';
  if (key === 'captured') return value ? '画面内' : '画面外';
  return String(value);
}

function renderResult(report) {
  byId('result-heading').textContent = report.heading;
  const [x0, y0, x1, y1] = report.settings.inspect;
  const note = [current.config.lights[report.settings.light], '窗 ' + (x1 - x0) + ' × ' + (y1 - y0) + ' px'];
  const shift = report.settings.shift || [0, 0];
  if (shift[0] || shift[1]) note.push('版图平移 ' + shiftText(shift));
  if (report.meta.component_count !== undefined) note.push(report.meta.component_count + ' 个斑块');
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
  const compute = current.saved || json(endpoint('/preview'), 'POST', snapshot());
  const [report] = await Promise.all([compute, paint()]);
  if (sequence === current.computing) renderResult(report);
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
  current.settings.shift = current.settings.shift || [0, 0];
  current.mode = 'coverage';
  current.view = 'marked';
  current.first = null;
  current.pin = null;
  current.saved = null;
  current.image = null;
  current.suggestion = null;
  current.previewing = false;
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
  current.view = 'marked';
  current.pin = null;
  current.first = null;
  current.suggestion = null;
  current.previewing = false;
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
  const description = ['源像素 (' + sample.x + ', ' + sample.y + ')'];
  if (sample.plate_x !== undefined && sample.plate_x !== null) {
    description.push('版图 (' + sample.plate_x + ', ' + sample.plate_y + ')');
  }
  description.push(current.config.lights[sample.light], 'RGB ' + sample.rgb.join(' / '),
    '箔色 ' + sample.score, sample.classification);
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
  current.first = null;
  current.pin = null;
  current.tool = 'point';
  if (tool === 'inspect') clearSuggestion();
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
    clearSuggestion();
    announceMap(directions[current.tool]);
    await refresh();
  });
}

for (const button of document.querySelectorAll('[data-view]')) {
  button.onclick = safe(async () => {
    current.view = button.dataset.view;
    current.previewing = false;
    renderShiftPanel();
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
    if (key === 'threshold') clearSuggestion();
    announceMap(directions[current.tool]);
    await refresh();
  });
}

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

byId('find-shift').onclick = safe(async () => {
  byId('find-shift').disabled = true;
  status('正在检查窗内搜索平移套准…');
  try {
    current.suggestion = await json(endpoint('/registration'), 'POST', {settings: current.settings});
    current.previewing = false;
    status('已得到套准建议，可先预览再采用。');
  } finally {
    renderShiftPanel();
  }
});

byId('preview-shift').onclick = safe(async () => {
  current.previewing = !current.previewing;
  renderShiftPanel();
  await paint();
});

byId('adopt-shift').onclick = safe(async () => {
  current.settings.shift = [...current.suggestion.shift];
  current.previewing = false;
  await refresh();
  status('已采用套准平移。覆盖率与读单点按对齐后计算，画面外边缘不计入。');
});

byId('drop-shift').onclick = safe(async () => {
  current.suggestion = null;
  current.previewing = false;
  renderShiftPanel();
  await paint();
});

byId('revert-shift').onclick = safe(async () => {
  current.settings.shift = [0, 0];
  await refresh();
  status('已撤回套准平移。');
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
