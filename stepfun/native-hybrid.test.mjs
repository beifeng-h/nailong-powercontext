import test from 'node:test';
import assert from 'node:assert/strict';
import { resolve } from 'node:path';
import { NATIVE_SEARCH_SQL, nativeSearchArguments, nativeSearchResults } from './native-hybrid.mjs';
import { createBridge, modelFor } from './bridge.mjs';

// Pure regressions. Put beside the two production modules (or reviewed copies).
// No SDK import, model execution, HTTP, browser, or database connection occurs.
const COLLECTION_ID = '0123456789abcdef0123456789abcdef';
const COLLECTION = Object.freeze({ collectionId: COLLECTION_ID });
const TEST_EMBEDDED_PATH = resolve('stepfun-independent-test', 'embedded-db');
const SQL = 'SELECT DBMS_HYBRID_SEARCH.SEARCH(?, ?) AS result';
const QUERIES = [
  'update the installed package',
  'delete an obsolete document',
  "O'Brien's notes; update/delete remain ordinary query text",
  "  UPDATE notes SET document='x'; DELETE FROM notes; -- 中文 😀\n  ",
];
const VECTOR = Object.freeze([1, 0, -0.25]);
const hit = (id, score = 0.25) => ({ _id: id, document: `document ${id}`, metadata: { title: id, nested: { tags: ['a', null] } }, _score: score });
const page = hits => [{ result: hits }];

function expectedParameters(text, embedding, topK = 5) {
  return {
    _source: ['_id', 'document', 'metadata'],
    query: { query_string: { fields: ['document'], query: text } },
    knn: { field: 'embedding', k: 50, query_vector: embedding },
    rank: { rrf: { rank_window_size: 50, rank_constant: 60 } },
    size: topK,
  };
}

test('native arguments preserve update/delete, quotes, semicolons and Unicode as bound JSON values', () => {
  assert.equal(NATIVE_SEARCH_SQL, SQL);
  assert.equal((NATIVE_SEARCH_SQL.match(/\?/g) ?? []).length, 2);
  for (const text of QUERIES) {
    const args = nativeSearchArguments(COLLECTION, { text, embedding: VECTOR, topK: 5 });
    assert.equal(args.length, 2);
    assert.equal(args[0], `c$v2$${COLLECTION_ID}`);
    assert.equal(typeof args[1], 'string');
    assert.deepEqual(JSON.parse(args[1]), expectedParameters(text, [...VECTOR]));
    assert.equal(NATIVE_SEARCH_SQL, SQL); // No input enters the SQL statement.
    assert.ok(!NATIVE_SEARCH_SQL.includes(text));
  }
  assert.deepEqual(VECTOR, [1, 0, -0.25]);
});

test('validated topK boundaries retain the 50-candidate native RRF settings', () => {
  for (const topK of [1, 5, 50]) {
    const [, json] = nativeSearchArguments(COLLECTION, { text: 'normal query', embedding: VECTOR, topK });
    assert.deepEqual(JSON.parse(json), expectedParameters('normal query', [...VECTOR], topK));
  }
});

test('collection identity uses the public readonly 32-hex ID and rejects malformed identities', () => {
  const upper = Object.freeze({ collectionId: COLLECTION_ID.toUpperCase() });
  assert.equal(nativeSearchArguments(upper, { text: 'q', embedding: VECTOR, topK: 5 })[0], `c$v2$${upper.collectionId}`);
  for (const value of [null, {}, { collectionId: 12 }, { collectionId: 'a'.repeat(31) },
    { collectionId: 'a'.repeat(33) }, { collectionId: 'g'.repeat(32) },
    { collectionId: `c$v2$${COLLECTION_ID}` }, { collectionId: `${COLLECTION_ID};DELETE` }]) {
    assert.throws(() => nativeSearchArguments(value, { text: 'q', embedding: VECTOR, topK: 5 }));
  }
});

