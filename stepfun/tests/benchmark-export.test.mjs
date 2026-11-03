import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const source = await readFile(new URL('../public/benchmark-page.mjs', import.meta.url), 'utf8');

async function harness(run) {
  const downloads = [], blobs = [], revoked = [], timers = [];
  class Element {
    constructor(tag) { this.tag = tag; this.listeners = {}; this.children = []; this.textContent = ''; this.disabled = false; }
    addEventListener(event, callback) { this.listeners[event] = callback; }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; }
    click() {
      if (this.tag === 'a') downloads.push({ filename: this.download, href: this.href });
      else return this.listeners.click?.();
    }
    remove() { this.removed = true; }
  }
  const elements = new Map(['raw', 'export', 'export-status', 'start', 'summary', 'pairs', 'stage', 'query-label', 'current-results']
    .map(id => [id, new Element(id)]));
  elements.get('export').disabled = true;
  const document = { getElementById: id => elements.get(id), createElement: tag => new Element(tag), body: new Element('body') };
  const context = vm.createContext({ document, Blob,
    URL: {
      createObjectURL(blob) { blobs.push(blob); return `blob:local-test/${blobs.length}`; },
      revokeObjectURL(url) { revoked.push(url); },
    },
    setTimeout(callback, delay) { timers.push({ callback, delay }); return timers.length; },
  });
  const dependency = new vm.SyntheticModule(['runQuantizationBenchmark'], function () {
    this.setExport('runQuantizationBenchmark', run);
  }, { context });
  const page = new vm.SourceTextModule(source, { context });
  await page.link(specifier => {
    assert.equal(specifier, './benchmark.mjs');
    return dependency;
  });
  await page.evaluate();
  return { elements, downloads, blobs, revoked, timers, document };
}

function report(runId, status = 'complete') {
  return { version: 2, runId, startedAt: '2026-11-03T00:00:00Z', finishedAt: '2026-11-03T00:01:00Z',
    status, modes: [], comparisons: [], preservedUnicode: '原始记录'.repeat(70_000) };
}

test('no file is emitted before a report exists', async () => {
  const h = await harness(() => { throw new Error('Benchmark must not be invoked by export'); });
  await h.elements.get('export').click();
  assert.equal(h.downloads.length, 0);
  assert.equal(h.blobs.length, 0);
});

test('the real page controller exports the complete large Unicode report and releases its URL', async () => {
  const value = report('49833fb0-c1bd-40da-858d-c6b569c5df4b');
  const h = await harness(async () => value);
  await h.elements.get('start').click();
  const displayed = h.elements.get('raw').textContent;
  assert.ok(displayed.length > 200_000);
  assert.equal(h.elements.get('export').disabled, false);
  await h.elements.get('export').click();
  assert.equal(h.downloads.length, 1);
  assert.equal(h.downloads[0].filename, `stepfun-benchmark-${value.runId}.json`);
  assert.equal(h.blobs[0].type, 'application/json;charset=utf-8');
  const exported = await h.blobs[0].text();
  assert.equal(exported, displayed);
  assert.equal(exported, JSON.stringify(value, null, 2));
  assert.equal(JSON.parse(exported).preservedUnicode, value.preservedUnicode);
  assert.match(h.elements.get('export-status').textContent, /已发起下载/);
  assert.ok(h.document.body.children[0].removed);
  for (const timer of h.timers) timer.callback();
  assert.deepEqual(h.revoked, [h.downloads[0].href]);
});

test('a new pending run cannot export stale data, and its partial failure remains exportable', async () => {
  let next = report('00000000-0000-4000-8000-000000000001');
  const h = await harness(() => typeof next === 'function' ? next() : Promise.resolve(next));
  await h.elements.get('start').click();
  let finish;
  next = () => new Promise(resolve => { finish = resolve; });
  const running = h.elements.get('start').click();
  assert.equal(h.elements.get('export').disabled, true);
  await h.elements.get('export').click();
  assert.equal(h.downloads.length, 0);
  const partial = report('00000000-0000-4000-8000-000000000002', 'incomplete');
  partial.error = { message: 'Controlled failure; no model was executed in this unit test.' };
  finish(partial);
  await running;
  await h.elements.get('export').click();
  assert.equal(h.downloads.length, 1);
  const exported = JSON.parse(await h.blobs[0].text());
  assert.equal(exported.runId, partial.runId);
  assert.equal(exported.status, 'incomplete');
  assert.deepEqual(exported.error, partial.error);
});
