import http from 'node:http';
import { open, realpath } from 'node:fs/promises';
import { extname, isAbsolute, relative, resolve, sep } from 'node:path';
import { pipeline } from 'node:stream/promises';

export const HTTP_HOST = '127.0.0.1';
const requestedPort = process.env.STEPFUN_HTTP_PORT;
if (requestedPort !== undefined && (!/^[0-9]{1,5}$/u.test(requestedPort)
  || Number(requestedPort) < 1 || Number(requestedPort) > 65535)) {
  throw new RangeError('STEPFUN_HTTP_PORT must be an integer from 1 to 65535');
}
export const HTTP_PORT = requestedPort === undefined ? 34021 : Number(requestedPort);
export const MAX_JSON_BYTES = 4 * 1024 * 1024;

const LOCAL_HOSTS = new Set([`${HTTP_HOST}:${HTTP_PORT}`, `localhost:${HTTP_PORT}`]);
if (HTTP_PORT === 80) {
  LOCAL_HOSTS.add(HTTP_HOST);
  LOCAL_HOSTS.add('localhost');
}
const MIME_TYPES = new Map([
  ['.html', 'text/html; charset=utf-8'],
  ['.js', 'text/javascript; charset=utf-8'],
  ['.mjs', 'text/javascript; charset=utf-8'],
  ['.css', 'text/css; charset=utf-8'],
  ['.json', 'application/json; charset=utf-8'],
  ['.txt', 'text/plain; charset=utf-8'],
  ['.svg', 'image/svg+xml'],
  ['.png', 'image/png'],
  ['.jpg', 'image/jpeg'],
  ['.jpeg', 'image/jpeg'],
  ['.webp', 'image/webp'],
  ['.ico', 'image/x-icon'],
  ['.wasm', 'application/wasm'],
]);

class HttpError extends Error {
  constructor(status, code, message, { close = false, allow } = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.close = close;
    this.allow = allow;
  }
}

function checkLocalRequest(request) {
  const host = request.headers.host;
  if (host !== undefined && (typeof host !== 'string' || !LOCAL_HOSTS.has(host.toLowerCase()))) {
    throw new HttpError(403, 'HOST_NOT_ALLOWED', 'Use the local application address.');
  }
  const origin = request.headers.origin;
  if (request.method === 'POST' && origin !== undefined) {
    const allowedOrigin = typeof origin === 'string'
      && [...LOCAL_HOSTS].some((entry) => origin === `http://${entry}`);
    const originHost = allowedOrigin ? origin.slice('http://'.length) : undefined;
    const normalizeDefaultPort = (value) => HTTP_PORT === 80 ? value.replace(/:80$/u, '') : value;
    const sameHost = host === undefined || (allowedOrigin
      && normalizeDefaultPort(host.toLowerCase()) === normalizeDefaultPort(originHost));
    if (!allowedOrigin || !sameHost) {
      throw new HttpError(403, 'ORIGIN_NOT_ALLOWED', 'Use the application from its local origin.', { close: true });
    }
  }
}

function isForbiddenSegment(segment) {
  return segment.startsWith('.')
    || segment.toLowerCase() === 'node_modules'
    || /[\\/:%\u0000-\u001f\u007f]/u.test(segment)
    || /[. ]$/u.test(segment);
}

function parsePath(requestTarget) {
  if (typeof requestTarget !== 'string' || !requestTarget.startsWith('/')
    || requestTarget.startsWith('//') || /[\\#\u0000-\u001f\u007f]/u.test(requestTarget)) {
    throw new HttpError(400, 'INVALID_PATH', 'The request path is invalid.');
  }
  const rawPath = requestTarget.split('?', 1)[0];
  let segments;
  try {
    segments = rawPath.slice(1).split('/').map((segment) => decodeURIComponent(segment));
  } catch {
    throw new HttpError(400, 'INVALID_PATH', 'The request path is invalid.');
  }
  if (segments.some(isForbiddenSegment) || segments.some((segment, index) => !segment && index < segments.length - 1)) {
    throw new HttpError(403, 'PATH_NOT_ALLOWED', 'The requested path is not available.');
  }
  return { pathname: `/${segments.join('/')}`, segments };
}

function sendJson(response, status, value, headers = {}, head = false) {
  const body = Buffer.from(JSON.stringify(value));
  response.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': body.byteLength,
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
    ...headers,
  });
  response.end(head ? undefined : body);
}

