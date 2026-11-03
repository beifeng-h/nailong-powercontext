import { appendFileSync, mkdirSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createBridge, SDK_VERSION } from './bridge.mjs';
import { createHttpServer, HTTP_HOST, HTTP_PORT } from './server.mjs';

const root = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const sdkPackage = JSON.parse(readFileSync(resolve(dirname(require.resolve('seekdb')), '../package.json'), 'utf8'));
if (sdkPackage.version !== SDK_VERSION) throw new Error('Use the delivered seekdb package lock');
const storageMode = process.env.STEPFUN_DB_MODE || 'embedded';
if (!['embedded', 'server'].includes(storageMode)) throw new Error('STEPFUN_DB_MODE must be embedded or server');
// Keep the official frozen native runtime and its cache local to this project.
process.env.SEEKDB_BINDINGS_CACHE_DIR = resolve(root, 'runtime', 'native-bindings');
process.env.SEEKDB_BINDINGS_BASE_URL = 'https://oceanbase-seekdb-builds.s3.ap-southeast-1.amazonaws.com/js-bindings/all_commits/469a55dc84ea7a9e077161a8b454871a9adaff35';
const connection = storageMode === 'embedded' ? {
  path: resolve(root, 'runtime', 'embedded-db-v1.4'),
} : {
  host: '127.0.0.1', port: Number(process.env.STEPFUN_DB_PORT || '36143'),
  user: process.env.STEPFUN_DB_USER || 'root', password: process.env.STEPFUN_DB_PASSWORD ?? '',
};
let bridge, server, restoreCapture;
try {
  let onSqlEvent;
  if (process.env.STEPFUN_CAPTURE_SQL === '1') {
    const directory = resolve(root, 'runtime'); mkdirSync(directory, { recursive: true });
    const path = resolve(directory, `sql-trace-${Date.now()}.jsonl`);
    const apiPath = resolve(directory, `bridge-api-events-${Date.now()}.jsonl`);
    onSqlEvent = event => appendFileSync(apiPath, JSON.stringify({ at: new Date().toISOString(), evidenceLevel: 'public-sdk-api', ...event }) + '\n');
    const { installSqlCapture } = await import('./sql-capture.mjs');
    restoreCapture = await installSqlCapture({
      includeGeneratedSql: process.env.STEPFUN_TRACE_RAW_SQL === '1',
      onEvent: event => appendFileSync(path, JSON.stringify({ at: new Date().toISOString(), ...event }) + '\n'),
    });
  }
  bridge = await createBridge({ connection, onSqlEvent });
  server = createHttpServer({ bridge, publicDir: resolve(root, 'public') });
  server.on('error', () => { console.error('Local HTTP service could not start'); process.exitCode = 1; });
  await new Promise((done, fail) => { server.once('error', fail); server.listen(HTTP_PORT, HTTP_HOST, done); });
  console.log(JSON.stringify({ ready: true, url: `http://${HTTP_HOST}:${HTTP_PORT}`, database: 'stepfun_kb_demo', storageMode, sdk: sdkPackage.version, inference: 'browser-only' }));
} catch (error) {
  console.error(JSON.stringify({ ready: false, code: error?.code || 'STARTUP_FAILED', stage: error?.details?.stage || 'startup' }));
  await bridge?.close().catch(() => {}); restoreCapture?.(); process.exitCode = 1;
}
let closing = false;
async function close() {
  if (closing) return; closing = true;
  if (server?.listening) await new Promise(done => server.close(done));
  await bridge?.close().catch(() => {}); restoreCapture?.();
}
process.once('SIGINT', close);
process.once('SIGTERM', close);
