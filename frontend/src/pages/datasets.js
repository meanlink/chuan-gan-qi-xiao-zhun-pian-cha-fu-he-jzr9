import {datasets,stations} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {table} from '../components/common/table.js';
import {esc,notify} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';
import {parseCSV} from '../utils/csv.js';

let stationCode = '';
// 发布后整页会刷新；把刚收到的核对结果带到新页面，避免差异明细被清空。
let pendingResult = null;

function diffPanel(diff, label) {
  if (!diff) return '<p class="empty">暂无对比。首次发布的快照会显示本代全部读数。</p>';
  const c = diff.counts || {added: 0, modified: 0, revoked: 0, unchanged: 0};
  const block = (title, items, render) => {
    if (!items?.items?.length) return '<div class="diff-block"><h4>' + esc(title) + ' · 0</h4><p class="hint">无变化。</p></div>';
    return '<div class="diff-block"><h4>' + esc(title) + ' · ' + items.items.length + (items.truncated ? '（仅显示前 ' + items.items.length + ' 条）' : '') + '</h4>' + table(render.columns, items.items.map(render.map)) + '</div>';
  };
  return '<div class="diff-summary">' +
    [['新增', c.added], ['修改', c.modified], ['撤销', c.revoked], ['未变', c.unchanged]].map(([k, v]) =>
      '<div><span>' + esc(k) + '</span><strong>' + v + '</strong></div>').join('') + '</div>' +
    '<p class="hint">' + esc(label || '') + '</p>' +
    '<div class="diff-blocks">' +
    block('新增读数', diff.added, {columns: workspace.meta.columns.map(c => ({key: c.key, label: c.label})), map: r => r}) +
    block('修改读数', diff.modified, {columns: [{key: 'sample', label: '读数编号'}, {key: 'before', label: '修改前'}, {key: 'after', label: '修改后'}], map: r => ({sample: r.sample, before: JSON.stringify({band: r.before.band, reference: r.before.reference, measured: r.before.measured}), after: JSON.stringify({band: r.after.band, reference: r.after.reference, measured: r.after.measured})})}) +
    block('撤销读数', diff.revoked, {columns: workspace.meta.columns.map(c => ({key: c.key, label: c.label})), map: r => r}) +
    '</div>';
}

export async function dataPage(){
  const [batchList, stationList] = await Promise.all([datasets.list(), stations.list()]);
  workspace.datasets = batchList;
  workspace.stations = stationList;
  if (!stationCode || !stationList.some(s => s.code === stationCode)) stationCode = stationList[0]?.code || '';
  let station = null, current = null;
  if (stationCode) {
    [station, current] = await Promise.all([stations.get(stationCode), stations.current(stationCode)]);
  }
  workspace.station = station;
  const stationOptions = stationList.map(s => '<option value="' + esc(s.code) + '" ' + (s.code === stationCode ? 'selected' : '') + '>' + esc(s.name) + ' · 代号 ' + s.current_generation + '</option>').join('');
  const pending = station?.pending || [];
  const canWrite = session.user.role !== 'viewer';
  return heading('02 / DATA INTAKE','站点台账快照接收','每日全量台账按站点与递增代号接收。整份替换本站台账，消失的读数退出后续分析；其他站不受影响。') +
    '<div class="dataset-grid"><section class="panel">' +
    '<div class="section-title"><h2>当前台账</h2><span>' + stationList.length + ' 个站点</span></div>' +
    (stationList.length ? '<div class="station-switch"><label>选择站点<select id="station-select">' + stationOptions + '</select></label></div>' : '<p class="empty">尚无站点。提交第一份快照即建立站点。</p>') +
    (station ? '<div class="station-card"><div><span>站点</span><strong>' + esc(station.name) + ' · ' + esc(station.code) + '</strong></div>' +
      '<div><span>当前代号</span><strong>' + station.current_generation + '</strong></div>' +
      '<div><span>当前读数</span><strong>' + station.rows + '</strong></div>' +
      '<div><span>台账指纹</span><strong class="mono">' + esc((station.current_checksum || '—').slice(0, 18)) + '…</strong></div></div>' +
      (pending.length ? '<div class="warning">待完成接入：' + pending.map(p => '代号 ' + p.generation + '（' + p.progress + '/' + p.row_count + ' 条）').join('，') + '。以相同内容重试即可续传，不会新增批次。</div>' : '') : '') +
    '<div class="batch-list"><div class="section-title"><h2>已发布台账</h2><span>当前代之外的历史代只保留给历史分析</span></div>' +
      (station?.snapshots?.length ? station.snapshots.map(s => '<button class="batch-item" data-generation="' + s.generation + '"><strong>' + esc(station.code) + ' · 代号 ' + s.generation + ' · ' + esc(s.status) + '</strong><span>' + s.row_count + ' 条 · 新增 ' + (s.diff?.counts?.added ?? 0) + ' / 修改 ' + (s.diff?.counts?.modified ?? 0) + ' / 撤销 ' + (s.diff?.counts?.revoked ?? 0) + '</span><small>SHA256 ' + esc((s.checksum || '').slice(0, 18)) + '…</small></button>').join('') : '<p class="empty">尚无已发布快照。</p>') + '</div>' +
    '<div class="section-title"><h2>接入新快照</h2></div>' +
    '<form id="snapshot-form">' +
      '<label>站点代号<input name="station" required minlength="1" maxlength="80" value="' + esc(stationCode) + '" placeholder="例如：WH-A1"></label>' +
      '<label>站点名称<input name="station_name" maxlength="160" placeholder="可选，例如：望衡仪器 · 1 号校准站"></label>' +
      '<label>快照代号<input name="generation" type="number" min="1" step="1" required value="' + (station ? station.current_generation + 1 : 1) + '" placeholder="递增整数"></label>' +
      '<label>上传 CSV 或 JSON<input type="file" id="snapshot-file" accept=".json,.csv"></label>' +
      '<label>台账记录 JSON<textarea name="records" rows="6" placeholder="粘贴全量读数 JSON 数组，或先选择上方文件" required></textarea></label>' +
      '<p class="hint">字段：' + workspace.meta.columns.map(c => esc(c.key) + ' / ' + esc(c.label)).join('，') + '。全量整份，1–5,000 条；同一读数编号不得重复。</p>' +
      '<div class="form-actions"><button type="button" id="dry-run" class="button" ' + (canWrite ? '' : 'disabled') + '>仅校验并预览差异</button><button type="submit" class="primary" ' + (canWrite ? '' : 'disabled') + '>接收并发布新代</button></div>' +
      '<p class="hint">旧代晚到拒收；同代异内容报冲突；同代重试不新增批次；校验或写入失败时本站继续使用旧代。</p>' +
    '</form>' +
    '<div id="snapshot-result"></div>' +
    '</section><section class="panel"><div class="section-title"><h2 id="preview-name">' + esc(station ? station.code + ' · 当前台账预览' : '尚无站点台账') + '</h2><span>预览前 30 条 / 差异明细</span></div>' +
    '<div id="data-preview">' + table(workspace.meta.columns, current?.rows?.slice(0, 30) || [], '尚无台账读数。') + '</div>' +
    '<div id="diff-panel">' + diffPanel(pendingResult ? pendingResult.diff : station?.current_diff, pendingResult ? '刚接收的代号 ' + pendingResult.snapshot.generation + ' 差异。' : (station ? '代号 ' + station.current_generation + ' 相对上一代的变化。' : '')) + '</div>' +
    '</section></div>';
}