function sendError(request, response, error) {
  if (response.destroyed || response.writableEnded) return;
  if (response.headersSent) {
    response.destroy();
    return;
  }
  const isBridgeError = error?.name === 'BridgeError';
  const isPublicError = (error instanceof HttpError || isBridgeError)
    && Number.isInteger(error.status) && error.status >= 400 && error.status <= 599
    && typeof error.code === 'string' && /^[A-Za-z0-9_.-]{1,80}$/u.test(error.code)
    && typeof error.message === 'string';
  const payload = isPublicError
    ? { code: error.code, message: error.message }
    : { code: 'INTERNAL_ERROR', message: 'The request could not be completed.' };
  if (isPublicError && isBridgeError && error.details !== undefined) payload.details = error.details;
  const headers = {};
  if (error instanceof HttpError && error.allow) headers.Allow = error.allow;
  if ((error instanceof HttpError && error.close) || (request.method === 'POST' && !request.complete)) {
    headers.Connection = 'close';
    response.once('finish', () => request.destroy());
  }
  try {
    sendJson(response, isPublicError ? error.status : 500, { error: payload }, headers, request.method === 'HEAD');
  } catch {
    sendJson(response, 500, { error: { code: 'INTERNAL_ERROR', message: 'The request could not be completed.' } }, headers, request.method === 'HEAD');
  }
}

async function readJson(request) {
  const contentType = request.headers['content-type'];
  if (typeof contentType !== 'string' || contentType.split(';', 1)[0].trim().toLowerCase() !== 'application/json') {
    throw new HttpError(415, 'JSON_REQUIRED', 'Send an application/json request body.', { close: true });
  }
  if (request.headers['content-encoding'] !== undefined && request.headers['content-encoding'] !== 'identity') {
    throw new HttpError(415, 'CONTENT_ENCODING_NOT_SUPPORTED', 'Send an uncompressed JSON body.', { close: true });
  }
  const lengthHeader = request.headers['content-length'];
  let declaredLength;
  if (lengthHeader !== undefined) {
    if (typeof lengthHeader !== 'string' || !/^(0|[1-9][0-9]*)$/u.test(lengthHeader)
      || request.headers['transfer-encoding'] !== undefined) {
      throw new HttpError(400, 'INVALID_CONTENT_LENGTH', 'The request body length is invalid.', { close: true });
    }
    declaredLength = Number(lengthHeader);
    if (!Number.isSafeInteger(declaredLength) || declaredLength > MAX_JSON_BYTES) {
      throw new HttpError(413, 'BODY_TOO_LARGE', 'The JSON body must not exceed 4 MiB.', { close: true });
    }
  }
  const body = await new Promise((resolveBody, rejectBody) => {
    const chunks = [];
    let bytes = 0;
    let settled = false;
    const cleanup = () => {
      request.off('data', onData);
      request.off('end', onEnd);
      request.off('aborted', onAborted);
      request.off('error', onError);
    };
    const fail = (error) => {
      if (settled) return;
      settled = true;
      cleanup();
      request.pause();
      rejectBody(error);
    };
    const onData = (chunk) => {
      const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
      bytes += buffer.byteLength;
      if (bytes > MAX_JSON_BYTES) {
        fail(new HttpError(413, 'BODY_TOO_LARGE', 'The JSON body must not exceed 4 MiB.', { close: true }));
        return;
      }
      chunks.push(buffer);
    };
    const onEnd = () => {
      if (settled) return;
      settled = true;
      cleanup();
      resolveBody(Buffer.concat(chunks, bytes));
    };
    const onAborted = () => fail(new HttpError(400, 'INCOMPLETE_BODY', 'The request body was incomplete.', { close: true }));
    const onError = () => fail(new HttpError(400, 'INVALID_BODY', 'The request body could not be read.', { close: true }));
    request.on('data', onData);
    request.once('end', onEnd);
    request.once('aborted', onAborted);
    request.once('error', onError);
  });
  if (declaredLength !== undefined && body.byteLength !== declaredLength) {
    throw new HttpError(400, 'INCOMPLETE_BODY', 'The request body length did not match Content-Length.', { close: true });
  }
  let value;
  try {
    value = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(body));
  } catch {
    throw new HttpError(400, 'INVALID_JSON', 'The request body must contain valid UTF-8 JSON.');
  }
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new HttpError(400, 'JSON_OBJECT_REQUIRED', 'The request body must be a JSON object.');
  }
  return value;
}

