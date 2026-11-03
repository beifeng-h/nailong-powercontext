/**
 * TEST-ONLY local API state probe. No browser/model inference or quality metrics.
 * Default is plan-only. All writes target this invocation's fresh KBs only.
 */
import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const BASE = 'http://127.0.0.1:34021';
const BASED_ON_COMMIT = 'c4f99a1a9c94da7111291f16cafc5eb30ff7c657';
const API_PROFILE = 'q8'; // Schema bucket only, NOT a claim of model quantization.
const ORIGIN = 'synthetic-one-hot-384-api-state-only-not-model-embeddings';
const MODEL = Object.freeze({ repo: 'Xenova/all-MiniLM-L6-v2',
  revision: '751bff37182d3f1213fa05d7196b954e230abad9', precision: API_PROFILE,
  dimension: 384, pooling: 'mean', normalize: true });
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const MARKER_QUERY = 'Where is the bicycle key cabinet marked cobaltmesa418?';
const EXPENSE_QUERY = 'What is the travel expense deadline in this workspace?';
const UPDATE_QUERY = 'Under the ledgermint604 expense update, what is the submission deadline?';
const sha = value => createHash('sha256').update(value).digest('hex');

export function protocolVectorFor(id) {
  let index;
  if (/^H(?:0[1-9]|1[0-9]|2[01])$/.test(id)) index = Number(id.slice(1)) - 1;
  else if (id === 'B01') index = 4; // Same vector as H05: same-query KB isolation probe.
  else if (id === 'B02') index = 17;
  else throw new Error('Unknown frozen fixture ID');
  const vector = Array(384).fill(0);
  vector[index] = 1;
  return vector;
}

export function loadFixtures() {
  const corpusBytes = readFileSync(new URL('./fixtures/corpus.json', import.meta.url));
  const mutationBytes = readFileSync(new URL('./fixtures/mutations.json', import.meta.url));
  const corpus = JSON.parse(corpusBytes), mutations = JSON.parse(mutationBytes);
  const harbor = corpus.documents.filter(doc => doc.knowledgeBase === 'harbor');
  const beacon = corpus.documents.filter(doc => doc.knowledgeBase === 'beacon');
  assert.deepEqual(harbor.map(doc => doc.id), Array.from({ length: 20 }, (_, i) => `H${String(i + 1).padStart(2, '0')}`));
  assert.deepEqual(beacon.map(doc => doc.id), ['B01', 'B02']);
  const add = mutations.documents.find(doc => doc.id === 'H21');
  const update = mutations.documents.find(doc => doc.id === 'H05' && doc.revision === '2');
  assert.equal(mutations.documents.length, 2);
  assert.ok(add?.text.includes('cobaltmesa418') && add.text.includes('east lobby'));
  assert.ok(update?.text.includes('ledgermint604') && update.text.includes('eleven calendar days'));
  assert.ok(!update.text.includes('seven calendar days'));
  assert.ok(beacon[0].text.includes('twenty-three calendar days'));
  const hashes = { corpus: sha(corpusBytes), mutations: sha(mutationBytes) };
  return { harbor, beacon, add, update, hashes };
}

export function makePlan(fixtures = loadFixtures()) {
  return { status: 'plan-only-no-http', endpoint: BASE, basedOnApiContract: BASED_ON_COMMIT, vectorOrigin: ORIGIN,
    declaredApiProfile: API_PROFILE, browserEmbeddingVerifiedByThisProbe: false,
    qualityOrModelPrecisionEvidence: false, fixtures: fixtures.hashes,
    sequence: [
      'Create fresh TEST_ONLY synthetic Harbor and Beacon KBs; reject any UUID present before this run',
      'Harbor import20 -> API count20/KB revision1; confirm H21 absent before addition',
      'Harbor addH21 -> count21/revision2; current H21 text becomes visible after import/refresh returns',
      'Harbor replace same ID H05 with r2 -> count21/revision3; current body11days/new marker, no old body',
      'Beacon import B01+B02 once -> count2/revision1; expense query23days',
      'Switch API target Harbor -> Beacon -> Harbor; returned IDs/text/metadata stay in selected KB',
      'Separate Node reopen command: read-only registry/search; no create/import/delete or service restart',
    ], noAutomaticRetry: true, noExistingKbWrites: true, noDeletion: true,
    notCovered: ['browser local inference', 'model precision/quality', 'UI dropdown/cache state',
      'independent fulltext-index correctness', 'browser reload', 'service/DB restart or crash recovery'] };
}

