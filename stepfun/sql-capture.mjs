import { createHash } from 'node:crypto';

const DATABASE = 'stepfun_kb_demo';
const hash = sql => createHash('sha256').update(sql).digest('hex');
const normalize = sql => {
  const text = String(sql).trim();
  return ((text.startsWith("'") && text.endsWith("'")) || (text.startsWith('"') && text.endsWith('"')))
    ? text.slice(1, -1) : text;
};

/**
 * Optional diagnostic hook for a dedicated StepFun Node process. Call before
 * createBridge(), then restore after closing the bridge. It uses mysql2's public
 * createConnection/query functions, not seekdb private fields or SDK patches.
 * It never records connection configuration, bound values, result rows, or error
 * messages. includeGeneratedSql is opt-in because SQL contains query text/vector.
 * Importing this module alone does not load mysql2 or contact a database.
 */
export async function installSqlCapture({ onEvent, includeGeneratedSql = false, mysql: injectedMysql } = {}) {
  if (typeof onEvent !== 'function') throw new TypeError('onEvent must be a function');
  const imported = injectedMysql ?? await import('mysql2/promise');
  const mysql = imported.default ?? imported;
  if (typeof mysql.createConnection !== 'function') throw new TypeError('mysql2 public createConnection is unavailable');
  const originalCreateConnection = mysql.createConnection;
  const wrappedConnections = new Map();
  let connectionNumber = 0;
  let eventNumber = 0;
  const emit = event => { try { onEvent({ eventNumber: ++eventNumber, ...event }); } catch {} };
  const tracedCreateConnection = async function (...args) {
    const conn = await Reflect.apply(originalCreateConnection, this, args);
    // Do not trace admin or unrelated database connections in the same process.
    if (!args[0] || typeof args[0] !== 'object' || args[0].database !== DATABASE) return conn;
    const id = ++connectionNumber;
    const generated = new Set();
    const originalQuery = conn.query;
    const wrappedQuery = async function (...queryArgs) {
      const sql = typeof queryArgs[0] === 'string' ? queryArgs[0] : queryArgs[0]?.sql;
      const normalized = typeof sql === 'string' ? normalize(sql) : '';
      const isGetSql = /\bDBMS_HYBRID_SEARCH\.GET_SQL\s*\(/i.test(normalized);
      const isNativeSearch = /\bDBMS_HYBRID_SEARCH\.SEARCH\s*\(/i.test(normalized);
      const statementSha256 = hash(normalized);
      const isGenerated = generated.has(statementSha256);
      const start = performance.now();
      try {
        const result = await Reflect.apply(originalQuery, this, queryArgs);
        if (isNativeSearch) {
          const parameters = queryArgs[1];
          emit({ kind: 'hybrid-native-search', connectionNumber: id, statementSha256,
            parameterSha256: Array.isArray(parameters) ? hash(JSON.stringify(parameters)) : null,
            elapsedMs: performance.now() - start, ok: true });
        } else if (isGetSql) {
          const rows = result?.[0];
          const generatedText = rows?.[0]?.query_sql;
          if (typeof generatedText === 'string' && generatedText.trim()) {
            const query = normalize(generatedText);
            const generatedSqlSha256 = hash(query);
            generated.add(generatedSqlSha256);
            emit({ kind: 'hybrid-get-sql', connectionNumber: id, statementSha256,
              generatedSqlSha256, ...(includeGeneratedSql ? { generatedSql: query } : {}),
              elapsedMs: performance.now() - start, ok: true });
          } else {
            emit({ kind: 'hybrid-get-sql', connectionNumber: id, statementSha256,
              generatedSqlPresent: false, elapsedMs: performance.now() - start, ok: true });
          }
        } else if (isGenerated) {
          emit({ kind: 'hybrid-execute-generated', connectionNumber: id,
            statementSha256, elapsedMs: performance.now() - start, ok: true });
        }
        return result;
      } catch (error) {
        if (isGetSql || isGenerated || isNativeSearch) {
          const code = typeof error?.code === 'string' && /^[A-Z0-9_]+$/.test(error.code) ? error.code : 'DATABASE_ERROR';
          emit({ kind: isGetSql ? 'hybrid-get-sql' : isNativeSearch ? 'hybrid-native-search' : 'hybrid-execute-generated', connectionNumber: id,
            statementSha256, elapsedMs: performance.now() - start, ok: false, code });
        }
        throw error;
      }
    };
    conn.query = wrappedQuery;
    wrappedConnections.set(conn, { originalQuery, wrappedQuery });
    return conn;
  };
  mysql.createConnection = tracedCreateConnection;
  return function restore() {
    if (mysql.createConnection === tracedCreateConnection) mysql.createConnection = originalCreateConnection;
    for (const [conn, { originalQuery, wrappedQuery }] of wrappedConnections) {
      if (conn.query === wrappedQuery) conn.query = originalQuery;
    }
    wrappedConnections.clear();
  };
}
