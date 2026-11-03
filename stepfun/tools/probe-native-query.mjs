// Read-only diagnostic using an existing browser-generated DOCUMENT vector.
// The vector is deliberately not a new question embedding or quality result.
// Stop the local app before opening its embedded directory in this process.
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { SeekdbClient } from 'seekdb';
import { NATIVE_SEARCH_SQL, nativeSearchArguments } from '../native-hybrid.mjs';
import { preparedRrfQuery } from '../prepared-rrf.mjs';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const kbId = process.argv[2];
if (!/^[0-9a-f-]{36}$/.test(kbId || '')) throw new Error('Provide own existing test KB UUID');
process.env.SEEKDB_BINDINGS_CACHE_DIR = resolve(root, 'runtime/native-bindings');
process.env.SEEKDB_BINDINGS_BASE_URL = 'https://oceanbase-seekdb-builds.s3.ap-southeast-1.amazonaws.com/js-bindings/all_commits/469a55dc84ea7a9e077161a8b454871a9adaff35';
const output = resolve(root, 'evidence/native-query-diagnostic/DIAGNOSTIC.json');
mkdirSync(dirname(output), { recursive: true });
const query = JSON.parse(readFileSync(resolve(root, 'public/fixtures/queries.json'), 'utf8')).queries.find(q => q.id === 'Q07').query;
const report = { diagnosticOnly: true, databaseWrites: false, newModelInference: false,
  vectorBasis: 'Existing browser-generated document H02 vector; not a query embedding or retrieval-quality experiment',
  kbId, startedAt: new Date().toISOString(), stage: 'before-open', cases: [] };
const save = () => writeFileSync(output, JSON.stringify(report, null, 2) + '\n'); save();
const client = new SeekdbClient({ path: resolve(root, 'runtime/embedded-db-v1.4'), database: 'stepfun_kb_demo' });
try {
  report.version = await client.execute('SELECT VERSION() AS version'); report.stage = 'opened'; save();
  const rows = await client.execute('SELECT collection_name FROM stepfun_kb_registry WHERE kb_id=?', [kbId]);
  if (rows.length !== 1) throw new Error('Expected own existing KB');
  const collection = await client.getCollection({ name: rows[0].collection_name, embeddingFunction: null });
  const fetched = await collection.get({ ids: ['H02'], include: ['embeddings'] });
  const embedding = fetched.embeddings?.[0];
  if (!Array.isArray(embedding) || embedding.length !== 384) throw new Error('Expected stored document embedding');
  for (const [name, text] of [['original-Q07', query], ['diagnostic-only-apostrophe-removed', query.replaceAll("'", '')], ['diagnostic-only-SQL-quote-encoded', query.replaceAll("'", "''")]]) {
    const record = { name, text }; report.cases.push(record);
    try {
      const values = await client.execute(NATIVE_SEARCH_SQL, nativeSearchArguments(collection, { text, embedding, topK: 5 }));
      record.status = 'executed'; record.returnedRowCount = values.length;
    } catch (error) {
      record.status = 'failed'; record.error = { name: error.name, message: String(error.message || error).slice(0, 1500) };
    }
    report.stage = name; save();
  }
  const prepared = preparedRrfQuery(collection, { text: query, embedding, topK: 5 });
  report.preparedOriginal = { parameterCount: prepared.params.length, originalTextBoundTwice: prepared.params[0] === query && prepared.params[1] === query };
  try {
    const results = await client.execute(prepared.sql, prepared.params);
    report.preparedOriginal.status = 'executed';
    report.preparedOriginal.rows = results.map(row => ({ id: row._id, idLength: row._id.length,
      documentLength: row.document.length, metadataType: typeof row.metadata,
      metadataKeys: typeof row.metadata === 'object' ? Object.keys(row.metadata) : null,
      scoreType: typeof row._score, score: row._score }));
  } catch (error) { report.preparedOriginal.status = 'failed'; report.preparedOriginal.error = String(error.message || error); }
  report.status = 'complete'; report.finishedAt = new Date().toISOString(); save();
  await client.close(); process.exit(0);
} catch (error) {
  report.status = 'failed'; report.error = String(error.message || error); save();
  await client.close().catch(() => {}); process.exit(1);
}
