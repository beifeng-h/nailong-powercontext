// Database-side hybrid query. All data values remain parameter-bound.
// Matches the pinned engine's native hybrid structure, using public execute(sql, params).
// Source: oceanbase/seekdb@0e49209e09fe58b6e4e91b6cb0d10131a0d19a4c
// src/sql/hybrid_search/ob_query_parse.cpp:662-807, 2560-2591 (raw physical lines).
import { nativeSearchResults } from './native-hybrid.mjs';
const WINDOW_SIZE = 50;
const FTS_LIMIT = WINDOW_SIZE * 20;
const DIMENSION = 384;

export function preparedRrfQuery(collection, { text, embedding, topK }) {
  if (typeof collection?.collectionId !== 'string'
    || !/^[0-9a-f]{32}$/i.test(collection.collectionId)) {
    throw new Error('Expected a version-2 seekdb collection ID');
  }
  if (typeof text !== 'string' || !text || text.includes('\0')
    || Buffer.byteLength(text, 'utf8') > 8192) {
    throw new Error('Invalid query text');
  }
  if (!Number.isInteger(topK) || topK < 1 || topK > WINDOW_SIZE) {
    throw new Error('topK must be an integer from 1 to 50');
  }
  if (!Array.isArray(embedding) || embedding.length !== DIMENSION
    || !embedding.every(value => typeof value === 'number' && Number.isFinite(value))) {
    throw new Error('Expected a finite 384-dimensional vector');
  }
  // Identifiers cannot be parameter-bound. Only this server-selected identifier
  // is interpolated, after exact 32-hex validation; all data values are bound.
  const table = `\`c$v2$${collection.collectionId}\``;
  const vector = JSON.stringify(embedding);
  const sql = `
SELECT
  IFNULL(f.\`_id\`, v.\`_id\`) AS \`_id\`,
  IFNULL(f.\`document\`, v.\`document\`) AS \`document\`,
  IFNULL(f.\`metadata\`, v.\`metadata\`) AS \`metadata\`,
  (IFNULL(1 / (f.\`_keyword_rank\` + 60), 0)
   + IFNULL(1 / (v.\`_semantic_rank\` + 60), 0)) AS \`_score\`
FROM
  (SELECT f0.*, RANK() OVER (ORDER BY \`_keyword_score\` DESC) AS \`_keyword_rank\`
   FROM
     (SELECT /*+ opt_param('hidden_column_visible', 'true') */
        \`__pk_increment\`, \`_id\`, \`document\`, \`metadata\`,
        MATCH(\`document\`) AGAINST (? IN NATURAL LANGUAGE MODE) AS \`_keyword_score\`
      FROM ${table}
      WHERE MATCH(\`document\`) AGAINST (? IN NATURAL LANGUAGE MODE)
      ORDER BY \`_keyword_score\` DESC LIMIT ?) f0) f
FULL JOIN
  (SELECT v0.*, RANK() OVER (ORDER BY \`_semantic_score\` DESC) AS \`_semantic_rank\`
   FROM
     (SELECT /*+ opt_param('hidden_column_visible', 'true') */
        \`__pk_increment\`, \`_id\`, \`document\`, \`metadata\`,
        cosine_distance(\`embedding\`, ?) AS \`_distance\`,
        ROUND(1 - cosine_distance(\`embedding\`, ?) / 2, 8) AS \`_semantic_score\`
      FROM ${table}
      ORDER BY \`_distance\` APPROXIMATE LIMIT ?) v0) v
ON f.\`__pk_increment\` = v.\`__pk_increment\`
ORDER BY \`_score\` DESC, IFNULL(v.\`__pk_increment\`, f.\`__pk_increment\`)
LIMIT ?`.trim();
  return { sql, params: [text, text, FTS_LIMIT, vector, vector, WINDOW_SIZE, topK] };
}

export function preparedRrfResults(rows, topK) {
  if (!Array.isArray(rows) || rows.length > topK) throw new Error('Invalid prepared hybrid search response');
  const decimal = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/;
  const hits = rows.map(row => {
    if (!row || typeof row !== 'object') throw new Error('Invalid prepared hybrid search hit');
    const metadata = typeof row.metadata === 'string' ? JSON.parse(row.metadata) : row.metadata;
    let score = row._score;
    if (typeof score === 'string' && decimal.test(score.trim())) score = Number(score);
    if (typeof score !== 'number' || !Number.isFinite(score)) throw new Error('Invalid prepared hybrid score');
    return { _id: row._id, document: row.document, metadata, _score: score };
  });
  // Preserve the database order and reuse the strict identity/integrity codec.
  return nativeSearchResults([{ result: hits }], topK);
}
