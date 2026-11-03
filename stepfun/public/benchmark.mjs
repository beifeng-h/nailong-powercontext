import { EmbeddingClient } from './embedding-client.mjs';

const K = 5, REPEATS = 3;
const MODES = Object.freeze([
  { id: 'fp32-gpu', clientMode: 'fp32', backend: 'webgpu', dtype: 'fp32' },
  { id: 'fp16-gpu', clientMode: 'fp16', backend: 'webgpu', dtype: 'fp16' },
  { id: 'fp32-wasm', clientMode: 'fp32-wasm', backend: 'wasm', dtype: 'fp32' },
  { id: 'q8-wasm', clientMode: 'q8', backend: 'wasm', dtype: 'q8' },
]);
let running = false;

function fail(message) { throw new Error(message); }
function finite(value, label) {
  if (!Number.isFinite(value) || value < 0) fail(`Invalid ${label}`);
  return value;
}
function mean(values) {
  if (!values.length || values.some(value => !Number.isFinite(value))) fail('Incomplete numeric sample set');
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}
export function median(values) {
  if (!Array.isArray(values) || !values.length || values.some(value => !Number.isFinite(value))) fail('Median requires actual finite samples');
  const ordered = values.slice().sort((a, b) => a - b), middle = Math.floor(ordered.length / 2);
  return ordered.length % 2 ? ordered[middle] : (ordered[middle - 1] + ordered[middle]) / 2;
}
export function scoreRanking(ids, relevantIds, corpusIds, k = K) {
  if (!Array.isArray(ids) || k !== K) fail('Invalid ranking input');
  const allowed = new Set(corpusIds), relevant = new Set(relevantIds);
  if (!relevant.size || relevant.size !== relevantIds.length || [...relevant].some(id => !allowed.has(id))) fail('Invalid complete relevance set');
  if (new Set(ids).size !== ids.length) fail('Integrity error: duplicate result ID');
  if (ids.some(id => !allowed.has(id))) fail('Integrity error: unknown or cross-KB result ID');
  const top = ids.slice(0, k), hits = top.filter(id => relevant.has(id)).length;
  const dcg = top.reduce((sum, id, index) => sum + (relevant.has(id) ? 1 / Math.log2(index + 2) : 0), 0);
  let idcg = 0;
  for (let index = 0; index < Math.min(k, relevant.size); index++) idcg += 1 / Math.log2(index + 2);
  return { k, hits, relevantCount: relevant.size, returnedCount: top.length, recallAt5: hits / relevant.size, ndcgAt5: dcg / idcg };
}
export function completeRound(samples, queryIds, repeat) {
  const rows = samples.filter(sample => sample.repeat === repeat);
  if (rows.length !== queryIds.length || new Set(rows.map(row => row.queryId)).size !== queryIds.length
    || rows.some(row => !queryIds.includes(row.queryId))) fail('Incomplete query round; no partial-success average');
  return { repeat, queryCount: rows.length,
    recallAt5: mean(rows.map(row => row.quality.recallAt5)), ndcgAt5: mean(rows.map(row => row.quality.ndcgAt5)) };
}
export function validateFixtures(corpus, queryFile) {
  if (!Array.isArray(corpus?.documents) || !Array.isArray(queryFile?.queries)) fail('Invalid fixture structure');
  const documents = corpus.documents.filter(doc => doc.knowledgeBase === 'harbor');
  const queries = queryFile.queries;
  const expectedIds = Array.from({ length: 20 }, (_, index) => `H${String(index + 1).padStart(2, '0')}`);
  if (documents.length !== 20 || new Set(documents.map(doc => doc.id)).size !== 20
    || documents.some(doc => !expectedIds.includes(doc.id) || doc.revision !== '1' || typeof doc.text !== 'string' || !doc.text.trim())) fail('Quality corpus must be the frozen Harbor H01-H20 revision 1');
  if (queries.length !== 10 || new Set(queries.map(query => query.id)).size !== 10) fail('Exactly ten fixed queries are required');
  const qrels = {};
  for (const [index, query] of queries.entries()) {
    if (query.id !== `Q${String(index + 1).padStart(2, '0')}` || query.kb_id !== 'harbor'
      || typeof query.query !== 'string' || !query.query.trim() || !Array.isArray(query.relevant_ids)
      || query.relevant_ids.length !== 2 || new Set(query.relevant_ids).size !== 2
      || query.relevant_ids.some(id => !expectedIds.includes(id))) fail('Invalid complete query relevance labels');
    qrels[query.id] = Object.fromEntries(expectedIds.map(id => [id, query.relevant_ids.includes(id) ? 1 : 0]));
  }
  return { documents, queries, qrels, corpusIds: expectedIds };
}

