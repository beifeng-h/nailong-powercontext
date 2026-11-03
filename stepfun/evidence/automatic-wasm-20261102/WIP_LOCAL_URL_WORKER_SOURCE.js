// Browser module Worker. Assets are supplied by the separately verified resource fetcher.
import { env, pipeline } from '/vendor/transformers.min.js';

const REPO = 'Xenova/all-MiniLM-L6-v2';
const REVISION = '751bff37182d3f1213fa05d7196b954e230abad9';
const DIMENSION = 384;
const LOCAL_ORIGIN = new URL(import.meta.url).origin;
env.allowLocalModels = true;
env.allowRemoteModels = false;
env.localModelPath = new URL(`/models/${REVISION}/`, LOCAL_ORIGIN).href;
env.backends.onnx.wasm.wasmPaths = new URL('/vendor/', LOCAL_ORIGIN).href;
env.backends.onnx.wasm.numThreads = 1;

let encoder = null;
let current = null;
let busy = false;

function failure(code, message, details = {}) {
  const error = new Error(message);
  error.code = code;
  error.details = details;
  return error;
}

function model(dtype) {
  return { repo: REPO, revision: REVISION, precision: dtype,
    dimension: DIMENSION, pooling: 'mean', normalize: true };
}

function progress(jobId, payload) {
  self.postMessage({ type: 'progress', jobId, ...payload });
}

async function init(jobId, backend, dtype) {
  if (encoder) throw failure('state', 'This Worker is already initialized; create a fresh Worker to change profile.');
  const valid = (backend === 'webgpu' && ['fp32', 'fp16'].includes(dtype))
    || (backend === 'wasm' && ['fp32', 'q8'].includes(dtype));
  if (!valid) throw failure('input', 'Unsupported application backend/precision combination.');
  let gpu = { checked: false };
  if (backend === 'webgpu') {
    if (!self.navigator.gpu) throw failure('unavailable', 'WebGPU API is unavailable in this Worker.',
      { gpuUnavailableObserved: true, fp16UnsupportedObserved: false });
    const adapter = await self.navigator.gpu.requestAdapter();
    if (!adapter) throw failure('unavailable', 'No WebGPU adapter was returned.',
      { gpuUnavailableObserved: true, fp16UnsupportedObserved: false });
    gpu = { checked: true, adapterAvailable: true, shaderF16: adapter.features.has('shader-f16') };
    const info = adapter.info;
    gpu.adapterInfo = Object.fromEntries(['vendor', 'architecture', 'device', 'description']
      .map(key => [key, typeof info?.[key] === 'string' ? info[key] : null]));
    if (dtype === 'fp16' && !gpu.shaderF16) throw failure('unavailable', 'The WebGPU adapter lacks shader-f16.',
      { gpuUnavailableObserved: false, fp16UnsupportedObserved: true });
  }
  const started = performance.now();
  encoder = await pipeline('feature-extraction', REPO, {
    revision: REVISION, local_files_only: true, device: backend, dtype,
    progress_callback: event => {
      const detail = {};
      for (const key of ['status', 'file', 'name']) {
        if (typeof event[key] === 'string') detail[key] = event[key];
      }
      for (const key of ['loaded', 'total', 'progress']) {
        if (Number.isFinite(event[key])) detail[key] = event[key];
      }
      progress(jobId, { phase: 'model-load', backend, dtype, detail });
    },
  });
  current = { backend, dtype, profile: dtype, model: model(dtype), gpu,
    timings: { loadMs: performance.now() - started, warmupPerformed: false } };
  return current;
}

async function embed(jobId, texts, batchSize) {
  if (!encoder || !current) throw failure('state', 'Initialize this Worker first.');
  if (!Array.isArray(texts) || !texts.length
    || texts.some(text => typeof text !== 'string' || !text.trim())) {
    throw failure('input', 'texts must be a nonempty array of nonblank strings.');
  }
  if (!Number.isSafeInteger(batchSize) || batchSize < 1) {
    throw failure('input', 'batchSize must be a positive safe integer.');
  }
  const started = performance.now();
  const embeddings = [];
  const batches = Math.ceil(texts.length / batchSize);
  let inferenceMs = 0;
  for (let offset = 0, batchIndex = 0; offset < texts.length; offset += batchSize, batchIndex++) {
    const batch = texts.slice(offset, offset + batchSize);
    const inferenceStarted = performance.now();
    const output = await encoder(batch, { pooling: 'mean', normalize: true });
    inferenceMs += performance.now() - inferenceStarted;
    if (output.dims.length !== 2 || output.dims[0] !== batch.length || output.dims[1] !== DIMENSION) {
      throw failure('runtime', 'Embedding output has an unexpected shape.');
    }
    const rows = output.tolist();
    for (const vector of rows) {
      if (!Array.isArray(vector) || vector.length !== DIMENSION
        || vector.some(value => !Number.isFinite(value))
        || vector.reduce((sum, value) => sum + value * value, 0) <= 0) {
        throw failure('runtime', 'Embedding output is not a finite nonzero 384-dimensional vector.');
      }
      embeddings.push(vector);
    }
    progress(jobId, { phase: 'embedding', completed: embeddings.length, total: texts.length,
      batchIndex: batchIndex + 1, batches, backend: current.backend, dtype: current.dtype });
  }
  return { embeddings, backend: current.backend, dtype: current.dtype,
    profile: current.profile, model: current.model,
    workerElapsedMs: performance.now() - started, inferenceMs, batchSize, batches };
}

self.onmessage = async event => {
  const { jobId, type, backend, dtype, texts, batchSize } = event.data ?? {};
  if (typeof jobId !== 'string') return;
  if (busy) {
    self.postMessage({ type: 'error', jobId, error: { code: 'busy', message: 'Worker already has a request in progress.' } });
    return;
  }
  busy = true;
  try {
    const result = type === 'init' ? await init(jobId, backend, dtype)
      : type === 'embed' ? await embed(jobId, texts, batchSize)
      : (() => { throw failure('input', 'Unknown Worker request.'); })();
    self.postMessage({ type: 'result', jobId, result });
  } catch (error) {
    self.postMessage({ type: 'error', jobId, error: {
      code: error.code ?? 'runtime', message: String(error.message ?? error),
      details: error.details ?? {}, phase: type,
    } });
  } finally {
    busy = false;
  }
};

// Send initialization only after module imports and the message handler are ready.
self.postMessage({ type: 'embedding-worker-ready', protocolVersion: 1 });