function documentPayload(doc, runId) {
  return { id: doc.id, text: doc.text, metadata: {
    knowledgeBase: doc.knowledgeBase ?? doc.kb_id, revision: doc.revision,
    title: doc.title, source_path: doc.source_path, fixtureTextSha256: sha(doc.text),
    testOnly: true, testSuite: 'api-state-protocol', runId, vectorOrigin: ORIGIN,
  } };
}

class LocalClient {
  constructor(report, { allowWrites, preexistingIds = new Set() }) {
    this.report = report; this.allowWrites = allowWrites;
    this.preexistingIds = preexistingIds; this.owned = new Map();
  }
  async request(method, path, body) {
    const fixedRead = method === 'GET' && ['/api/health', '/api/kbs'].includes(path);
    const create = method === 'POST' && path === '/api/kbs';
    const match = /^\/api\/kbs\/([0-9a-f-]{36})\/(import|search)$/.exec(path);
    const target = match && this.owned.get(match[1]);
    const search = method === 'POST' && match?.[2] === 'search' && target;
    const importing = method === 'POST' && match?.[2] === 'import' && target && target.createdThisRun;
    assert.ok(fixedRead || (this.allowWrites && create) || search || (this.allowWrites && importing), 'Route/ownership guard rejected request');
    const writeIntent = create || Boolean(importing);
    const log = { startedUtc: new Date().toISOString(), method, path, writeIntent,
      documentIds: body?.documents?.map(doc => doc.id), queryText: body?.text,
      vectorOrigin: body?.embedding || body?.embeddings ? ORIGIN : undefined };
    this.report.requests.push(log);
    try {
      const response = await fetch(BASE + path, { method, redirect: 'error', cache: 'no-store',
        signal: AbortSignal.timeout(30000),
        ...(body === undefined ? {} : { headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }) });
      log.httpStatus = response.status;
      const result = await response.json();
      if (!response.ok) {
        log.outcome = 'failed'; log.publicError = result.error;
        throw new Error(`Local API failed at ${method} ${path}; no retry`);
      }
      log.outcome = 'response-received';
      return result;
    } catch (error) {
      if (!log.outcome) log.outcome = 'unknown-outcome';
      log.inspectBeforeRetry = true;
      log.mayHaveCreatedOrWritten = writeIntent;
      throw error; // Entire run stops; never retry create/import automatically.
    }
  }
  async create(which) {
    assert.ok(this.allowWrites);
    const label = `TEST_ONLY_PROTOCOL_SYNTHETIC_${this.report.runId}_${which}`;
    this.report.plannedLabels.push(label); // Can reconcile a lost create response.
    const kb = await this.request('POST', '/api/kbs', { label, profile: API_PROFILE });
    assert.ok(UUID.test(kb.id) && !this.preexistingIds.has(kb.id) && !this.owned.has(kb.id), 'Create returned existing or invalid KB UUID');
    assert.equal(kb.label, label); assert.equal(kb.profile, API_PROFILE);
    assert.equal(kb.revision, 0); assert.equal(kb.status, 'ready');
    const owned = { id: kb.id, label, profile: API_PROFILE, confirmedRevision: 0,
      lastImportObservedCount: null, createdThisRun: true };
    this.owned.set(kb.id, owned); this.report.created.push(owned);
    return owned;
  }
  async importing(kb, docs, expectedCount) {
    assert.ok(this.allowWrites && this.owned.get(kb.id)?.createdThisRun);
    const result = await this.request('POST', `/api/kbs/${kb.id}/import`, {
      documents: docs.map(doc => documentPayload(doc, this.report.runId)),
      embeddings: docs.map(doc => protocolVectorFor(doc.id)), model: MODEL,
    });
    this.report.importResponses.push({ kbId: kb.id, ids: docs.map(doc => doc.id), response: result });
    assert.equal(result.count, expectedCount); assert.equal(result.revision, kb.confirmedRevision + 1);
    for (const field of ['writeMs', 'refreshMs', 'totalMs']) assert.ok(Number.isFinite(result.timings?.[field]) && result.timings[field] >= 0);
    kb.confirmedRevision = result.revision; kb.lastImportObservedCount = result.count;
    // The existing API returns only after the actual refresh operation completes.
    return result;
  }
  async search(kb, text, targetId, expectedDocs, { mustHave = [], mustNotHave = [] } = {}) {
    assert.ok(this.owned.has(kb.id));
    const result = await this.request('POST', `/api/kbs/${kb.id}/search`, {
      text, embedding: protocolVectorFor(targetId), model: MODEL, topK: 50,
    });
    const ids = Array.isArray(result.results) ? result.results.map(row => row.id) : null;
    const log = { kbId: kb.id, queryText: text, revision: result.revision, resultIds: ids,
      countMeaning: 'returned top-K count, NOT database row count', requiredBodies: {} };
    this.report.searchResponses.push(log);
    assert.ok(Array.isArray(result.results) && ids.length <= 50);
    assert.equal(new Set(ids).size, ids.length, 'Duplicate search ID');
    assert.equal(result.revision, kb.confirmedRevision);
    const expected = new Map(expectedDocs.map(doc => [doc.id, doc]));
    assert.ok(ids.every(id => expected.has(id)), 'Unknown or cross-KB result ID');
    for (const row of result.results) {
      assert.equal(row.text, expected.get(row.id).text, 'Stale/wrong body');
      assert.equal(row.metadata?.revision, expected.get(row.id).revision);
      assert.equal(row.metadata?.testOnly, true); assert.equal(row.metadata?.vectorOrigin, ORIGIN);
      assert.equal(row.metadata?.runId, this.report.runId);
    }
    for (const id of mustHave) {
      assert.ok(ids.includes(id), `Required current document not visible: ${id}`);
      log.requiredBodies[id] = result.results.find(row => row.id === id).text;
    }
    assert.ok(mustNotHave.every(id => !ids.includes(id)), 'Document unexpectedly present before import');
    // No rankings/Recall/nDCG/embedding-precision claim is made from these probes.
    return result;
  }
}