async function hashBytes(bytes) {
  const value = await crypto.subtle.digest('SHA-256', bytes);
  return [...new Uint8Array(value)].map(byte => byte.toString(16).padStart(2, '0')).join('');
}
async function fixture(path) {
  const response = await fetch(path, { cache: 'no-store' });
  if (!response.ok) fail(`Fixture fetch failed: ${path} (${response.status})`);
  const bytes = await response.arrayBuffer();
  return { value: JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)), sha256: await hashBytes(bytes), path };
}
async function api(path, body) {
  const response = await fetch(path, body === undefined ? { cache: 'no-store' } : {
    method: 'POST', cache: 'no-store', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok) fail(result.error?.message || `Local API failed (${response.status})`);
  return result;
}
function assertProfile(value, mode, expectedModel) {
  if (value.backend !== mode.backend || value.dtype !== mode.dtype || value.model?.precision !== mode.dtype) {
    fail(`Mode resolved to ${value.backend}/${value.dtype}, expected ${mode.backend}/${mode.dtype}; no fallback relabelling`);
  }
  const model = value.model;
  if (!model || !Number.isSafeInteger(model.dimension) || model.dimension < 1
    || typeof model.repo !== 'string' || !/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(model.repo)
    || !/^[0-9a-f]{40}$/.test(model.revision) || model.pooling !== 'mean' || model.normalize !== true) fail('Invalid resolved model manifest');
  if (expectedModel && JSON.stringify(model) !== JSON.stringify(expectedModel)) fail('Model manifest changed within one experiment');
}
function embeddingSample(value, wallMs, count, batchSize) {
  if (!Array.isArray(value.embeddings) || value.embeddings.length !== count
    || value.embeddings.some(vector => !Array.isArray(vector) || vector.length !== value.model.dimension
      || vector.some(component => !Number.isFinite(component)))) fail('Invalid actual embedding batch');
  return { textCount: count, batchSize, wallMs: finite(wallMs, 'embedding wall time'),
    elapsedMs: finite(value.elapsedMs, 'client embedding time'), inferenceMs: finite(value.inferenceMs, 'worker inference time'),
    workerElapsedMs: finite(value.workerElapsedMs, 'worker elapsed time'), batches: value.batches,
    throughputTextsPerSecond: wallMs > 0 ? count * 1000 / wallMs : null };
}
async function modelAssets(model) {
  const directory = `/models/${model.revision}/${model.repo.split('/').map(encodeURIComponent).join('/')}/`;
  const onnx = { fp32: 'model.onnx', fp16: 'model_fp16.onnx', q8: 'model_quantized.onnx' }[model.precision];
  if (!onnx) fail('Unknown model asset profile');
  const paths = ['config.json', 'special_tokens_map.json', 'tokenizer.json', 'tokenizer_config.json', 'vocab.txt', `onnx/${onnx}`];
  const files = [];
  for (const relative of paths) {
    const path = directory + relative;
    const response = await fetch(path, { method: 'HEAD', cache: 'no-store' });
    const size = Number(response.headers.get('content-length'));
    if (!response.ok || !Number.isSafeInteger(size) || size <= 0
      || ![null, 'identity'].includes(response.headers.get('content-encoding'))) fail(`Model size metadata unavailable: ${relative}`);
    files.push({ path, bytes: size, basis: 'actual same-origin HEAD Content-Length; not transferred bytes or file hash' });
  }
  return { basis: 'five delivered shared config/tokenizer files plus selected ONNX; excludes JS/WASM runtime', files,
    totalBytes: files.reduce((sum, file) => sum + file.bytes, 0), contentSha256: null };
}
function phaseTimingSummary(samples) {
  const display = samples.map(row => row.endToEndDisplayMs);
  return { sampleCount: samples.length, medianQueryEmbeddingMs: median(samples.map(row => row.queryEmbedding.elapsedMs)),
    medianSeekdbQueryMs: median(samples.map(row => row.seekdbQueryMs)),
    medianSearchRoundTripMs: median(samples.map(row => row.searchRoundTripMs)),
    medianEndToEndReadyMs: median(samples.map(row => row.endToEndReadyMs)),
    displaySampleCount: display.filter(Number.isFinite).length,
    medianEndToEndDisplayMs: display.every(Number.isFinite) ? median(display) : null };
}
async function measureDisplay(renderer, results, metadata, started) {
  if (typeof renderer !== 'function') return { endToEndDisplayMs: null, displayTimingStatus: 'not-requested' };
  if (document.visibilityState !== 'visible') fail('Display timing requires a foreground page');
  let hidden = false, first = 0, second = 0, timer;
  const changed = () => { hidden ||= document.visibilityState !== 'visible'; };
  document.addEventListener('visibilitychange', changed);
  try {
    await renderer(results, metadata);
    await new Promise((resolve, reject) => {
      timer = setTimeout(() => reject(new Error('Display frame timeout')), 3000);
      first = requestAnimationFrame(() => { second = requestAnimationFrame(resolve); });
    });
    if (hidden || document.visibilityState !== 'visible') fail('Page hidden during display timing');
    return { endToEndDisplayMs: performance.now() - started, displayTimingStatus: 'foreground-dom-update-plus-two-raf' };
  } finally {
    clearTimeout(timer); if (first) cancelAnimationFrame(first); if (second) cancelAnimationFrame(second);
    document.removeEventListener('visibilitychange', changed);
  }
}
function ratio(numerator, denominator) {
  return Number.isFinite(numerator) && Number.isFinite(denominator) && denominator > 0 ? numerator / denominator : null;
}
function compareModes(modes, baselineId, candidateId) {
  const baseline = modes.find(mode => mode.id === baselineId), candidate = modes.find(mode => mode.id === candidateId);
  if (baseline?.status !== 'valid' || candidate?.status !== 'valid') return { baselineId, candidateId, status: 'unavailable', reason: 'Both complete valid modes are required' };
  const fields = ['repo', 'revision', 'dimension', 'pooling', 'normalize'];
  if (baseline.actual.backend !== candidate.actual.backend
    || fields.some(key => baseline.model[key] !== candidate.model[key])) return { baselineId, candidateId, status: 'unavailable', reason: 'Backend/model conditions differ' };
  return { baselineId, candidateId, status: 'same-backend-pair',
    recallAt5Delta: candidate.summary.quality.macroRecallAt5 - baseline.summary.quality.macroRecallAt5,
    ndcgAt5Delta: candidate.summary.quality.macroNdcgAt5 - baseline.summary.quality.macroNdcgAt5,
    modelTotalBytesCompressionRatio: baseline.modelAssets.totalBytes / candidate.modelAssets.totalBytes,
    subsequentQueryEndToEndMedianRatio: ratio(baseline.summary.subsequentQueryTrials.medianEndToEndReadyMs, candidate.summary.subsequentQueryTrials.medianEndToEndReadyMs) };
}

/** Returns an in-memory report only. Caller renders it; no export/download/storage. */
export async function runQuantizationBenchmark({ onProgress = () => {}, onStatus = () => {}, onResults = null } = {}) {
  if (running) fail('A benchmark is already running');
  running = true;
  const runId = crypto.randomUUID();
  const report = { version: 2, runId, startedAt: new Date().toISOString(), status: 'running',
    userAgent: navigator.userAgent, platform: navigator.userAgentData?.platform || navigator.platform || null,
    hardwareConcurrency: navigator.hardwareConcurrency || null, deviceMemoryGiB: navigator.deviceMemory || null,
    manifest: { topK: K, repeatsPerQuery: REPEATS, corpusCount: 20, queryCount: 10,
      batchSizes: [1, 4], repeatsPerBatchSize: 3, batchTrialOrders: [[1, 4], [4, 1], [1, 4]],
      browserCacheCleared: false, modelCacheCleared: false,
      coldDefinition: 'fresh EmbeddingClient/Worker session only; no claim of clean HTTP/model/device cache',
      endToEndBoundary: 'programmatic query start through parsed DB results ready for display; excludes report rendering',
      endToEndDisplayBoundary: 'separate field: query start through visible result DOM update plus two foreground animation-frame opportunities; not a physical screen-presentation timestamp',
      timingLoadBoundary: 'client init includes cache/file acquisition and backend session setup; download is not separately isolated',
      expectedReviewedBridge: { sdk: 'seekdb 1.4.0', execution: 'public SDK execute; one bound database-side RRF statement', vectorDistance: 'cosine', analyzer: 'ik smart',
        fulltextCandidates: 1000, knnCandidates: 50, rrfRankWindowSize: 50, rrfRankConstant: 60, source: 'reviewed bridge contract, not queried configuration' },
      runtimeExpectedFromReviewedAssets: { library: 'Transformers.js', version: '3.8.1' },
      qualityScope: 'AI-assisted synthetic development set, not official gold or general retrieval-quality evidence' },
    modes: [], comparisons: [], callbackWarnings: [] };
  const notify = (callback, value, name) => { try { callback(value); } catch { if (!report.callbackWarnings.includes(name)) report.callbackWarnings.push(name); } };
  const progress = message => notify(onProgress, message, 'onProgress callback failed');
  const status = value => notify(onStatus, value, 'onStatus callback failed');
  try {
    progress('正在读取固定开发语料与相关性标签…');
    const corpusFile = await fixture('/fixtures/corpus.json');
    const queryFile = await fixture('/fixtures/queries.json');
    const dataset = validateFixtures(corpusFile.value, queryFile.value);
    report.manifest.dataset = { corpus: { path: corpusFile.path, sha256: corpusFile.sha256 },
      queries: { path: queryFile.path, sha256: queryFile.sha256 },
      qrelsBasis: 'complete reviewed relevant_ids expanded over all twenty initial Harbor IDs; all other pairs explicitly zero',
      qrelsSha256: await hashBytes(new TextEncoder().encode(JSON.stringify(dataset.qrels))),
      qrels: dataset.qrels, corpusIds: dataset.corpusIds, queryIds: dataset.queries.map(query => query.id) };
    report.databaseHealth = await api('/api/health');
    const createdIds = new Set();
    for (const mode of MODES) {
      const row = { id: mode.id, requested: { ...mode }, status: 'running', phase: 'init',
        stateEvents: [], batchSamples: [], warmups: [], queries: [], summary: null, kb: null };
      report.modes.push(row);
      progress(`正在运行 ${mode.id}，每种模式使用独立本地推理会话和新知识库…`);
      status({ mode: mode.id, status: 'running', phase: row.phase });
      const client = new EmbeddingClient({
        onStatus(value) {
          row.stateEvents.push({ at: new Date().toISOString(), status: value.status, backend: value.backend ?? null,
            dtype: value.dtype ?? null, generation: value.generation ?? null, fallback: value.fallback ?? null,
            error: value.error ?? null });
          status({ mode: mode.id, ...value });
        },
        onProgress(value) {
          if (value.phase === 'embedding') progress(`${mode.id}：本地向量化 ${value.completed}/${value.total}`);
          else progress(`${mode.id}：加载本地模型${Number.isFinite(value.detail?.progress) ? ` ${value.detail.progress.toFixed(0)}%` : '…'}`);
        },
      });
      try {
        const initStarted = performance.now();
        const state = await client.init(mode.clientMode);
        row.init = { wallMs: performance.now() - initStarted, clientTotalInitMs: state.timings?.totalInitMs ?? null,
          workerLoadMs: state.timings?.loadMs ?? null, warmupPerformedByWorker: state.timings?.warmupPerformed ?? null };
        row.actual = { backend: state.backend, dtype: state.dtype, selection: state.selection, fallback: state.fallback ?? null, gpu: state.gpu ?? null };
        row.model = { ...state.model };
        assertProfile(state, mode);
        row.phase = 'model-asset-metadata'; row.modelAssets = await modelAssets(row.model);
        const embed = async (texts, batchSize) => {
          const started = performance.now();
          const value = await client.embed(texts, { batchSize });
          const wallMs = performance.now() - started;
          assertProfile(value, mode, row.model);
          return { value, sample: embeddingSample(value, wallMs, texts.length, batchSize) };
        };
        row.phase = 'first-inference';
        const first = await embed([dataset.documents[0].text], 1);
        row.firstInference = { ...first.sample, documentCount: 1, documentIds: [dataset.documents[0].id],
          interpretation: 'first actual inference in this fresh Worker; browser/model caches not cleared' };
        const texts = dataset.documents.map(document => document.text);
        row.phase = 'batch-warmups';
        for (const batchSize of [1, 4]) {
          const warm = await embed(texts, batchSize);
          row.warmups.push({ ...warm.sample, documentCount: 20, excludedFromMeasuredBatchMedian: true });
        }
        row.phase = 'batch-comparison';
        let importVectors = null, importVectorSample = null;
        for (let trial = 1; trial <= 3; trial++) {
          for (const batchSize of (trial % 2 ? [1, 4] : [4, 1])) {
            const measured = await embed(texts, batchSize);
            const sample = { ...measured.sample, documentCount: 20, throughputDocsPerSecond: measured.sample.throughputTextsPerSecond, trial, id: `${mode.id}-batch${batchSize}-trial${trial}` };
            row.batchSamples.push(sample);
            if (batchSize === 4 && trial === 3) { importVectors = measured.value.embeddings; importVectorSample = sample; }
          }
        }
        if (!importVectors || importVectorSample.documentCount !== 20) fail('The actual final batch-4 corpus vectors are missing');
        row.phase = 'create-knowledge-base';
        let started = performance.now();
        const kb = await api('/api/kbs', { label: `benchmark-${runId}-${mode.id}`, profile: mode.dtype });
        row.kbCreateRoundTripMs = performance.now() - started;
        if (typeof kb.id !== 'string' || !/^[0-9a-f-]{36}$/.test(kb.id) || createdIds.has(kb.id)
          || kb.profile !== mode.dtype || kb.revision !== 0 || kb.status !== 'ready') fail('Fresh knowledge base contract failed');
        createdIds.add(kb.id); row.kb = kb;
        row.phase = 'write-and-refresh';
        const documents = dataset.documents.map(({ id, text, ...metadata }) => ({ id, text, metadata }));
        started = performance.now();
        const imported = await api(`/api/kbs/${encodeURIComponent(kb.id)}/import`, { documents, embeddings: importVectors, model: row.model });
        row.import = { ...imported, roundTripMs: performance.now() - started, vectorSourceBatchSampleId: importVectorSample.id,
          sharedCorpusEmbeddingWallMs: importVectorSample.wallMs };
        importVectors = null;
        if (imported.count !== 20 || imported.revision !== 1) fail('New KB must contain exactly twenty documents after completed import/refresh');
        for (const field of ['writeMs', 'refreshMs', 'totalMs']) finite(imported.timings?.[field], `import ${field}`);
        const byId = new Map(dataset.documents.map(document => [document.id, document]));
        for (let repeat = 1; repeat <= REPEATS; repeat++) {
          for (const query of dataset.queries) {
            row.phase = `query-${query.id}-repeat-${repeat}`;
            progress(`${mode.id}：查询 ${query.id}，第 ${repeat}/${REPEATS} 次`);
            row.pendingQuery = { queryId: query.id, repeat };
            if (onResults && document.visibilityState !== 'visible') fail('Display experiment requires a foreground page at query start');
            const queryStarted = performance.now();
            const embedded = await embed([query.query], 1);
            const searchStarted = performance.now();
            const result = await api(`/api/kbs/${encodeURIComponent(kb.id)}/search`,
              { text: query.query, embedding: embedded.value.embeddings[0], model: row.model, topK: K });
            const ready = performance.now();
            row.pendingQuery.sqlResultIDs = Array.isArray(result.results) ? result.results.map(item => item.id) : null;
            row.pendingQuery.revision = result.revision ?? null;
            if (!Array.isArray(result.results) || result.results.length > K || result.revision !== imported.revision) fail('Unexpected database search result contract');
            const ids = result.results.map(item => item.id);
            const quality = scoreRanking(ids, query.relevant_ids, dataset.corpusIds, K);
            for (const item of result.results) {
              const expected = byId.get(item.id);
              if (item.text !== expected.text || item.metadata?.revision !== '1' || item.metadata?.knowledgeBase !== 'harbor') fail('Result text/metadata differs from the frozen indexed corpus');
            }
            const displayed = await measureDisplay(onResults, result.results,
              { modeId: mode.id, queryId: query.id, repeat, kbId: kb.id }, queryStarted);
            row.queries.push({ queryId: query.id, query: query.query, repeat, firstForQuery: repeat === 1,
              firstSearchInFreshKB: row.queries.length === 0,
              documentEmbeddingSourceBatchSampleId: importVectorSample.id,
              documentEmbeddingTimingSharedNotPerQuery: { documentCount: 20, batchSize: 4, wallMs: importVectorSample.wallMs },
              queryEmbedding: embedded.sample, seekdbQueryMs: finite(result.queryMs, 'seekdb query time'),
              searchRoundTripMs: ready - searchStarted, endToEndReadyMs: ready - queryStarted,
              ...displayed,
              revision: result.revision, sqlResultIDs: ids, quality });
            delete row.pendingQuery;
          }
        }
        const qualityRounds = [1, 2, 3].map(repeat => completeRound(row.queries, dataset.queries.map(query => query.id), repeat));
        const batches = {};
        for (const batchSize of [1, 4]) {
          const samples = row.batchSamples.filter(sample => sample.batchSize === batchSize);
          if (samples.length !== 3 || samples.some(sample => sample.documentCount !== 20)) fail('Incomplete batch experiment');
          batches[batchSize] = { sampleCount: samples.length, medianWallMs: median(samples.map(sample => sample.wallMs)),
            medianInferenceMs: median(samples.map(sample => sample.inferenceMs)),
            medianThroughputDocsPerSecond: median(samples.map(sample => sample.throughputDocsPerSecond)) };
        }
        row.summary = { batches, batch4WallTimeSpeedup: batches[1].medianWallMs / batches[4].medianWallMs,
          quality: { queryCount: dataset.queries.length, repeatsPerQuery: REPEATS, querySamples: row.queries.length, perRound: qualityRounds,
            macroRecallAt5: mean(qualityRounds.map(round => round.recallAt5)), macroNdcgAt5: mean(qualityRounds.map(round => round.ndcgAt5)) },
          firstSearchInFreshKB: row.queries[0],
          firstPerQueryTrials: phaseTimingSummary(row.queries.filter(sample => sample.repeat === 1)),
          subsequentQueryTrials: phaseTimingSummary(row.queries.filter(sample => sample.repeat > 1)),
          perQuery: dataset.queries.map(query => {
            const samples = row.queries.filter(sample => sample.queryId === query.id);
            if (samples.length !== 3) fail('Incomplete per-query trials');
            return { queryId: query.id, allThree: phaseTimingSummary(samples), first: samples[0], subsequent: phaseTimingSummary(samples.slice(1)) };
          }) };
        row.status = 'valid'; row.phase = 'complete';
        status({ mode: mode.id, status: 'valid', message: '完整模式已完成；指标包含全部十条查询及重复请求' });
      } catch (error) {
        row.status = 'invalid'; row.summary = null;
        if (row.pendingQuery) { row.failedQuery = row.pendingQuery; delete row.pendingQuery; }
        row.error = { phase: row.phase, message: String(error.message || error).slice(0, 600), code: error.code ?? null,
          partialSamplesAreDiagnosticOnly: true };
        status({ mode: mode.id, status: 'invalid', ...row.error });
        progress(`${mode.id} 无效：${row.error.message}`);
      } finally {
        client.close();
      }
    }
    report.comparisons = [compareModes(report.modes, 'fp32-gpu', 'fp16-gpu'), compareModes(report.modes, 'fp32-wasm', 'q8-wasm')];
    report.status = report.modes.every(mode => mode.status === 'valid') ? 'complete' : 'incomplete';
  } catch (error) {
    report.status = 'invalid'; report.error = { message: String(error.message || error).slice(0, 600) };
  } finally {
    report.finishedAt = new Date().toISOString(); running = false;
    status({ status: report.status, phase: 'benchmark-complete' });
  }
  return report;
}
