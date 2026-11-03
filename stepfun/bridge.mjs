import { randomUUID, createHash } from 'node:crypto';
import { isAbsolute } from 'node:path';
import { preparedRrfQuery, preparedRrfResults } from './prepared-rrf.mjs';

export const DATABASE = 'stepfun_kb_demo';
export const SDK_VERSION = '1.4.0';
export const MODEL_REPO = 'Xenova/all-MiniLM-L6-v2';
export const MODEL_REVISION = '751bff37182d3f1213fa05d7196b954e230abad9';
export const DIMENSION = 384;
export const PROFILES = Object.freeze(['fp32', 'fp16', 'q8']);
const REGISTRY = 'stepfun_kb_registry';
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

export class BridgeError extends Error {
  constructor(status, code, message, details, cause) {
    super(message, cause === undefined ? undefined : { cause });
    this.name = 'BridgeError';
    this.status = status;
    this.code = code;
    if (details !== undefined) this.details = details;
  }
}

function invalid(message) { throw new BridgeError(400, 'INVALID_REQUEST', message); }
function object(value, label) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) invalid(`${label} must be an object`);
  return value;
}
function keys(value, allowed, label) {
  object(value, label);
  if (Object.keys(value).some(key => !allowed.includes(key))) invalid(`${label} contains an unsupported field`);
}
function text(value, label, maxBytes, trim = false) {
  if (typeof value !== 'string') invalid(`${label} must be a string`);
  const normalized = trim ? value.trim() : value;
  if (!normalized.trim() || normalized.includes('\0') || Buffer.byteLength(normalized, 'utf8') > maxBytes) {
    invalid(`${label} is empty or exceeds its size limit`);
  }
  return normalized;
}
export function modelFor(profile) {
  if (!PROFILES.includes(profile)) invalid('profile must be fp32, fp16, or q8');
  return { repo: MODEL_REPO, revision: MODEL_REVISION, precision: profile,
    dimension: DIMENSION, pooling: 'mean', normalize: true };
}
export function validateModel(value, profile) {
  keys(value, ['repo', 'revision', 'precision', 'dimension', 'pooling', 'normalize'], 'model');
  const expected = modelFor(profile);
  if (Object.entries(expected).some(([key, expectedValue]) => value[key] !== expectedValue)) {
    throw new BridgeError(409, 'MODEL_MISMATCH', 'The browser model must match this knowledge base');
  }
  return expected;
}
export function validateVector(value, label = 'embedding') {
  if (!Array.isArray(value) || value.length !== DIMENSION) invalid(`${label} must have 384 dimensions`);
  let norm = 0;
  for (const component of value) {
    if (typeof component !== 'number' || !Number.isFinite(component)) invalid(`${label} must contain finite numbers`);
    norm += component * component;
  }
  if (!Number.isFinite(norm) || norm <= 0) invalid(`${label} must have a finite nonzero norm`);
  return value.slice();
}
function metadata(value) {
  if (value === undefined) return {};
  object(value, 'metadata');
  const walk = (node, depth) => {
    if (depth > 8) invalid('metadata exceeds maximum depth');
    if (node === null || typeof node === 'string' || typeof node === 'boolean') return;
    if (typeof node === 'number' && Number.isFinite(node)) return;
    if (Array.isArray(node)) { for (const item of node) walk(item, depth + 1); return; }
    if (typeof node === 'object') { for (const item of Object.values(node)) walk(item, depth + 1); return; }
    invalid('metadata must contain JSON values');
  };
  walk(value, 0);
  if (Object.hasOwn(value, '_stepfun')) invalid('metadata._stepfun is reserved');
  const encoded = JSON.stringify(value);
  if (Buffer.byteLength(encoded, 'utf8') > 16384) invalid('metadata exceeds 16 KiB');
  return JSON.parse(encoded);
}
export function validateCreate(value) {
  keys(value, ['label', 'profile'], 'request');
  return { label: text(value.label, 'label', 480, true), profile: modelFor(value.profile).precision };
}
export function validateImport(value, profile) {
  keys(value, ['documents', 'embeddings', 'model'], 'request');
  const model = validateModel(value.model, profile);
  if (!Array.isArray(value.documents) || value.documents.length < 1 || value.documents.length > 100) {
    invalid('documents must contain 1 to 100 entries');
  }
  if (!Array.isArray(value.embeddings) || value.embeddings.length !== value.documents.length) {
    invalid('embeddings and documents must have equal lengths');
  }
  const seen = new Set();
  const documents = value.documents.map((row, index) => {
    keys(row, ['id', 'text', 'metadata'], `documents[${index}]`);
    const id = text(row.id, 'document id', 512);
    if (seen.has(id)) invalid('document IDs must be unique within a batch');
    seen.add(id);
    return { id, text: text(row.text, 'document text', 65536), metadata: metadata(row.metadata) };
  });
  return { model, documents, embeddings: value.embeddings.map((vec, index) => validateVector(vec, `embeddings[${index}]`)) };
}
export function validateSearch(value, profile) {
  keys(value, ['text', 'embedding', 'model', 'topK'], 'request');
  const model = validateModel(value.model, profile);
  const topK = value.topK === undefined ? 5 : value.topK;
  if (!Number.isInteger(topK) || topK < 1 || topK > 50) invalid('topK must be an integer from 1 to 50');
  return { text: text(value.text, 'query text', 8192), embedding: validateVector(value.embedding), model, topK };
}
function kbId(value) {
  if (typeof value !== 'string' || !UUID.test(value)) invalid('Invalid knowledge base ID');
  return value;
}
function revision(value) {
  const n = Number(value);
  if (!Number.isSafeInteger(n) || n < 0) throw new BridgeError(500, 'INVALID_REGISTRY', 'Invalid knowledge base revision');
  return n;
}
function kbPublic(row) {
  return { id: row.kb_id, label: row.label, profile: row.profile, revision: revision(row.revision), status: row.state };
}
function fingerprint(model) { return createHash('sha256').update(JSON.stringify(model)).digest('hex'); }
function databaseError(error, details) {
  if (error instanceof BridgeError) return error;
  return new BridgeError(503, 'DATABASE_OPERATION_FAILED', 'The database operation failed; no successful completion is claimed', details, error);
}