async function serveStatic(request, response, publicDir, segments) {
  const fileSegments = segments.length === 1 && segments[0] === '' ? ['index.html'] : segments;
  if (fileSegments.at(-1) === '') throw new HttpError(404, 'NOT_FOUND', 'The requested file was not found.');
  let handle;
  try {
    const root = await realpath(publicDir);
    const filename = await realpath(resolve(root, ...fileSegments));
    const localPath = relative(root, filename);
    if (!localPath || localPath === '..' || localPath.startsWith(`..${sep}`) || isAbsolute(localPath)
      || localPath.split(sep).some(isForbiddenSegment)) {
      throw new HttpError(403, 'PATH_NOT_ALLOWED', 'The requested path is not available.');
    }
    handle = await open(filename, 'r');
    const info = await handle.stat();
    if (!info.isFile()) throw new HttpError(404, 'NOT_FOUND', 'The requested file was not found.');
    response.writeHead(200, {
      'Content-Type': MIME_TYPES.get(extname(filename).toLowerCase()) ?? 'application/octet-stream',
      'Content-Length': info.size,
      'Cache-Control': 'no-cache',
      'X-Content-Type-Options': 'nosniff',
    });
    if (request.method === 'HEAD') {
      await handle.close();
      handle = undefined;
      response.end();
      return;
    }
    const stream = handle.createReadStream();
    handle = undefined;
    await pipeline(stream, response);
  } catch (error) {
    if (handle) await handle.close().catch(() => {});
    if (['ENOENT', 'ENOTDIR', 'EACCES', 'EPERM', 'ELOOP'].includes(error?.code)) {
      throw new HttpError(404, 'NOT_FOUND', 'The requested file was not found.');
    }
    throw error;
  }
}

/**
 * Create an unbound HTTP server. Only the optional local port is configured at import.
 * The startup owner supplies a bridge and an absolute public directory, then calls:
 *   server.listen(HTTP_PORT, HTTP_HOST);
 * This module deliberately has no CLI bootstrap or automatic listen call.
 */
export function createHttpServer({ bridge, publicDir } = {}) {
  for (const method of ['health', 'listKbs', 'createKb', 'importDocuments', 'search']) {
    if (typeof bridge?.[method] !== 'function') throw new TypeError(`bridge.${method} must be a function`);
  }
  if (typeof publicDir !== 'string' || !isAbsolute(publicDir)) {
    throw new TypeError('publicDir must be an absolute path');
  }
  const root = resolve(publicDir);
  const server = http.createServer({ maxHeaderSize: 16 * 1024 }, (request, response) => {
    const handleRequest = async () => {
      checkLocalRequest(request);
      const { pathname, segments } = parsePath(request.url);
      if (pathname === '/api/health') {
        if (request.method !== 'GET') throw new HttpError(405, 'METHOD_NOT_ALLOWED', 'Use GET for this route.', { allow: 'GET' });
        sendJson(response, 200, await bridge.health());
      } else if (pathname === '/api/kbs') {
        if (request.method === 'GET') sendJson(response, 200, await bridge.listKbs());
        else if (request.method === 'POST') sendJson(response, 201, await bridge.createKb(await readJson(request)));
        else throw new HttpError(405, 'METHOD_NOT_ALLOWED', 'Use GET or POST for this route.', { allow: 'GET, POST' });
      } else if (pathname.startsWith('/api/')) {
        const match = /^\/api\/kbs\/([A-Za-z0-9_-]{1,128})\/(import|search)$/u.exec(pathname);
        if (!match) throw new HttpError(404, 'NOT_FOUND', 'The requested API route was not found.');
        if (request.method !== 'POST') throw new HttpError(405, 'METHOD_NOT_ALLOWED', 'Use POST for this route.', { allow: 'POST' });
        const body = await readJson(request);
        const result = match[2] === 'import'
          ? await bridge.importDocuments(match[1], body)
          : await bridge.search(match[1], body);
        sendJson(response, 200, result);
      } else {
        if (request.method !== 'GET' && request.method !== 'HEAD') {
          throw new HttpError(405, 'METHOD_NOT_ALLOWED', 'Use GET or HEAD for static files.', { allow: 'GET, HEAD' });
        }
        await serveStatic(request, response, root, segments);
      }
    };
    handleRequest().catch((error) => sendError(request, response, error));
  });
  server.requestTimeout = 30_000;
  server.headersTimeout = 10_000;
  server.keepAliveTimeout = 5_000;
  server.on('clientError', (_error, socket) => {
    if (!socket.destroyed && socket.writable) socket.end('HTTP/1.1 400 Bad Request\r\nConnection: close\r\nContent-Length: 0\r\n\r\n');
  });
  return server;
}
