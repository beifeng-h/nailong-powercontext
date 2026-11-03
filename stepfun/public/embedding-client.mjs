// Owns only its own module Worker; no database calls or embedding work occur here.
const MODES = new Set(['auto', 'fp32', 'fp16', 'q8', 'fp32-wasm']);

function asError(payload) {
  const error = new Error(payload.message ?? 'Embedding Worker failed.');
  Object.assign(error, payload);
  return error;
}

export class EmbeddingClient {
  constructor({ onStatus = () => {}, onProgress = () => {},
    startupTimeoutMs = 15_000, requestTimeoutMs = 120_000 } = {}) {
    for (const timeout of [startupTimeoutMs, requestTimeoutMs]) {
      if (!Number.isSafeInteger(timeout) || timeout <= 0 || timeout > 2_147_483_647) {
        throw new TypeError('Worker timeouts must be positive timer-safe integers.');
      }
    }
    this.onStatus = onStatus;
    this.onProgress = onProgress;
    this.startupTimeoutMs = startupTimeoutMs;
    this.requestTimeoutMs = requestTimeoutMs;
    this.worker = null;
    this.startup = null;
    this.state = null;
    this.mode = null;
    this.closed = false;
    this.generation = 0;
    this.sequence = 0;
    this.pending = new Map();
    this.queue = Promise.resolve();
  }

  _enqueue(operation) {
    const result = this.queue.then(() => {
      if (this.closed) throw asError({ code: 'closed', message: 'EmbeddingClient has been closed.' });
      return operation();
    });
    // A failed UI request must not poison the client's scheduling queue.
    this.queue = result.catch(() => {});
    return result;
  }

  _status(status, extra = {}) {
    this.onStatus({ status, requestedMode: this.mode, generation: this.generation,
      ...(this.state ?? {}), ...extra });
  }

  _assertActive(worker = this.worker, generation = this.generation) {
    if (this.closed) throw asError({ code: 'closed', message: 'EmbeddingClient has been closed.' });
    if (!worker || this.worker !== worker || this.generation !== generation) {
      throw asError({ code: 'replaced', message: 'Embedding Worker generation changed.' });
    }
  }

  _dropWorker(reason = asError({ code: 'replaced', message: 'Worker was replaced.' })) {
    this.generation++;
    const worker = this.worker;
    this.worker = null;
    this.state = null;
    if (worker) worker.terminate();
    this._settleStartup(reason);
    for (const entry of this.pending.values()) {
      clearTimeout(entry.timer);
      entry.reject(reason);
    }
    this.pending.clear();
  }

  _settleStartup(error) {
    const startup = this.startup;
    if (!startup) return;
    this.startup = null;
    clearTimeout(startup.timer);
    if (error) startup.reject(error);
    else startup.resolve();
  }

  _spawn() {
    if (this.closed) throw asError({ code: 'closed', message: 'EmbeddingClient has been closed.' });
    this._dropWorker();
    const generation = this.generation;
    const worker = new Worker(new URL('./embedding-worker.js', import.meta.url), { type: 'module' });
    this.worker = worker;
    let startup;
    const ready = new Promise((resolve, reject) => { startup = { resolve, reject, timer: null }; });
    this.startup = startup;
    startup.timer = setTimeout(() => {
      if (this.worker !== worker || this.generation !== generation || this.startup !== startup) return;
      this._dropWorker(asError({ code: 'timeout', message: 'Embedding Worker did not become ready in time.',
        details: { phase: 'worker-startup' } }));
    }, this.startupTimeoutMs);
    worker.onmessage = event => {
      if (this.worker !== worker || this.generation !== generation) return;
      const message = event.data ?? {};
      if (message.type === 'embedding-worker-ready' && message.protocolVersion === 1) {
        this._settleStartup();
        return;
      }
      const entry = this.pending.get(message.jobId);
      if (!entry) return;
      if (message.type === 'progress') {
        this.onProgress({ ...message, generation, requestedMode: this.mode });
      } else if (message.type === 'result' || message.type === 'error') {
        this.pending.delete(message.jobId);
        clearTimeout(entry.timer);
        if (message.type === 'result') entry.resolve({ ...message.result, jobId: message.jobId });
        else entry.reject(asError(message.error ?? {}));
      }
    };
    const fatal = event => {
      if (this.worker !== worker || this.generation !== generation) return;
      const error = asError({ code: 'runtime', message: event.message ?? 'Worker could not load or decode a message.' });
      this._dropWorker(error);
      if (!this.closed) this._status('failed', { error: error.message });
    };
    worker.onerror = fatal;
    worker.onmessageerror = fatal;
    return ready;
  }

