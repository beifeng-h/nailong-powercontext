import { EmbeddingClient } from './embedding-client.mjs';

const $ = id => document.getElementById(id);
const events = [];
let activeModel = null, knowledgeBases = [], busy = false, generation = 0;
const clientCallbacks = {
  onStatus(status) {
    if (status.status === 'ready' && status.backend && status.dtype) {
      const previousModel = activeModel;
      activeModel = status.model || activeModel;
      if (!previousModel || previousModel.precision !== activeModel?.precision) showBases();
      $('model-progress').textContent = '模型已就绪，可在本地使用';
      $('backend').textContent = `${status.backend.toUpperCase()} · ${status.dtype.toUpperCase()}`;
    }
    if (status.status === 'fallback') $('model-progress').textContent = 'GPU 推理不可用，正在加载独立 WASM 后端…';
    if (status.status === 'failed') {
      activeModel = null;
      $('backend').textContent = '模型未就绪';
      $('model-progress').textContent = status.error || '本地模型加载失败';
      showBases();
    }
  },
  onProgress(progress) {
    if (progress.phase === 'embedding') {
      $('model-progress').textContent = `已在本地向量化 ${progress.completed} / ${progress.total} 篇`;
    } else {
      const detail = progress.detail || progress;
      const value = Number(detail.progress);
      $('model-progress').textContent = Number.isFinite(value) ? `正在加载本地模型 ${value.toFixed(0)}%` : (detail.status || '正在加载本地模型');
    }
  },
};
let client = new EmbeddingClient(clientCallbacks);