test('results preserve DB order and score values, including ties, without client reranking', () => {
  const hits = [hit('10', 0.01), hit('2', 0.9), hit('01', 0.9)];
  hits[0].document = "update/delete O'Brien; 中文";
  const before = structuredClone(hits);
  assert.deepEqual(nativeSearchResults(page(hits), 5), hits.map(row => ({
    id: row._id, text: row.document, metadata: row.metadata, score: row._score, distance: null,
  })));
  assert.deepEqual(hits, before);
});

test('native JSON-string arrays and SQL NULL/empty arrays are supported', () => {
  const hits = [hit('first', 0), hit('second', 0.1)];
  assert.deepEqual(nativeSearchResults(page(JSON.stringify(hits)), 5), nativeSearchResults(page(hits), 5));
  for (const result of [null, [], '[]']) assert.deepEqual(nativeSearchResults(page(result), 5), []);
});

test('embedded fixed-512-byte binary IDs decode to the public SDK identity, preserving UTF-8 and whitespace', () => {
  for (const id of ['H02', ' 港口😀 ']) {
    const padded = id + '\0'.repeat(512 - Buffer.byteLength(id, 'utf8'));
    assert.equal(nativeSearchResults(page([hit(padded)]), 5)[0].id, id);
  }
});

test('ID codec rejects noncanonical NUL forms and duplicates after decoding', () => {
  for (const id of ['H02\0', '\0'.repeat(512), 'H\0x' + '\0'.repeat(509)]) {
    assert.throws(() => nativeSearchResults(page([hit(id)]), 5));
  }
  const padded = 'H02' + '\0'.repeat(509);
  assert.throws(() => nativeSearchResults(page([hit('H02'), hit(padded)]), 5));
});

test('malformed response envelopes and non-array JSON are rejected rather than treated as empty', () => {
  for (const rows of [null, undefined, {}, [], [page([])[0], page([])[0]], [{}],
    [{ result: undefined }], page('{}'), page('null'), page('{bad json'), page({}), page(0)]) {
    assert.throws(() => nativeSearchResults(rows, 5));
  }
});

test('malformed hit fields and non-finite/string scores are rejected', () => {
  const badHits = [null, undefined, false, [],
    ...['', null, 7].map(_id => ({ ...hit('valid'), _id })),
    ...[null, 7].map(document => ({ ...hit('valid'), document })),
    ...[null, [], 'metadata'].map(metadata => ({ ...hit('valid'), metadata })),
    ...[undefined, null, '0.1', NaN, Infinity, -Infinity].map(_score => ({ ...hit('valid'), _score })),
  ];
  for (const row of badHits) assert.throws(() => nativeSearchResults(page([row]), 5));
});

test('duplicate IDs are rejected even when nonadjacent', () => {
  assert.throws(() => nativeSearchResults(page([hit('a'), hit('b'), hit('a', 0.8)]), 5));
});

test('a complete topK page is accepted, overflow is rejected rather than truncated', () => {
  const hits = Array.from({ length: 6 }, (_, index) => hit(String(index)));
  assert.equal(nativeSearchResults(page(hits.slice(0, 5)), 5).length, 5);
  assert.throws(() => nativeSearchResults(page(hits), 5));
});

