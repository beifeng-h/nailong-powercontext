/** OFFLINE_NOT_MODEL: deterministic Worker/timer substitutes; no model, browser, HTTP, or DB. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { EmbeddingClient } from '../public/embedding-client.mjs';

class Clock {
  now = 0;
  sequence = 0;
  timers = new Map();
  setTimeout = (callback, delay) => {
    const id = ++this.sequence;
    this.timers.set(id, { callback, at: this.now + delay });
    return id;
  };
  clearTimeout = id => { this.timers.delete(id); };
  advance(ms) {
    const end = this.now + ms;
    for (;;) {
      const next = [...this.timers].filter(([, timer]) => timer.at <= end)
        .sort((left, right) => left[1].at - right[1].at || left[0] - right[0])[0];
      if (!next) break;
      this.now = next[1].at;
      this.timers.delete(next[0]);
      next[1].callback();
    }
    this.now = end;
  }
}

async function flush() {
  // Only promise scheduling is involved; do not wait on wall-clock time.
  for (let turn = 0; turn < 16; turn++) await Promise.resolve();
}

function harness(t) {
  const originals = { Worker: globalThis.Worker, setTimeout: globalThis.setTimeout,
    clearTimeout: globalThis.clearTimeout, fetch: globalThis.fetch };
  const clock = new Clock(), workers = [], clients = [], statuses = [], progress = [];
  class OfflineWorker {
    constructor(url, options) {
      assert.ok(String(url).endsWith('/embedding-worker.js'));
      assert.equal(options.type, 'module');
      this.messages = [];
      this.terminated = false;
      workers.push(this);
    }
    terminate() { this.terminated = true; }
    postMessage(message) {
      if (this.postError) throw this.postError;
      this.messages.push(structuredClone(message));
    }
    // Deliberately allow late messages after termination to exercise generation isolation.
    deliver(data) { this.onmessage?.({ data }); }
    ready(protocolVersion = 1) { this.deliver({ type: 'embedding-worker-ready', protocolVersion }); }
    initialized(message = this.messages.findLast(item => item.type === 'init')) {
      assert.ok(message, 'init must be posted after ready');
      this.deliver({ type: 'result', jobId: message.jobId, result: {
        backend: message.backend, dtype: message.dtype,
        model: { repo: 'OFFLINE_NOT_MODEL', revision: 'OFFLINE', precision: message.dtype,
          dimension: 384, pooling: 'mean', normalize: true },
      } });
    }
  }
  globalThis.Worker = OfflineWorker;
  globalThis.setTimeout = clock.setTimeout;
  globalThis.clearTimeout = clock.clearTimeout;
  globalThis.fetch = () => { throw new Error('OFFLINE_NOT_MODEL: real network is forbidden'); };
  const makeClient = options => {
    const client = new EmbeddingClient({ startupTimeoutMs: 15, requestTimeoutMs: 120,
      onStatus: value => statuses.push(value), onProgress: value => progress.push(value), ...options });
    clients.push(client);
    return client;
  };
  t.after(() => {
    for (const client of clients) client.close();
    Object.assign(globalThis, originals);
    assert.equal(clock.timers.size, 0, 'every client must release its timers');
  });
  return { clock, workers, statuses, progress, makeClient,
    async tick(ms) { clock.advance(ms); await flush(); } };
}

test('OFFLINE_NOT_MODEL: delayed module ready retains the first init until the handler is ready', async t => {
  const h = harness(t), client = h.makeClient();
  const pending = client.init('q8');
  await flush();
  const worker = h.workers[0];
  assert.equal(worker.messages.length, 0);
  worker.ready(0); // A mismatched protocol cannot unlock startup.
  await h.tick(5);
  assert.equal(worker.messages.length, 0);
  assert.equal(client.state, null);
  worker.ready();
  await flush();
  assert.equal(worker.messages.length, 1);
  assert.equal(worker.messages[0].type, 'init');
  assert.equal(worker.messages[0].backend, 'wasm');
  worker.initialized();
  const state = await pending;
  assert.equal(state.dtype, 'q8');
  assert.equal(h.clock.timers.size, 0);
});

test('OFFLINE_NOT_MODEL: never-ready auto tries a fresh generation and eventually rejects', async t => {
  const h = harness(t), client = h.makeClient();
  const outcome = client.init('auto').then(value => ({ value }), error => ({ error }));
  await flush();
  const first = h.workers[0];
  await h.tick(15);
  assert.equal(first.terminated, true);
  assert.equal(first.messages.length, 0);
  assert.equal(h.workers.length, 2);
  const fallback = h.statuses.find(value => value.status === 'fallback').fallback;
  assert.equal(fallback.errorCode, 'timeout');
  assert.equal(fallback.gpuUnavailableObserved, false);
  assert.equal(fallback.fp16UnsupportedObserved, false);
  await h.tick(15);
  assert.equal((await outcome).error.code, 'timeout');
  assert.equal(h.workers[1].terminated, true);
  assert.equal(client.state, null);
  assert.equal(client.pending.size, 0);
  assert.equal(h.clock.timers.size, 0);
  // The rejected operation must release the queue for a later explicit retry.
  const retry = client.init('q8');
  await flush();
  const third = h.workers[2];
  third.ready(); await flush(); third.initialized();
  assert.equal((await retry).dtype, 'q8');
});

test('OFFLINE_NOT_MODEL: unanswered init times out; old replies cannot replace recovered WASM state', async t => {
  const h = harness(t), client = h.makeClient();
  const pending = client.init('auto');
  await flush();
  const old = h.workers[0];
  old.ready(); await flush();
  const oldJob = old.messages[0];
  assert.equal(oldJob.backend, 'webgpu');
  await h.tick(120);
  assert.equal(old.terminated, true);
  assert.equal(h.workers.length, 2);
  old.ready(); old.initialized(oldJob);
  await flush();
  assert.equal(client.state, null);
  const current = h.workers[1];
  current.ready(); await flush();
  assert.equal(current.messages[0].backend, 'wasm');
  assert.equal(current.messages[0].dtype, 'q8');
  current.initialized();
  const state = await pending;
  assert.equal(state.backend, 'wasm');
  assert.equal(state.fallback.errorCode, 'timeout');
  assert.equal(state.fallback.gpuUnavailableObserved, false);
  const readyState = client.state, statusCount = h.statuses.length;
  old.initialized(oldJob);
  old.deliver({ type: 'error', jobId: oldJob.jobId, error: { code: 'runtime', message: 'OFFLINE stale error' } });
  old.deliver({ type: 'progress', jobId: oldJob.jobId, phase: 'OFFLINE stale progress' });
  await flush();
  assert.equal(client.state, readyState);
  assert.equal(h.statuses.length, statusCount);
  assert.equal(h.progress.length, 0);
  assert.equal(h.clock.timers.size, 0);
});

test('OFFLINE_NOT_MODEL: successful init and embed clear deadlines instead of killing a ready worker later', async t => {
  const h = harness(t), client = h.makeClient();
  const init = client.init('q8');
  await flush();
  const worker = h.workers[0];
  worker.ready(); await flush(); worker.initialized(); await init;
  assert.equal(h.clock.timers.size, 0);
  const embedding = client.embed(['OFFLINE input']);
  await flush();
  const request = worker.messages.findLast(message => message.type === 'embed');
  assert.equal(h.clock.timers.size, 1);
  const vector = Array(384).fill(0); vector[0] = 1;
  worker.deliver({ type: 'result', jobId: request.jobId, result: {
    backend: 'wasm', dtype: 'q8', model: client.state.model, embeddings: [vector],
  } });
  assert.deepEqual((await embedding).embeddings, [vector]);
  assert.equal(h.clock.timers.size, 0);
  await h.tick(10_000);
  assert.equal(worker.terminated, false);
  assert.equal(client.state.backend, 'wasm');
});

test('OFFLINE_NOT_MODEL: a request error or synchronous post failure releases every timer', async t => {
  const h = harness(t);
  for (const synchronous of [false, true]) {
    const client = h.makeClient();
    const outcome = client.init('q8').then(value => ({ value }), error => ({ error }));
    await flush();
    const worker = h.workers.at(-1);
    if (synchronous) worker.postError = new Error('OFFLINE postMessage failure');
    worker.ready(); await flush();
    if (!synchronous) worker.deliver({ type: 'error', jobId: worker.messages[0].jobId,
      error: { code: 'runtime', message: 'OFFLINE initialization error' } });
    const { error } = await outcome;
    assert.match(error.message, synchronous ? /postMessage failure/ : /initialization error/);
    assert.equal(worker.terminated, true);
    assert.equal(client.pending.size, 0);
    assert.equal(h.clock.timers.size, 0);
    client.close();
  }
});

test('OFFLINE_NOT_MODEL: close during boot rejects immediately, clears startup, and ignores late ready', async t => {
  const h = harness(t), client = h.makeClient();
  const outcome = client.init('auto').then(value => ({ value }), error => ({ error }));
  await flush();
  const worker = h.workers[0];
  assert.equal(h.clock.timers.size, 1);
  client.close();
  assert.equal((await outcome).error.code, 'closed');
  assert.equal(worker.terminated, true);
  assert.equal(h.clock.timers.size, 0);
  worker.ready(); await h.tick(10_000);
  assert.equal(worker.messages.length, 0);
  assert.equal(h.workers.length, 1);
  assert.equal(client.state, null);
});

test('OFFLINE_NOT_MODEL: deadline options reject unsafe timer values', () => {
  for (const name of ['startupTimeoutMs', 'requestTimeoutMs']) {
    for (const value of [0, -1, 0.5, NaN, Infinity, 2_147_483_648]) {
      assert.throws(() => new EmbeddingClient({ [name]: value }), TypeError);
    }
    const client = new EmbeddingClient({ [name]: 2_147_483_647 });
    client.close();
  }
});
