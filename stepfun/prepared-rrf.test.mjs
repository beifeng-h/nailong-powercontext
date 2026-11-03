import test from 'node:test';
import assert from 'node:assert/strict';
import { preparedRrfQuery, preparedRrfResults } from './prepared-rrf.mjs';
const collection = { collectionId: '0123456789abcdef0123456789abcdef' };
const vector = Array(384).fill(0); vector[0] = 1;

test('full original text and vector stay bound while the SQL shape is invariant', () => {
  const texts = ["How quickly is a verified owner's workspace removed?", "update; DELETE FROM x; -- O'Brien \\ 中文😀"];
  const queries = texts.map(text => preparedRrfQuery(collection, { text, embedding: vector, topK: 5 }));
  assert.equal(queries[0].sql, queries[1].sql);
  for (const [i, query] of queries.entries()) {
    assert.ok(!query.sql.includes(texts[i]));
    assert.equal((query.sql.match(/\?/g) || []).length, query.params.length);
    assert.deepEqual(query.params, [texts[i], texts[i], 1000, JSON.stringify(vector), JSON.stringify(vector), 50, 5]);
    assert.ok(query.sql.includes('FULL JOIN'));
    assert.equal((query.sql.match(/RANK\(\) OVER/g) || []).length, 2);
    assert.ok(!query.sql.includes('ROW_NUMBER'));
  }
});

test('only a server-selected 32-hex identifier enters SQL; invalid boundaries are refused', () => {
  for (const collectionId of ['x`; DROP TABLE x;--', 'g'.repeat(32), 'a'.repeat(31)]) {
    assert.throws(() => preparedRrfQuery({ collectionId }, { text: 'q', embedding: vector, topK: 5 }));
  }
  for (const topK of [0, 51, 2.5, null]) assert.throws(() => preparedRrfQuery(collection, { text: 'q', embedding: vector, topK }));
  const bad = vector.slice(); bad[1] = NaN;
  assert.throws(() => preparedRrfQuery(collection, { text: 'q', embedding: bad, topK: 5 }));
});

test('actual embedded decimal/JSON strings decode without changing database order or text', () => {
  const rows = [
    { _id: 'H02', document: ' Alpha\n', metadata: '{"revision":"1"}', _score: '0.0100' },
    { _id: 'H01', document: 'Beta', metadata: { source: 'fixture' }, _score: '0.0900' },
  ];
  const result = preparedRrfResults(rows, 5);
  assert.deepEqual(result.map(row => row.id), ['H02', 'H01']);
  assert.deepEqual(result.map(row => row.score), [0.01, 0.09]);
  assert.equal(result[0].text, ' Alpha\n');
  assert.deepEqual(result[0].metadata, { revision: '1' });
  assert.deepEqual(preparedRrfResults([], 5), []);
});

test('invalid score/metadata/envelope or duplicate identity never becomes a successful result', () => {
  const hit = { _id: 'H02', document: 'Alpha', metadata: '{}', _score: '0.0320' };
  for (const _score of ['', '0x10', 'Infinity', null, false, {}, NaN]) {
    assert.throws(() => preparedRrfResults([{ ...hit, _score }], 5));
  }
  for (const metadata of ['null', '[]', '{bad', null]) assert.throws(() => preparedRrfResults([{ ...hit, metadata }], 5));
  assert.throws(() => preparedRrfResults([hit, hit], 5));
  assert.throws(() => preparedRrfResults([hit], 0));
  assert.throws(() => preparedRrfResults(null, 5));
});
