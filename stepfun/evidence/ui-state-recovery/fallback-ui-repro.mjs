/** Offline VM/DOM/Worker substitute repro only. No browser/network/DB/model. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import vm from 'node:vm';

const here = dirname(fileURLToPath(import.meta.url));
const index = process.argv.indexOf('--source-dir');
const sourceDir = index >= 0 ? resolve(process.argv[index + 1]) : resolve(here, 'original');
const appSource = readFileSync(resolve(sourceDir, 'app.mjs'), 'utf8');
const sourceHashes = Object.fromEntries(['app.mjs','embedding-client.mjs','embedding-worker.js'].map(name =>
  [name, createHash('sha256').update(readFileSync(resolve(sourceDir, name))).digest('hex')]));
const { EmbeddingClient } = await import(pathToFileURL(resolve(sourceDir, 'embedding-client.mjs')).href);
globalThis.fetch = () => { throw new Error('REAL NETWORK FORBIDDEN IN OFFLINE REPRO'); };
const DOCS = Array.from({ length: 5 }, (_, i) => ({ id: `OFFLINE_DOC_${i + 1}`, text: `Offline substitute input ${i + 1}` }));
const KB16 = 'OFFLINE_FP16_KB', KB8 = 'OFFLINE_Q8_KB';
const OLD_RESULT = 'OFFLINE_OLD_FP16_RESULT', OLD_TIME = 'OFFLINE_OLD_FP16_TIMING';

class Element {
  constructor(id = '', tag = '') { this.id = id; this.tag = tag; this.value = ''; this.textContent = ''; this.children = []; this.listeners = new Map(); }
  addEventListener(type, callback) { this.listeners.set(type, callback); }
  replaceChildren(...children) { this.children = children; this.textContent = ''; if (this.id === 'kb') this.value = ''; }
  append(...children) { this.children.push(...children); }
}
function fakeWorkerFactory({ failGpuInit = false, failWasmEmbed = false } = {}) {
  const instances = [];
  class SubstituteWorker {
    constructor() { this.messages = []; this.terminated = false; this.backend = null; this.dtype = null; instances.push(this); }
    terminate() { this.terminated = true; }
    postMessage(message) {
      this.messages.push(structuredClone(message));
      queueMicrotask(() => {
        if (this.terminated) return;
        const error = (text, details = {}) => this.onmessage({ data: { type: 'error', jobId: message.jobId,
          error: { code: 'runtime', message: text, details } } });
        const result = value => this.onmessage({ data: { type: 'result', jobId: message.jobId, result: value } });
        if (message.type === 'init') {
          this.backend = message.backend; this.dtype = message.dtype;
          if (this.backend === 'webgpu' && failGpuInit) return error('OFFLINE injected GPU initialization unavailable', { gpuUnavailableObserved: true });
          this.model = { repo: 'OFFLINE_STUB_NOT_A_MODEL_RUN', revision: 'OFFLINE', precision: this.dtype, dimension: 384, pooling: 'mean', normalize: true };
          return result({ backend: this.backend, dtype: this.dtype, model: this.model });
        }
        assert.equal(message.type, 'embed');
        if (this.backend === 'webgpu') {
          // Five inputs at batch4: simulate first batch progress, then second-batch error.
          this.onmessage({ data: { type: 'progress', jobId: message.jobId, phase: 'embedding', completed: 4, total: message.texts.length } });
          return error('OFFLINE injected GPU second-batch inference failure');
        }
        if (failWasmEmbed) return error('OFFLINE injected WASM retry inference failure');
        return result({ backend: this.backend, dtype: this.dtype, model: this.model,
          embeddings: message.texts.map((_, i) => Array.from({ length: 384 }, (_, j) => i === j ? 1 : 0)) });
      });
    }
  }
  return { SubstituteWorker, instances };
}
async function setup(policy) {
  const workers = fakeWorkerFactory(policy);
  globalThis.Worker = workers.SubstituteWorker;
  const ids = ['mode','backend','model-progress','kb','kb-name','results','search-timing','events','message','load-model','create-kb','import-text','files','import-sample','search-form','query','export-log','doc-text','doc-id','db-status'];
  const elements = new Map(ids.map(id => [id, new Element(id)]));
  elements.get('mode').value = 'auto';
  let syntheticReads = 0, forbiddenWrites = 0;
  const context = vm.createContext({
    document: { getElementById: id => elements.get(id), createElement: tag => new Element('', tag), querySelectorAll: () => [...elements.values()] },
    performance,
    fetch: async (path, options = {}) => {
      if (path === '/api/health' && !options.method) { syntheticReads++; return { ok: true, json: async () => ({ databaseVersion: 'OFFLINE_STUB_NOT_DB' }) }; }
      if (path === '/api/kbs' && !options.method) { syntheticReads++; return { ok: true, json: async () => ({ kbs: [
        { id: KB16, label: 'OFFLINE old fp16 KB', profile: 'fp16' }, { id: KB8, label: 'OFFLINE q8 KB', profile: 'q8' },
      ] }) }; }
      forbiddenWrites++;
      throw new Error('OFFLINE API WRITE/SEARCH FORBIDDEN');
    },
  });
  const dependency = new vm.SyntheticModule(['EmbeddingClient'], function () { this.setExport('EmbeddingClient', EmbeddingClient); }, { context });
  const hooks = '\nexport const __audit = { loadModel, ensureModel, importDocuments, showBases, get activeModel(){return activeModel}, get client(){return client}, get generation(){return generation} };\n';
  const module = new vm.SourceTextModule(appSource + hooks, { context, identifier: pathToFileURL(resolve(sourceDir, 'app.mjs')).href });
  await module.link(specifier => { assert.equal(specifier, './embedding-client.mjs'); return dependency; });
  await module.evaluate();
  const api = module.namespace.__audit;
  return { api, elements, workers: workers.instances,
    counters: () => ({ syntheticReads, forbiddenWrites }),
    seedOldResults() { elements.get('kb').value = KB16; elements.get('results').textContent = OLD_RESULT; elements.get('search-timing').textContent = OLD_TIME; } };
}
function replayFacts(h) {
  const gpu = h.workers.find(worker => worker.backend === 'webgpu');
  const wasm = h.workers.find(worker => worker.backend === 'wasm');
  const gpuTexts = gpu?.messages.find(message => message.type === 'embed')?.texts;
  const wasmTexts = wasm?.messages.find(message => message.type === 'embed')?.texts;
  return { oldGpuTerminated: gpu?.terminated === true, gpuInput: gpuTexts, wasmInput: wasmTexts };
}
const rows = [];
async function check(name, operation) {
  const row = { name, observations: {} }; rows.push(row);
  try { await operation(row.observations); row.status = 'pass'; }
  catch (error) { row.status = 'fail'; row.assertion = String(error.message); }
}
await check('CONTROL: initialization failure destroys old worker and replays full input on WASM', async facts => {
  const h = await setup({ failGpuInit: true });
  try {
    await h.api.loadModel();
    const embedded = await h.api.client.embed(DOCS.map(doc => doc.text), { batchSize: 4 });
    facts.oldGpuTerminated = h.workers[0].terminated;
    facts.wasmFullInput = h.workers[1].messages.find(message => message.type === 'embed').texts;
    assert.equal(embedded.dtype, 'q8'); assert.equal(embedded.embeddings.length, 5);
    assert.equal(facts.oldGpuTerminated, true); assert.deepEqual(facts.wasmFullInput, DOCS.map(doc => doc.text));
    assert.equal(h.counters().forbiddenWrites, 0);
  } finally { h.api.client.close(); }
});
await check('REGRESSION: precision-invalidated KB must clear old results and timings', async facts => {
  const h = await setup({});
  try {
    await h.api.loadModel(); h.seedOldResults(); const generation = h.api.generation;
    await assert.rejects(h.api.importDocuments(DOCS), /模型已自动降级/);
    Object.assign(facts, replayFacts(h));
    facts.selectedKb = h.elements.get('kb').value;
    facts.resultText = h.elements.get('results').textContent;
    facts.timingText = h.elements.get('search-timing').textContent;
    facts.generationAdvanced = h.api.generation > generation;
    facts.forbiddenApiCalls = h.counters().forbiddenWrites;
    assert.equal(facts.oldGpuTerminated, true);
    assert.deepEqual(facts.wasmInput, DOCS.map(doc => doc.text));
    assert.equal(facts.forbiddenApiCalls, 0, 'Cross-precision import must be blocked');
    assert.equal(facts.selectedKb, '');
    assert.ok(!facts.resultText.includes(OLD_RESULT), 'Old FP16 result remained after selected KB was removed');
    assert.ok(!facts.timingText.includes(OLD_TIME), 'Old FP16 timing remained');
    assert.equal(facts.generationAdvanced, true, 'Programmatic selection invalidation must advance generation');
  } finally { h.api.client.close(); }
});
await check('REGRESSION: terminal retry failure must invalidate activeModel and make ensureModel initialize again', async facts => {
  const h = await setup({ failWasmEmbed: true });
  try {
    await h.api.loadModel(); h.seedOldResults();
    await assert.rejects(h.api.importDocuments(DOCS), /OFFLINE injected WASM retry inference failure/);
    facts.clientStateNull = h.api.client.state === null;
    facts.activeModelAfterFailure = h.api.activeModel;
    facts.selectedKbAfterFailure = h.elements.get('kb').value;
    const count = h.workers.length;
    await h.api.ensureModel();
    facts.newWorkerCreatedByEnsure = h.workers.length > count;
    facts.forbiddenApiCalls = h.counters().forbiddenWrites;
    assert.equal(facts.clientStateNull, true);
    assert.equal(facts.activeModelAfterFailure, null, 'App kept a stale ready model after client dropped its Worker');
    assert.equal(facts.newWorkerCreatedByEnsure, true, 'ensureModel skipped initialization after terminal failure');
    assert.equal(facts.forbiddenApiCalls, 0);
  } finally { h.api.client.close(); }
});
const failed = rows.filter(row => row.status === 'fail').length;
console.log(JSON.stringify({ scope: 'OFFLINE real client/app code with VM DOM/Worker/API substitutes; NOT browser/model/DB evidence',
  sourceDir, sourceHashes, controlAndRegressionCases: rows, failed,
  realBrowser: false, realModelInference: false, realHttpOrDatabase: false,
  workerSourceExecuted: false, desiredAssertionsUnchangedForAfterFix: true }, null, 2));
process.exitCode = failed ? 1 : 0;
