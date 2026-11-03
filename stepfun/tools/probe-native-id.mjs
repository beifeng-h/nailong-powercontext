// Read-only storage/codec diagnostic. Stop the local app before running this
// against its embedded directory. It does not compute model vectors or quality.
import { mkdirSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { SeekdbClient } from 'seekdb';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const kbId = process.argv[2], logicalId = process.argv[3] || 'H02';
if (!/^[0-9a-f-]{36}$/.test(kbId || '') || logicalId.includes('\0')) throw new Error('Provide own test KB UUID and NUL-free document ID');
process.env.SEEKDB_BINDINGS_CACHE_DIR = resolve(root, 'runtime/native-bindings');
process.env.SEEKDB_BINDINGS_BASE_URL = 'https://oceanbase-seekdb-builds.s3.ap-southeast-1.amazonaws.com/js-bindings/all_commits/469a55dc84ea7a9e077161a8b454871a9adaff35';
const path = resolve(root, 'runtime/embedded-db-v1.4');
const output = resolve(root, 'evidence/native-id-codec/DIAGNOSTIC.json');
mkdirSync(dirname(output), { recursive: true });
const report = { diagnosticOnly: true, databaseWrites: false, modelInference: false,
  startedAt: new Date().toISOString(), kbId, logicalId, stages: [], status: 'running' };
const save = stage => {
  report.stages.push({ stage, at: new Date().toISOString() });
  writeFileSync(output, JSON.stringify(report, null, 2) + '\n');
};
save('before-first-sdk-execute');
const client = new SeekdbClient({ path, database: 'stepfun_kb_demo' });
try {
  report.version = await client.execute('SELECT VERSION() AS version'); save('opened');
  report.scalar = await client.execute("SELECT LENGTH('H02') AS literal_len, LENGTH(?) AS bound_len, LENGTH(CAST(? AS BINARY)) AS binary_len", ['H02', 'H02']); save('scalar-complete');
  const rows = await client.execute('SELECT collection_name FROM stepfun_kb_registry WHERE kb_id=?', [kbId]);
  if (rows.length !== 1) throw new Error('Expected own existing KB');
  const collection = await client.getCollection({ name: rows[0].collection_name, embeddingFunction: null });
  if (!/^[0-9a-f]{32}$/i.test(collection.collectionId)) throw new Error('Expected public version-2 collection ID');
  const table = `\`c$v2$${collection.collectionId}\``;
  const stored = await client.execute(`SELECT LENGTH(_id) AS id_len, HEX(_id) AS id_hex, JSON_OBJECT('id',_id) AS encoded_id FROM ${table} WHERE _id=CAST(? AS BINARY)`, [logicalId]);
  if (stored.length !== 1) throw new Error('Expected one existing document');
  const row = stored[0];
  const object = typeof row.encoded_id === 'string' ? JSON.parse(row.encoded_id) : row.encoded_id;
  const value = object.id, prefix = value.replace(/\0+$/, '');
  report.stored = { lengthFromSql: row.id_len, hexLength: row.id_hex.length,
    hexPrefix: row.id_hex.slice(0, 48), hexSuffixAllZero: /^0*$/.test(row.id_hex.slice(Buffer.byteLength(logicalId) * 2)),
    encodedId: { prefix, utf8Bytes: Buffer.byteLength(value), trailingNuls: value.length - prefix.length,
      sha256: createHash('sha256').update(value).digest('hex') } };
  save('stored-id-and-json-complete');
  const fetched = await collection.get({ ids: [logicalId], include: ['documents', 'metadatas'] });
  report.publicSdkGet = { ids: fetched.ids, documentCount: fetched.documents?.length ?? null };
  report.status = 'complete'; report.finishedAt = new Date().toISOString(); save('all-read-only-queries-complete');
  await client.close(); process.exit(0);
} catch (error) {
  report.status = 'failed'; report.error = String(error.message || error); save('failed');
  await client.close().catch(() => {}); process.exit(1);
}