async function registry(client) {
  const result = await client.request('GET', '/api/kbs');
  assert.ok(Array.isArray(result.kbs));
  return result.kbs;
}
async function checkHealth(client) {
  const health = await client.request('GET', '/api/health');
  assert.equal(health.ok, true); assert.equal(health.database, 'stepfun_kb_demo');
  assert.equal(health.dimension, 384); assert.equal(health.sdkTargetVersion, '1.4.0');
  client.report.serverConfigurationReported = health;
}
function freshReport(kind, fixtures, runId) {
  return { schema: 'TEST_ONLY_API_STATE_V1', kind, runId, processId: process.pid,
    startedUtc: new Date().toISOString(), status: 'running', endpoint: BASE, basedOnApiContract: BASED_ON_COMMIT,
    actualServerCommit: 'not exposed by API; root binds actual running source separately',
    vectorOrigin: ORIGIN, declaredApiProfile: API_PROFILE,
    declaredApiModelManifestNotInferenceEvidence: MODEL,
    browserEmbeddingVerifiedByThisProbe: false, qualityOrModelPrecisionEvidence: false,
    fixtures: fixtures.hashes, plannedLabels: [], created: [], requests: [], importResponses: [], searchResponses: [] };
}

async function runProbe(fixtures) {
  const report = freshReport('new-kb-state-probe', fixtures, randomUUID());
  const client = new LocalClient(report, { allowWrites: true });
  try {
    await checkHealth(client);
    client.preexistingIds = new Set((await registry(client)).map(kb => kb.id));
    const harbor = await client.create('harbor'), beacon = await client.create('beacon');
    await client.importing(harbor, fixtures.harbor, fixtures.harbor.length);
    await client.search(harbor, MARKER_QUERY, 'H21', fixtures.harbor, { mustNotHave: ['H21'] });
    await client.importing(harbor, [fixtures.add], fixtures.harbor.length + 1);
    const afterAdd = [...fixtures.harbor, fixtures.add];
    await client.search(harbor, MARKER_QUERY, 'H21', afterAdd, { mustHave: ['H21'] });
    await client.importing(harbor, [fixtures.update], afterAdd.length);
    const afterUpdate = afterAdd.map(doc => doc.id === fixtures.update.id ? fixtures.update : doc);
    await client.search(harbor, UPDATE_QUERY, 'H05', afterUpdate, { mustHave: ['H05'] });
    await client.importing(beacon, fixtures.beacon, fixtures.beacon.length);
    for (const [kb, docs, id] of [[harbor, afterUpdate, 'H05'], [beacon, fixtures.beacon, 'B01'], [harbor, afterUpdate, 'H05']]) {
      await client.search(kb, EXPENSE_QUERY, id, docs, { mustHave: [id] });
    }
    await client.search(harbor, MARKER_QUERY, 'H21', afterUpdate, { mustHave: ['H21'] });
    report.status = 'passed-api-state-protocol-only';
    report.reopenInstruction = 'Exit this Node process; root may save this actual JSON and run reopen --receipt <file> --execute. No server restart or browser-inference evidence is implied.';
  } catch (error) {
    report.status = 'failed-or-incomplete'; report.error = String(error.message || error);
    report.noAutomaticRetry = true; report.inspectExistingNewTestKbsBeforeRetry = true;
  }
  report.finishedUtc = new Date().toISOString();
  return report;
}

