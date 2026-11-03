import { runQuantizationBenchmark } from './benchmark.mjs';

const $ = id => document.getElementById(id);
const number = (value, digits = 2) => Number.isFinite(value) ? value.toFixed(digits) : '—';
let exportText = null, exportRunId = null;
function cell(row, text, tag = 'td') {
  const element = document.createElement(tag); element.textContent = text; row.append(element);
}
function render(report) {
  exportText = JSON.stringify(report, null, 2);
  exportRunId = report.runId;
  $('raw').textContent = exportText;
  $('export').disabled = false;
  $('export-status').textContent = '原始记录已生成，可导出。';
  const table = document.createElement('table'), head = document.createElement('tr');
  for (const title of ['模式 / 状态', '模型总字节', 'Recall@5', 'nDCG@5', '后两轮结果准备中位数 ms', '后两轮展示中位数 ms', '批量 4 / 1 耗时加速比']) cell(head, title, 'th');
  table.append(head);
  for (const mode of report.modes) {
    const row = document.createElement('tr');
    cell(row, `${mode.id} / ${mode.status}${mode.error ? `：${mode.error.message}` : ''}`);
    cell(row, mode.modelAssets?.totalBytes?.toLocaleString() ?? '—');
    cell(row, number(mode.summary?.quality.macroRecallAt5, 3));
    cell(row, number(mode.summary?.quality.macroNdcgAt5, 3));
    cell(row, number(mode.summary?.subsequentQueryTrials.medianEndToEndReadyMs));
    cell(row, number(mode.summary?.subsequentQueryTrials.medianEndToEndDisplayMs));
    cell(row, number(mode.summary?.batch4WallTimeSpeedup));
    table.append(row);
  }
  $('summary').replaceChildren(table);
  $('pairs').textContent = report.comparisons.map(pair => pair.status === 'same-backend-pair'
    ? `${pair.baselineId} → ${pair.candidateId}：体积压缩 ${number(pair.modelTotalBytesCompressionRatio)} 倍，Recall 差 ${number(pair.recallAt5Delta, 3)}，nDCG 差 ${number(pair.ndcgAt5Delta, 3)}，查询中位数比 ${number(pair.subsequentQueryEndToEndMedianRatio)} 倍。`
    : `${pair.baselineId} / ${pair.candidateId}：比较不可用。`).join(' ');
}
$('export').addEventListener('click', () => {
  if (exportText === null || !exportRunId || $('export').disabled) return;
  let url, anchor;
  try {
    const blob = new Blob([exportText], { type: 'application/json;charset=utf-8' });
    url = URL.createObjectURL(blob);
    anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `stepfun-benchmark-${exportRunId}.json`;
    document.body.append(anchor);
    anchor.click();
    $('export-status').textContent = '已发起下载，请核对浏览器下载列表。';
  } catch {
    $('export-status').textContent = '未能发起下载，原始记录仍保留在本页。';
  } finally {
    anchor?.remove();
    if (url) setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
});
$('start').addEventListener('click', async () => {
  $('start').disabled = true;
  $('export').disabled = true;
  $('export-status').textContent = '';
  exportText = null; exportRunId = null;
  try {
    const report = await runQuantizationBenchmark({
      onProgress: text => { $('stage').textContent = text; },
      onResults(results, meta) {
        $('query-label').textContent = `${meta.modeId} · ${meta.queryId} · 第 ${meta.repeat} 次`;
        const articles = results.map(result => {
          const article = document.createElement('article'), title = document.createElement('h3'), text = document.createElement('p');
          title.textContent = result.id; text.textContent = result.text; article.append(title, text); return article;
        });
        $('current-results').replaceChildren(...articles);
      },
    });
    render(report);
    $('stage').textContent = `运行状态：${report.status}；${report.finishedAt}${report.error ? `；${report.error.message}` : ''}`;
  } catch (error) {
    $('stage').textContent = `未完成：${error.message}`;
  } finally { $('start').disabled = false; }
});