function readForm() {
  const form = document.querySelector('#snapshot-form');
  const f = new FormData(form);
  let records;
  try { records = JSON.parse(f.get('records')); }
  catch (e) { throw new Error('台账记录必须是合法 JSON 数组'); }
  if (!Array.isArray(records)) throw new Error('台账记录必须是 JSON 数组');
  return {station: String(f.get('station') || '').trim(), generation: Number(f.get('generation')),
    station_name: String(f.get('station_name') || '').trim(), source: form.dataset.source || 'station-snapshot.json', records};
}

function renderResult(result, dryRun) {
  const box = document.querySelector('#snapshot-result');
  const s = result.snapshot;
  const head = dryRun ? '校验通过 · 尚未发布' : (result.replayed ? '已存在相同快照 · 未新增批次' : '新代已发布');
  box.innerHTML = '<div class="snapshot-result"><div class="section-title"><h2>' + esc(head) + '</h2><span>' + (result.station ? esc(result.station.code) + ' · 当前代号 ' + result.station.current_generation : '') + '</span></div>' +
    (s ? '<p class="hint">代号 ' + s.generation + ' · ' + s.row_count + ' 条 · SHA256 ' + esc(s.checksum.slice(0, 24)) + '…</p>' : '') +
    diffPanel(result.diff, dryRun ? '以下差异将在发布后生效；发布时整份替换本站台账。' : '本站台账已整份替换；其他站点不受影响。') + '</div>';
  const diff = document.querySelector('#diff-panel');
  if (diff && result.diff) diff.innerHTML = diffPanel(result.diff, '代号 ' + (s?.generation ?? '') + ' 的差异明细。');
}

export function bindData(refresh){
  if (pendingResult) {
    renderResult(pendingResult, false);
    pendingResult = null;
  }
  document.querySelector('#station-select')?.addEventListener('change', e => { stationCode = e.target.value; refresh(); });
  document.querySelector('#snapshot-file').addEventListener('change', async e => {
    try {
      const file = e.target.files[0]; if (!file) return;
      const form = document.querySelector('#snapshot-form');
      form.dataset.source = file.name;
      const text = await file.text(), records = file.name.endsWith('.csv') ? parseCSV(text) : JSON.parse(text);
      document.querySelector('[name=records]').value = JSON.stringify(records, null, 2);
    } catch (error) { notify(error.message, true); }
  });
  document.querySelector('#dry-run').onclick = async () => {
    try { const payload = readForm(); renderResult(await stations.receive(payload.station, payload, true), true); }
    catch (error) { notify(error.message, true); }
  };
  submit(document.querySelector('#snapshot-form'), async () => {
    const payload = readForm();
    const result = await stations.receive(payload.station, payload, false);
    stationCode = payload.station;
    renderResult(result, false);
    notify(result.replayed ? '相同快照重复回传，未新增批次' : '新代已发布，站点台账已整份替换');
    if (!result.replayed) { pendingResult = result; await refresh(); }
  });
  document.querySelectorAll('[data-generation]').forEach(button => button.onclick = async () => {
    try {
      const list = await stations.snapshots(stationCode);
      const snap = list.find(s => String(s.generation) === button.dataset.generation);
      if (!snap) return;
      document.querySelector('#preview-name').textContent = stationCode + ' · 代号 ' + snap.generation;
      renderResult({station: workspace.station, snapshot: snap, diff: snap.diff, replayed: false}, snap.status !== 'published');
      document.querySelector('#diff-panel').innerHTML = diffPanel(snap.diff, '代号 ' + snap.generation + ' 的变化。');
    } catch (error) { notify(error.message, true); }
  });
}