async function reopenProbe(fixtures, previous) {
  assert.equal(previous.schema, 'TEST_ONLY_API_STATE_V1');
  assert.equal(previous.status, 'passed-api-state-protocol-only');
  assert.equal(previous.vectorOrigin, ORIGIN); assert.deepEqual(previous.fixtures, fixtures.hashes);
  assert.ok(UUID.test(previous.runId)); assert.notEqual(previous.processId, process.pid, 'Reopen must use a separate Node process');
  assert.equal(previous.created.length, 2);
  const report = freshReport('new-process-read-only-reopen', fixtures, previous.runId);
  report.previousProcessId = previous.processId;
  const client = new LocalClient(report, { allowWrites: false });
  try {
    await checkHealth(client);
    const kbs = await registry(client);
    for (const which of ['harbor', 'beacon']) {
      const label = `TEST_ONLY_PROTOCOL_SYNTHETIC_${previous.runId}_${which}`;
      const entry = previous.created.find(kb => kb.label === label);
      assert.ok(entry && UUID.test(entry.id));
      const actual = kbs.find(kb => kb.id === entry.id);
      assert.ok(actual); assert.equal(actual.label, label); assert.equal(actual.profile, API_PROFILE);
      assert.equal(actual.status, 'ready'); assert.equal(actual.revision, which === 'harbor' ? 3 : 1);
      assert.equal(entry.confirmedRevision, actual.revision);
      client.owned.set(entry.id, { ...entry, createdThisRun: false });
    }
    const harbor = [...client.owned.values()].find(kb => kb.label.endsWith('_harbor'));
    const beacon = [...client.owned.values()].find(kb => kb.label.endsWith('_beacon'));
    const updated = [...fixtures.harbor.map(doc => doc.id === 'H05' ? fixtures.update : doc), fixtures.add];
    for (const [kb, docs, id] of [[harbor, updated, 'H05'], [beacon, fixtures.beacon, 'B01'], [harbor, updated, 'H05']]) {
      await client.search(kb, EXPENSE_QUERY, id, docs, { mustHave: [id] });
    }
    await client.search(harbor, MARKER_QUERY, 'H21', updated, { mustHave: ['H21'] });
    report.status = 'passed-new-process-read-only-visibility';
    report.importCountsFromPreviousActualRunNotRecounted = previous.created.map(kb => ({ id: kb.id, count: kb.lastImportObservedCount }));
    report.freshCountAfterReopen = null;
    report.countLimit = 'Current API exposes registry revision and search results, no independent count endpoint. Top-K length is never treated as database count.';
  } catch (error) {
    report.status = 'failed-or-incomplete'; report.error = String(error.message || error);
  }
  report.finishedUtc = new Date().toISOString();
  return report;
}

async function main() {
  const args = process.argv.slice(2), command = args[0] ?? 'plan';
  const fixtures = loadFixtures();
  if (command === 'plan') { console.log(JSON.stringify(makePlan(fixtures), null, 2)); return; }
  assert.ok(args.includes('--execute'), 'No HTTP without explicit --execute after root review');
  let result;
  if (command === 'run') result = await runProbe(fixtures);
  else if (command === 'reopen') {
    const position = args.indexOf('--receipt');
    assert.ok(position >= 0 && args[position + 1], 'Actual previous-run receipt is required');
    result = await reopenProbe(fixtures, JSON.parse(readFileSync(args[position + 1], 'utf8')));
  } else throw new Error('Use plan, run --execute, or reopen --receipt <actual JSON> --execute');
  console.log(JSON.stringify(result, null, 2));
  if (!result.status.startsWith('passed-')) process.exitCode = 1;
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(error => { console.error(JSON.stringify({ status: 'preflight-failed-no-success-claimed', error: String(error.message || error) })); process.exitCode = 1; });
}