  _request(type, payload = {}) {
    if (!this.worker) return Promise.reject(asError({ code: 'state', message: 'No initialized Worker exists.' }));
    const worker = this.worker;
    const generation = this.generation;
    const jobId = `${this.generation}:${++this.sequence}`;
    return new Promise((resolve, reject) => {
      const entry = { resolve, reject, timer: null };
      this.pending.set(jobId, entry);
      entry.timer = setTimeout(() => {
        if (this.worker !== worker || this.generation !== generation || this.pending.get(jobId) !== entry) return;
        this._dropWorker(asError({ code: 'timeout', message: `Embedding Worker ${type} request timed out.`,
          details: { phase: type } }));
      }, this.requestTimeoutMs);
      try { worker.postMessage({ type, jobId, ...payload }); }
      catch (error) {
        this.pending.delete(jobId);
        clearTimeout(entry.timer);
        reject(error);
      }
    });
  }

  async _load(backend, dtype, context = {}) {
    const ready = this._spawn();
    const worker = this.worker;
    const generation = this.generation;
    this._status('loading', { requestedBackend: backend, requestedDtype: dtype, ...context });
    await ready;
    this._assertActive(worker, generation);
    const state = await this._request('init', { backend, dtype });
    this._assertActive(worker, generation);
    this.state = { ...state, ...context };
    this._status('ready');
    this._assertActive(worker, generation);
    return this.state;
  }

  async _embedAttempt(texts, batchSize) {
    const worker = this.worker;
    const generation = this.generation;
    const result = await this._request('embed', { texts, batchSize });
    this._assertActive(worker, generation);
    return result;
  }

  _fallbackDetails(error, trigger) {
    return { fallback: {
      trigger, reason: error.message, errorCode: error.code ?? 'runtime',
      gpuUnavailableObserved: error.details?.gpuUnavailableObserved === true,
      fp16UnsupportedObserved: error.details?.fp16UnsupportedObserved === true,
    } };
  }

  init(mode = 'auto') {
    return this._enqueue(async () => {
      if (!MODES.has(mode)) throw asError({ code: 'input', message: 'mode must be auto, fp32, fp16, q8, or fp32-wasm.' });
      this.mode = mode;
      const started = performance.now();
      try {
        let state;
        if (mode === 'q8' || mode === 'fp32-wasm') {
          state = await this._load('wasm', mode === 'q8' ? 'q8' : 'fp32', { selection: 'explicit-wasm', fallback: null });
        } else {
          const dtype = mode === 'fp32' ? 'fp32' : 'fp16';
          try {
            state = await this._load('webgpu', dtype, { selection: mode === 'auto' ? 'automatic-preference' : 'explicit-experiment', fallback: null });
          } catch (error) {
            if (this.closed || mode === 'fp16' || ['input', 'closed'].includes(error.code)) throw error;
            // A fresh Worker resets both failed session initialization and web inference promises.
            const details = this._fallbackDetails(error, 'initialization');
            this._status('fallback', details);
            state = await this._load('wasm', mode === 'fp32' ? 'fp32' : 'q8',
              { selection: 'automatic-fallback', ...details });
          }
        }
        this._assertActive();
        this.state = { ...state, timings: { ...state.timings, totalInitMs: performance.now() - started } };
        return this.state;
      } catch (error) {
        if (!this.closed) {
          this._dropWorker(error);
          this._status('failed', { error: error.message });
        }
        throw error;
      }
    });
  }

  embed(texts, { batchSize = 1 } = {}) {
    const input = Array.isArray(texts) ? texts.slice() : texts;
    return this._enqueue(async () => {
      if (!this.state) throw asError({ code: 'state', message: 'Call client.init(mode) before embedding.' });
      if (!Array.isArray(input) || !input.length
        || input.some(text => typeof text !== 'string' || !text.trim())
        || !Number.isSafeInteger(batchSize) || batchSize < 1) {
        throw asError({ code: 'input', message: 'Use nonblank string texts and a positive integer batchSize.' });
      }
      const started = performance.now();
      const before = this.state;
      let result;
      try {
        try {
          result = await this._embedAttempt(input, batchSize);
        } catch (error) {
          if (this.closed || before.backend !== 'webgpu' || this.mode === 'fp16'
            || ['input', 'state', 'busy', 'closed', 'replaced'].includes(error.code)) throw error;
          const details = this._fallbackDetails(error, 'inference');
          this._status('fallback', details);
          await this._load('wasm', this.mode === 'fp32' ? 'fp32' : 'q8',
            { selection: 'automatic-fallback', ...details });
          // Restart the entire input, not just the failed batch: never return mixed precisions.
          result = await this._embedAttempt(input, batchSize);
        }
      } catch (error) {
        if (!this.closed && !['input', 'state', 'busy'].includes(error.code)) {
          this._dropWorker(error);
          this._status('failed', { error: error.message });
        }
        throw error;
      }
      this._assertActive();
      return { ...result, elapsedMs: performance.now() - started,
        requestedMode: this.mode, generation: this.generation,
        fallback: this.state?.fallback ?? null,
        profileChanged: before.dtype !== result.dtype };
    });
  }

  close() {
    if (this.closed) return;
    this.closed = true;
    this._dropWorker(asError({ code: 'closed', message: 'EmbeddingClient was closed.' }));
    this._status('closed');
  }
}
