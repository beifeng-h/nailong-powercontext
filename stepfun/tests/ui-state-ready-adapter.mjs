/** OFFLINE_NOT_MODEL: adapt only the frozen substitute Worker's ready protocol. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const ORIGINAL_SHA256 = '18bc9489ebad64782fd9d32bc02d4edf9aa89cad55430b658349e1ae586c93d0';
const originalUrl = new URL('../evidence/ui-state-recovery/fallback-boundary-repro.mjs', import.meta.url);
const originalBytes = readFileSync(originalUrl);
const actualSha256 = createHash('sha256').update(originalBytes).digest('hex');
assert.equal(actualSha256, ORIGINAL_SHA256, 'Frozen offline fixture bytes changed; review the adapter explicitly.');

const originalSource = originalBytes.toString('utf8');
assert.ok(Buffer.from(originalSource, 'utf8').equals(originalBytes), 'Fixture must round-trip as exact UTF-8 bytes.');
const constructorBefore = 'constructor() { this.messages = []; this.terminated = false; this.backend = null; this.dtype = null; instances.push(this); }';
const constructorAfter = 'constructor() { this.messages = []; this.terminated = false; this.backend = null; this.dtype = null; instances.push(this); queueMicrotask(() => { if (!this.terminated) this.onmessage({ data: { type: \'embedding-worker-ready\', protocolVersion: 1 } }); }); }';
const occurrences = (source, needle) => source.split(needle).length - 1;
assert.equal(occurrences(originalSource, constructorBefore), 1, 'Expected exactly one frozen substitute Worker constructor.');
assert.equal(occurrences(originalSource, constructorAfter), 0);
const adaptedSource = originalSource.replace(constructorBefore, constructorAfter);
assert.equal(occurrences(adaptedSource, constructorAfter), 1, 'Ready injection must occur exactly once.');
const revertedSource = adaptedSource.replace(constructorAfter, constructorBefore);
assert.ok(Buffer.from(revertedSource, 'utf8').equals(originalBytes), 'Reverting the constructor must recover every original byte.');
const checkCount = source => [...source.matchAll(/^await check\(/gm)].length;
assert.equal(checkCount(originalSource), 5, 'Expected the frozen five control/regression/boundary cases.');
assert.equal(checkCount(adaptedSource), 5, 'All five original await check calls must remain unchanged.');

// No context option: host/client/substitute Worker share the main context's intrinsics.
// Only the original fixture's own app VM retains its original isolated context.
const namespaceModules = new Map();
const module = new vm.SourceTextModule(adaptedSource, {
  identifier: originalUrl.href,
  initializeImportMeta(meta) { meta.url = originalUrl.href; },
  importModuleDynamically(specifier) { return import(specifier); },
});
await module.link(async specifier => {
  assert.ok(specifier.startsWith('node:'), 'The frozen fixture must statically import only Node builtins.');
  if (!namespaceModules.has(specifier)) {
    const namespace = await import(specifier);
    const names = Object.keys(namespace);
    namespaceModules.set(specifier, new vm.SyntheticModule(names, function () {
      for (const name of names) this.setExport(name, namespace[name]);
    }, { identifier: specifier }));
  }
  return namespaceModules.get(specifier);
});

// Preserve supplied --source-dir arguments. The npm UI-state contract defaults to public.
const originalArgv = process.argv;
if (!process.argv.includes('--source-dir')) {
  process.argv = [...process.argv, '--source-dir', fileURLToPath(new URL('../public/', import.meta.url))];
}
try {
  await module.evaluate();
} finally {
  process.argv = originalArgv;
  console.error(JSON.stringify({
    scope: 'OFFLINE_NOT_MODEL',
    adapter: 'single substitute Worker constructor ready microtask',
    originalFixture: fileURLToPath(originalUrl),
    originalFixtureSha256: actualSha256,
    exactReplacementCount: 1,
    revertedBytesIdentical: true,
    originalAwaitCheckCount: 5,
    adaptedAwaitCheckCount: 5,
    outerVmContext: 'main/default',
    importMetaUrl: originalUrl.href,
    businessAssertionsChanged: false,
    originalFixtureModified: false,
    realBrowser: false,
    realModelInference: false,
    realNetworkOrDatabase: false,
  }));
}