/**
 * Explicit runtime factory. Importing this module does not load seekdb, read
 * environment variables, start HTTP, or contact the database.
 * sdk is an optional dependency seam for offline checks; production omits it.
 * connection.password is explicit (default empty), avoiding the SDK's env fallback.
 */
export async function createBridge({ connection = {}, sdk, onSqlEvent } = {}) {
  const embedded = Object.hasOwn(connection, 'path');
  if (embedded && (typeof connection.path !== 'string' || !connection.path.trim() || !isAbsolute(connection.path))) invalid('Embedded database path must be absolute');
  if (embedded && ['host', 'port', 'user', 'password'].some(key => Object.hasOwn(connection, key))) invalid('Choose embedded path or server connection, not both');
  if (connection.host !== undefined && connection.host !== '127.0.0.1') invalid('Database host must be 127.0.0.1');
  const port = connection.port ?? 36143;
  if (!Number.isInteger(port) || port < 1 || port > 65535) invalid('Invalid local database port');
  const user = connection.user ?? 'root';
  const password = connection.password ?? '';
  if (typeof user !== 'string' || typeof password !== 'string') invalid('Database credentials must be strings');
  if (Object.hasOwn(connection, 'database') && connection.database !== DATABASE) invalid('Database is fixed to stepfun_kb_demo');
  // Optional observer is installed by root before SDK import; it must never log
  // connection configuration. See SQL_TRACE_PLAN.md for the supported limitation.
  if (onSqlEvent !== undefined && typeof onSqlEvent !== 'function') invalid('onSqlEvent must be a function');
  const api = sdk ?? await import('seekdb');
  const config = embedded ? { path: connection.path } : { host: '127.0.0.1', port, user, password, queryTimeout: 60000 };
  const admin = new api.SeekdbAdminClient(config);
  try { await admin.createDatabase(DATABASE); }
  catch (error) { throw databaseError(error, { stage: 'initialize-database' }); }
  finally { await admin.close(); }
  const client = new api.SeekdbClient({ ...config, database: DATABASE });
  let tail = Promise.resolve();
  let closed = false;
  function serial(task) {
    const result = tail.then(async () => {
      if (closed) throw new BridgeError(503, 'BRIDGE_CLOSED', 'The database bridge is closed');
      return task();
    });
    tail = result.catch(() => {});
    return result;
  }
  async function execute(sql, params = []) {
    // Public SDK execute(sql, params) is supported and binds values through mysql2.
    return client.execute(sql, params);
  }
  try {
    await execute(`CREATE TABLE IF NOT EXISTS ${REGISTRY} (
      kb_id VARCHAR(36) NOT NULL PRIMARY KEY,
      label VARCHAR(480) NOT NULL,
      profile VARCHAR(8) NOT NULL,
      collection_name VARCHAR(80) NOT NULL,
      model_manifest JSON NOT NULL,
      revision BIGINT NOT NULL DEFAULT 0,
      state VARCHAR(16) NOT NULL,
      updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)
    )`);
  } catch (error) { await client.close(); throw databaseError(error, { stage: 'initialize-registry' }); }
  async function rowFor(id) {
    kbId(id);
    const rows = await execute(`SELECT kb_id,label,profile,collection_name,model_manifest,revision,state FROM ${REGISTRY} WHERE kb_id = ?`, [id]);
    if (!rows?.length) throw new BridgeError(404, 'KB_NOT_FOUND', 'Knowledge base not found');
    const row = rows[0];
    const expectedModel = modelFor(row.profile);
    let stored;
    try { stored = typeof row.model_manifest === 'string' ? JSON.parse(row.model_manifest) : row.model_manifest; }
    catch { throw new BridgeError(500, 'INVALID_REGISTRY', 'Invalid knowledge base model manifest'); }
    if (JSON.stringify(expectedModel) !== JSON.stringify(stored)) {
      // Compare values rather than relying on JSON key order returned by the DB.
      if (!stored || Object.entries(expectedModel).some(([key, value]) => stored[key] !== value)) {
        throw new BridgeError(500, 'INVALID_REGISTRY', 'Knowledge base model manifest does not match the fixed model');
      }
    }
    const expectedCollection = `stepfun_${id.replaceAll('-', '')}_${row.profile}`;
    if (row.collection_name !== expectedCollection) {
      throw new BridgeError(500, 'INVALID_REGISTRY', 'Invalid registered collection');
    }
    revision(row.revision);
    return row;
  }
  async function collectionFor(row) {
    return client.getCollection({ name: row.collection_name, embeddingFunction: null });
  }
  const emit = event => { if (onSqlEvent) { try { onSqlEvent(event); } catch {} } };
  const bridge = {
    health: () => serial(async () => {
      try {
        const rows = await execute('SELECT VERSION() AS version');
        return { ok: true, database: DATABASE, databaseVersion: rows?.[0]?.version ?? null,
          sdkTargetVersion: SDK_VERSION, storageMode: embedded ? 'embedded' : 'server', embedding: 'browser-only', dimension: DIMENSION };
      } catch (error) { throw databaseError(error, { stage: 'health' }); }
    }),
    listKbs: () => serial(async () => {
      try {
        const rows = await execute(`SELECT kb_id,label,profile,revision,state FROM ${REGISTRY} ORDER BY updated_at,kb_id`);
        return { kbs: (rows ?? []).map(kbPublic) };
      } catch (error) { throw databaseError(error, { stage: 'list-knowledge-bases' }); }
    }),
    createKb: value => serial(async () => {
      const body = validateCreate(value);
      const id = randomUUID();
      const name = `stepfun_${id.replaceAll('-', '')}_${body.profile}`;
      const model = modelFor(body.profile);
      let inserted = false;
      try {
        await execute(`INSERT INTO ${REGISTRY} (kb_id,label,profile,collection_name,model_manifest,revision,state) VALUES (?,?,?,?,?,0,?)`,
          [id, body.label, body.profile, name, JSON.stringify(model), 'creating']);
        inserted = true;
        const schema = new api.Schema({
          fulltextIndex: new api.FulltextIndexConfig('ik', { ik_mode: 'smart' }),
          vectorIndex: new api.VectorIndexConfig({ hnsw: { dimension: DIMENSION, distance: 'cosine' }, embeddingFunction: null }),
        });
        await client.createCollection({ name, schema, embeddingFunction: null });
        await execute(`UPDATE ${REGISTRY} SET state=? WHERE kb_id=?`, ['ready', id]);
        return { id, label: body.label, profile: body.profile, revision: 0, status: 'ready' };
      } catch (error) {
        if (inserted) { try { await execute(`UPDATE ${REGISTRY} SET state=? WHERE kb_id=?`, ['failed', id]); } catch {} }
        throw databaseError(error, { stage: 'create-knowledge-base', id, registryCreated: inserted });
      }
    }),
    importDocuments: (id, value) => serial(async () => {
      const start = performance.now();
      let row;
      let attemptedWrite = false;
      let stateChangeAttempted = false;
      let refreshed = false;
      try {
        row = await rowFor(id);
        // One bridge process is supported. A persisted writing state after a
        // crash is retryable: the same complete batch can be idempotently upserted.
        if (!['ready', 'dirty', 'writing'].includes(row.state)) throw new BridgeError(409, 'KB_NOT_READY', 'Knowledge base is not ready for import');
        const body = validateImport(value, row.profile);
        const current = revision(row.revision);
        if (current === Number.MAX_SAFE_INTEGER) throw new BridgeError(409, 'REVISION_LIMIT', 'Knowledge base revision limit reached');
        const collection = await collectionFor(row);
        stateChangeAttempted = true;
        await execute(`UPDATE ${REGISTRY} SET state=? WHERE kb_id=?`, ['writing', id]);
        const writeStart = performance.now();
        attemptedWrite = true;
        await collection.upsert({ ids: body.documents.map(doc => doc.id), documents: body.documents.map(doc => doc.text),
          embeddings: body.embeddings,
          metadatas: body.documents.map(doc => ({ ...doc.metadata, _stepfun: { modelFingerprint: fingerprint(body.model) } })) });
        const writeMs = performance.now() - writeStart;
        const refreshStart = performance.now();
        // SDK refresh_index() can silently no-op when its VERSION probe fails.
        // Use the same real fixed procedure through public SDK value-bound SQL
        // execution, so a failed/unsupported refresh becomes a reported failure.
        await execute('CALL dbms_index_manager.refresh();');
        refreshed = true;
        const refreshMs = performance.now() - refreshStart;
        const count = Number(await collection.count());
        if (!Number.isSafeInteger(count) || count < 0) throw new Error('Invalid collection count');
        await execute(`UPDATE ${REGISTRY} SET revision=revision+1,state=? WHERE kb_id=?`, ['ready', id]);
        return { revision: current + 1, count, timings: { writeMs, refreshMs, totalMs: performance.now() - start } };
      } catch (error) {
        if (stateChangeAttempted) { try { await execute(`UPDATE ${REGISTRY} SET state=? WHERE kb_id=?`, ['dirty', id]); } catch {} }
        throw databaseError(error, { stage: 'import', id: typeof id === 'string' && UUID.test(id) ? id : undefined,
          mayHavePartialWrites: attemptedWrite, refreshCompleted: refreshed });
      }
    }),
    search: (id, value) => serial(async () => {
      try {
        const row = await rowFor(id);
        if (row.state !== 'ready') throw new BridgeError(409, 'KB_NOT_READY', 'Knowledge base has incomplete writes; complete a successful import before searching');
        const body = validateSearch(value, row.profile);
        const collection = await collectionFor(row);
        const queryStart = performance.now();
        // This event proves API invocation only. Actual SQL tracing is separate.
        emit({ kind: 'hybrid-api-start', kbId: id, revision: revision(row.revision) });
        // One database-side RRF statement, preserving the pinned engine's query
        // structure. Bind all data directly: SDK dynamic-SQL keyword checks and
        // the native SEARCH query-string quote bug cannot reinterpret this text.
        const { sql, params } = preparedRrfQuery(collection, body);
        const page = await execute(sql, params);
        const queryMs = performance.now() - queryStart;
        const results = preparedRrfResults(page, body.topK);
        emit({ kind: 'hybrid-api-complete', transport: embedded ? 'embedded' : 'server',
          statementSha256: createHash('sha256').update(sql).digest('hex'), parameterSha256: fingerprint(params),
          kbId: id, revision: revision(row.revision), count: results.length, queryMs });
        return { results, queryMs, revision: revision(row.revision) };
      } catch (error) { throw databaseError(error, { stage: 'search' }); }
    }),
    close: () => serial(async () => { closed = true; await client.close(); }),
  };
  return bridge;
}
