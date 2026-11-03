import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { dirname, resolve } from 'node:path';
import test from 'node:test';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const serverUrl = pathToFileURL(resolve(root, 'server.mjs')).href;

// Run imports in separate, deliberately minimal environments. No API keys or
// unrelated user configuration are copied into child processes.
function probe(port, exerciseRequests = false) {
  const env = {};
  for (const name of ['SystemRoot', 'WINDIR', 'PATH', 'PATHEXT', 'TEMP', 'TMP']) {
    if (process.env[name] !== undefined) env[name] = process.env[name];
  }
  if (port !== undefined) env.STEPFUN_HTTP_PORT = port;
  const script = `
    import { EventEmitter } from 'node:events';
    import { Readable } from 'node:stream';
    import { createHttpServer, HTTP_HOST, HTTP_PORT } from ${JSON.stringify(serverUrl)};
    const result = { host: HTTP_HOST, port: HTTP_PORT };
    if (${exerciseRequests}) {
      const bridge = {
        health: async () => ({ ok: true }), listKbs: async () => [],
        createKb: async () => ({ ok: true }), importDocuments: async () => ({}),
        search: async () => ({}),
      };
      const server = createHttpServer({ bridge, publicDir: ${JSON.stringify(root)} });
      async function request(method, host, origin) {
        const req = Readable.from(method === 'POST' ? [Buffer.from('{}')] : []);
        Object.assign(req, { method, url: method === 'POST' ? '/api/kbs' : '/api/health',
          complete: true, headers: { host, ...(origin === undefined ? {} : { origin }),
            ...(method === 'POST' ? { 'content-type': 'application/json', 'content-length': '2' } : {}) } });
        return await new Promise((resolveRequest) => {
          const res = new EventEmitter();
          Object.assign(res, { destroyed: false, writableEnded: false, headersSent: false });
          res.writeHead = (status) => { res.status = status; res.headersSent = true; };
          res.end = () => { res.writableEnded = true; res.emit('finish'); resolveRequest(res.status); };
          server.emit('request', req, res);
        });
      }
      result.requests = [
        await request('GET', '127.0.0.1:' + HTTP_PORT),
        await request('GET', 'localhost:' + HTTP_PORT),
        await request('GET', '127.0.0.1:34021'),
        await request('GET', 'example.test:' + HTTP_PORT),
        await request('POST', '127.0.0.1:' + HTTP_PORT, 'http://127.0.0.1:' + HTTP_PORT),
        await request('POST', '127.0.0.1:' + HTTP_PORT, 'http://localhost:' + HTTP_PORT),
      ];
      if (HTTP_PORT === 80) {
        const combinations = [];
        for (const localHost of ['127.0.0.1', 'localhost']) {
          for (const hostSuffix of ['', ':80']) {
            for (const originSuffix of ['', ':80']) {
              combinations.push(await request('POST', localHost + hostSuffix,
                'http://' + localHost + originSuffix));
            }
          }
        }
        result.defaultPort = {
          combinations,
          getLoopback: await request('GET', '127.0.0.1'),
          getLocalhost: await request('GET', 'localhost'),
          otherHost: await request('GET', 'example.test'),
          spoofedOrigin: await request('POST', '127.0.0.1', 'http://example.test'),
          crossAlias: await request('POST', '127.0.0.1:80', 'http://localhost'),
          wrongOriginPort: await request('POST', '127.0.0.1', 'http://127.0.0.1:81'),
          wrongHostPort: await request('POST', '127.0.0.1:81', 'http://127.0.0.1'),
          wrongScheme: await request('POST', '127.0.0.1', 'https://127.0.0.1'),
          originPath: await request('POST', '127.0.0.1', 'http://127.0.0.1/path'),
          originUserinfo: await request('POST', '127.0.0.1', 'http://user@127.0.0.1'),
          paddedOriginPort: await request('POST', '127.0.0.1', 'http://127.0.0.1:080'),
          paddedHostPort: await request('POST', 'localhost:080', 'http://localhost'),
          noHost: await request('POST', undefined, 'http://localhost'),
          noOrigin: await request('POST', 'localhost'),
        };
      } else {
        result.nonDefault = {
          noPortHost: await request('GET', '127.0.0.1'),
          noPortOrigin: await request('POST', '127.0.0.1:' + HTTP_PORT, 'http://127.0.0.1'),
        };
      }
    }
    console.log(JSON.stringify(result));
  `;
  return spawnSync(process.execPath, ['--input-type=module', '--eval', script], {
    cwd: root, env, encoding: 'utf8', timeout: 10_000, windowsHide: true,
  });
}

test('default host and port remain the loopback application address', () => {
  const result = probe(undefined);
  assert.equal(result.status, 0);
  assert.deepEqual(JSON.parse(result.stdout), { host: '127.0.0.1', port: 34021 });
});

test('explicit port changes only the loopback port and permitted local origins', () => {
  const result = probe('34022', true);
  assert.equal(result.status, 0);
  assert.deepEqual(JSON.parse(result.stdout), {
    host: '127.0.0.1', port: 34022, requests: [200, 200, 403, 403, 201, 403],
    nonDefault: { noPortHost: 403, noPortOrigin: 403 },
  });
});

test('invalid port configuration is rejected before service startup', () => {
  for (const port of ['', '0', '65536', '-1', '+1', '1.5', '1e3', 'NaN', ' 34022', '34022 ']) {
    const result = probe(port);
    assert.ifError(result.error);
    assert.notEqual(result.status, null);
    assert.notEqual(result.status, 0, `expected invalid value to fail: ${JSON.stringify(port)}`);
    assert.equal(result.stdout, '');
    assert.match(result.stderr, /STEPFUN_HTTP_PORT must be an integer from 1 to 65535/u);
  }
});

test('valid port boundaries are accepted', () => {
  for (const port of ['1', '65535']) {
    const result = probe(port);
    assert.equal(result.status, 0);
    assert.equal(JSON.parse(result.stdout).port, Number(port));
  }
});

test('HTTP port 80 accepts equivalent explicit and implicit local origins only', () => {
  const result = probe('80', true);
  assert.equal(result.status, 0);
  const { defaultPort } = JSON.parse(result.stdout);
  assert.deepEqual(defaultPort.combinations, Array(8).fill(201));
  assert.equal(defaultPort.getLoopback, 200);
  assert.equal(defaultPort.getLocalhost, 200);
  assert.equal(defaultPort.otherHost, 403);
  assert.equal(defaultPort.spoofedOrigin, 403);
  assert.equal(defaultPort.crossAlias, 403);
  assert.equal(defaultPort.wrongOriginPort, 403);
  assert.equal(defaultPort.wrongHostPort, 403);
  assert.equal(defaultPort.wrongScheme, 403);
  assert.equal(defaultPort.originPath, 403);
  assert.equal(defaultPort.originUserinfo, 403);
  assert.equal(defaultPort.paddedOriginPort, 403);
  assert.equal(defaultPort.paddedHostPort, 403);
  assert.equal(defaultPort.noHost, 201);
  assert.equal(defaultPort.noOrigin, 201);
});
