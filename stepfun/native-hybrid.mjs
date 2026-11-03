// Public seekdb-js execute() route demonstrated by the pinned SDK's own test:
// https://github.com/oceanbase/seekdb-js/blob/1efc691adb6093230025d333a6cbf9bad4395e02/packages/seekdb/tests/client/client-execute.test.ts#L241
// SEARCH performs vector/full-text RRF inside seekdb. No generated SQL is
// interpreted or executed by this application and no client-side merge occurs.
export const NATIVE_SEARCH_SQL = 'SELECT DBMS_HYBRID_SEARCH.SEARCH(?, ?) AS result';

function logicalDocumentId(value) {
  if (typeof value !== 'string' || !value) throw new Error('Invalid native document ID');
  if (!value.includes('\0')) return value;
  // Embedded type SEEKDB_TYPE_VARBINARY_ID right-pads IDs to exactly 512 bytes.
  // SEARCH JSON preserves that representation; public collection.get() exposes
  // the logical ID. The application rejects NUL in all input IDs. Decode only
  // this fixed-width, tail-padded form, preserving every other character.
  // https://github.com/oceanbase/seekdb/blob/0e49209e09fe58b6e4e91b6cb0d10131a0d19a4c/src/include/seekdb.h#L490
  const match = /^([^\0]+)\0+$/.exec(value);
  if (!match || Buffer.byteLength(value, 'utf8') !== 512) throw new Error('Invalid binary document ID representation');
  return match[1];
}

export function nativeSearchArguments(collection, { text, embedding, topK }) {
  // collectionId is a public readonly field of the pinned SDK. Collections
  // created by this application use its version-2 storage layout.
  if (typeof collection?.collectionId !== 'string' || !/^[0-9a-f]{32}$/i.test(collection.collectionId)) {
    throw new Error('Expected a version-2 seekdb collection ID');
  }
  const parameters = {
    _source: ['_id', 'document', 'metadata'],
    query: { query_string: { fields: ['document'], query: text } },
    knn: { field: 'embedding', k: Math.max(50, topK), query_vector: embedding },
    rank: { rrf: { rank_window_size: Math.max(50, topK), rank_constant: 60 } },
    size: topK,
  };
  return [`c$v2$${collection.collectionId}`, JSON.stringify(parameters)];
}

export function nativeSearchResults(rows, topK) {
  if (!Array.isArray(rows) || rows.length !== 1) throw new Error('Invalid native hybrid search response');
  let hits = rows[0]?.result;
  if (hits === null) return []; // Native SEARCH returns SQL NULL for no hits.
  if (typeof hits === 'string') hits = JSON.parse(hits);
  if (!Array.isArray(hits) || hits.length > topK) throw new Error('Invalid native hybrid search result list');
  const seen = new Set();
  return hits.map(hit => {
    if (!hit
      || typeof hit.document !== 'string' || !hit.metadata || typeof hit.metadata !== 'object'
      || Array.isArray(hit.metadata) || !Number.isFinite(hit._score)) {
      throw new Error('Invalid native hybrid search hit');
    }
    const id = logicalDocumentId(hit._id);
    if (seen.has(id)) throw new Error('Duplicate native hybrid search ID');
    seen.add(id);
    return { id, text: hit.document, metadata: hit.metadata, score: hit._score, distance: null };
  });
}