// A public SDK boundary double lets the public bridge search run without a DB.
// These synthetic rows test routing/protocol only; they are not retrieval gold.
function sdkDouble(resultRows) {
  const calls = [];
  const configs = [];
  const id = '12345678-1234-4123-8123-123456789abc';
  const row = { kb_id: id, label: 'synthetic', profile: 'fp32', revision: 7, state: 'ready',
    collection_name: `stepfun_${id.replaceAll('-', '')}_fp32`, model_manifest: modelFor('fp32') };
  const collection = Object.freeze({ collectionId: COLLECTION_ID,
    hybridSearch() { assert.fail('Legacy SDK generated-SQL path must not be invoked'); } });
  class SeekdbAdminClient {
    constructor(config) { configs.push({ kind: 'admin', config: structuredClone(config) }); }
    async createDatabase() {}
    async close() {}
  }
  class SeekdbClient {
    constructor(config) { configs.push({ kind: 'client', config: structuredClone(config) }); }
    async execute(sql, params = []) {
      calls.push({ sql, params: structuredClone(params) });
      if (sql.startsWith('SELECT\n') && sql.includes('FULL JOIN')) return resultRows;
      if (sql.startsWith('CREATE TABLE IF NOT EXISTS stepfun_kb_registry')) return [];
      if (sql.startsWith('SELECT kb_id,label,profile,collection_name,model_manifest,revision,state FROM ')) {
        assert.deepEqual(params, [id]);
        return [row];
      }
      assert.fail(`Unexpected SDK execute route in pure test: ${sql}`);
    }
    async getCollection({ name, embeddingFunction }) {
      assert.equal(name, row.collection_name);
      assert.equal(embeddingFunction, null);
      return collection;
    }
    async close() {}
  }
  return { sdk: { SeekdbAdminClient, SeekdbClient }, id, calls, configs };
}

test('embedded configuration passes only the absolute path and logical database through the public SDK', async t => {
  const fixture = sdkDouble(page([]));
  const path = TEST_EMBEDDED_PATH;
  const bridge = await createBridge({ sdk: fixture.sdk, connection: { path } });
  t.after(() => bridge.close());
  assert.deepEqual(fixture.configs, [
    { kind: 'admin', config: { path } },
    { kind: 'client', config: { path, database: 'stepfun_kb_demo' } },
  ]);
});

test('invalid or mixed embedded/server configuration fails before any SDK construction', async () => {
  for (const connection of [{ path: '' }, { path: 'relative/path' },
    { path: TEST_EMBEDDED_PATH, host: '127.0.0.1' }, { path: TEST_EMBEDDED_PATH, port: 36143 },
    { path: TEST_EMBEDDED_PATH, user: 'root' }, { path: TEST_EMBEDDED_PATH, password: '' }]) {
    const fixture = sdkDouble(page([]));
    await assert.rejects(createBridge({ sdk: fixture.sdk, connection }));
    assert.deepEqual(fixture.configs, []);
  }
});

test('public bridge.search executes one bound DB-side RRF query with original text and default size5', async t => {
  const hits = [hit('low-first', 0.1), hit('high-second', 0.9)];
  const fixture = sdkDouble(hits);
  const bridge = await createBridge({ sdk: fixture.sdk });
  t.after(() => bridge.close());
  const embedding = Array(384).fill(0); embedding[0] = 1;
  for (const text of QUERIES) {
    const response = await bridge.search(fixture.id, { text, embedding, model: modelFor('fp32') });
    assert.deepEqual(response.results.map(row => row.id), ['low-first', 'high-second']);
    assert.equal(response.revision, 7);
    const call = fixture.calls.at(-1);
    assert.ok(call.sql.includes('FULL JOIN'));
    assert.ok(call.sql.includes(`\`c$v2$${COLLECTION_ID}\``));
    assert.equal((call.sql.match(/\?/g) || []).length, 7);
    assert.deepEqual(call.params, [text, text, 1000, JSON.stringify(embedding), JSON.stringify(embedding), 50, 5]);
  }
  assert.equal(fixture.calls.filter(call => call.sql.includes('FULL JOIN')).length, QUERIES.length);
  assert.ok(fixture.calls.every(call => !/DBMS_HYBRID_SEARCH\.(?:GET_SQL|SEARCH)\s*\(/i.test(call.sql)));
});

test('public bridge.search surfaces invalid native result failure instead of successful empty output', async t => {
  const fixture = sdkDouble([hit('duplicate'), hit('duplicate')]);
  const bridge = await createBridge({ sdk: fixture.sdk });
  t.after(() => bridge.close());
  const embedding = Array(384).fill(0); embedding[0] = 1;
  await assert.rejects(bridge.search(fixture.id, {
    text: 'update/delete is ordinary text', embedding, model: modelFor('fp32'),
  }), error => error.status === 503 && error.code === 'DATABASE_OPERATION_FAILED' && error.details?.stage === 'search');
});