function record(type, detail) {
  events.push({ at: new Date().toISOString(), type, ...detail });
  $('events').textContent = JSON.stringify(events, null, 2);
}
function message(text, error = false) { $('message').textContent = text; $('message').className = error ? 'error' : ''; }
function lock(value) {
  busy = value;
  for (const element of document.querySelectorAll('button,input,select,textarea')) element.disabled = value;
}
async function action(job) {
  if (busy) return;
  lock(true);
  try { await job(); } catch (error) { message(error.message || '操作失败', true); record('error', { message: error.message || 'operation failed' }); }
  finally { lock(false); }
}
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error?.message || result.error || '本地数据库操作失败');
  return result;
}
function selectedKB() {
  const kb = knowledgeBases.find(item => item.id === $('kb').value);
  if (!kb) throw new Error('请选择或新建当前精度的知识库');
  return kb;
}
function clearSearchView() {
  generation++;
  $('results').replaceChildren();
  $('search-timing').textContent = '';
}
function showBases() {
  clearSearchView();
  const selected = $('kb').value;
  const compatible = knowledgeBases.filter(kb => kb.profile === activeModel?.precision);
  $('kb').replaceChildren();
  const empty = document.createElement('option'); empty.value = ''; empty.textContent = compatible.length ? '请选择知识库' : '当前精度暂无知识库'; $('kb').append(empty);
  for (const kb of compatible) {
    const option = document.createElement('option'); option.value = kb.id; option.textContent = `${kb.label} · ${kb.profile}`; $('kb').append(option);
  }
  if (compatible.some(kb => kb.id === selected)) $('kb').value = selected;
}
async function loadModel() {
  const state = await client.init($('mode').value);
  activeModel = state.model;
  $('backend').textContent = `${state.backend.toUpperCase()} · ${state.dtype.toUpperCase()}`;
  $('model-progress').textContent = '模型已在浏览器就绪';
  showBases(); record('model-ready', state);
  return state;
}
async function ensureModel() { if (!activeModel) await loadModel(); }
async function importDocuments(documents) {
  await ensureModel();
  const kb = selectedKB();
  const texts = documents.map(doc => doc.text);
  message(`正在本地向量化 ${texts.length} 篇文档…`);
  const vectors = await client.embed(texts, { batchSize: 4 });
  activeModel = vectors.model;
  if (kb.profile !== activeModel.precision) { showBases(); throw new Error('模型已自动降级，请选择或新建当前精度的知识库后重新导入'); }
  const result = await api(`/api/kbs/${encodeURIComponent(kb.id)}/import`, {
    documents, embeddings: vectors.embeddings, model: activeModel,
  });
  record('import', { kb: kb.id, documents: documents.map(doc => doc.id), embeddingMs: vectors.elapsedMs, ...result });
  message(`已写入并刷新 ${documents.length} 篇文档，知识库版本 ${result.revision}`);
}
function renderResults(results) {
  $('results').replaceChildren();
  if (!results.length) { $('results').textContent = '没有匹配结果'; return; }
  for (const [index, result] of results.entries()) {
    const article = document.createElement('article'); article.className = 'result';
    const title = document.createElement('h3'); title.textContent = `${index + 1}. ${result.id}`;
    const text = document.createElement('p'); text.textContent = result.text;
    const meta = document.createElement('small'); meta.textContent = JSON.stringify(result.metadata || {});
    article.append(title, text, meta); $('results').append(article);
  }
}
$('load-model').addEventListener('click', () => action(loadModel));
$('mode').addEventListener('change', () => { clearSearchView(); activeModel = null; client.close(); client = new EmbeddingClient(clientCallbacks); $('kb').value = ''; $('backend').textContent = '模式已切换，请加载本地模型'; });
$('kb').addEventListener('change', clearSearchView);
$('create-kb').addEventListener('click', () => action(async () => {
  await ensureModel();
  const label = $('kb-name').value.trim(); if (!label) throw new Error('请填写知识库名称');
  const kb = await api('/api/kbs', { label, profile: activeModel.precision });
  knowledgeBases.push(kb); showBases(); $('kb').value = kb.id; generation++;
  record('kb-created', kb); message(`已建立 ${kb.label}`);
}));
$('import-text').addEventListener('click', () => action(async () => {
  const text = $('doc-text').value.trim(), id = $('doc-id').value.trim();
  if (!text || !id) throw new Error('请填写文档 ID 和原文');
  await importDocuments([{ id, text, metadata: { source: 'typed-text' } }]);
}));
$('files').addEventListener('change', () => action(async () => {
  const files = [...$('files').files]; if (!files.length) return;
  if (files.length > 24 || files.some(file => file.size > 128 * 1024)) throw new Error('一次最多导入24个不超过128KB的文本文件');
  const documents = await Promise.all(files.map(async file => ({ id: file.name, text: await file.text(), metadata: { source: file.name } })));
  await importDocuments(documents); $('files').value = '';
}));
$('import-sample').addEventListener('click', () => action(async () => {
  const response = await fetch('/fixtures/corpus.json');
  if (!response.ok) throw new Error('合成样例尚未安装');
  const corpus = await response.json();
  await importDocuments(corpus.documents.filter(doc => doc.knowledgeBase === 'harbor').map(({ id, text, ...metadata }) => ({ id, text, metadata })));
}));
$('search-form').addEventListener('submit', event => {
  event.preventDefault();
  action(async () => {
    await ensureModel(); const kb = selectedKB(), token = ++generation;
    const text = $('query').value.trim(); if (!text) throw new Error('请输入查询');
    const start = performance.now(); const embedded = await client.embed([text], { batchSize: 1 });
    activeModel = embedded.model;
    if (kb.profile !== activeModel.precision) { showBases(); throw new Error('模型已降级，请选择当前精度的知识库'); }
    const result = await api(`/api/kbs/${encodeURIComponent(kb.id)}/search`, { text, embedding: embedded.embeddings[0], model: activeModel, topK: 5 });
    if (token !== generation || $('kb').value !== kb.id) return;
    renderResults(result.results);
    const endToEndMs = performance.now() - start;
    $('search-timing').textContent = `本地向量化 ${embedded.elapsedMs.toFixed(1)} ms · seekdb ${result.queryMs.toFixed(1)} ms · 端到端 ${endToEndMs.toFixed(1)} ms`;
    record('search', { kb: kb.id, text, ids: result.results.map(item => item.id), embeddingMs: embedded.elapsedMs, queryMs: result.queryMs, endToEndMs });
    message('结果由 seekdb 混合检索返回，按数据库次序展示');
  });
});
$('export-log').addEventListener('click', () => {
  const blob = new Blob([JSON.stringify({ version: 1, userAgent: navigator.userAgent, events }, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob), anchor = document.createElement('a'); anchor.href = url; anchor.download = 'stepfun-local-run.json'; anchor.click(); URL.revokeObjectURL(url);
});
try {
  const health = await api('/api/health'); $('db-status').textContent = `seekdb 已连接 · ${health.databaseVersion}`;
  const existing = await api('/api/kbs'); knowledgeBases = existing.kbs; record('database-ready', health);
} catch (error) { $('db-status').textContent = '本地数据库尚未就绪'; message(error.message, true); }
