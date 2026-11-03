import mysql from "mysql2/promise";

import { seekdb } from "@/lib/config";

const holder = globalThis as typeof globalThis & { __studyseekPool?: mysql.Pool };

function baseOptions(): mysql.PoolOptions {
  return {
    host: seekdb.host,
    port: seekdb.port,
    user: seekdb.user,
    password: seekdb.password,
    waitForConnections: true,
    connectionLimit: 8,
    queueLimit: 0,
    charset: "utf8mb4_unicode_ci",
    multipleStatements: false,
  };
}

/** 连接池：单例，避免 dev 模式热重载时反复建池。 */
export function getPool(): mysql.Pool {
  if (!holder.__studyseekPool) {
    holder.__studyseekPool = mysql.createPool({
      ...baseOptions(),
      database: seekdb.database,
    });
  }
  return holder.__studyseekPool;
}

/** 关闭连接池：CLI 脚本执行完后必须调用，否则池里的空闲连接会让进程不退出。 */
export async function closePool(): Promise<void> {
  if (!holder.__studyseekPool) return;
  const pool = holder.__studyseekPool;
  holder.__studyseekPool = undefined;
  await pool.end();
}

/** 未指定 database 的临时连接，用于建库。 */
export function connectServerLevel(): Promise<mysql.Connection> {
  return mysql.createConnection(baseOptions());
}

export async function query<T extends mysql.RowDataPacket[]>(sql: string, params?: unknown[]): Promise<T> {
  const [rows] = await getPool().query<T>(sql, params ?? []);
  return rows;
}

export async function execute(sql: string, params?: unknown[]): Promise<mysql.OkPacket> {
  const [result] = await getPool().execute<mysql.OkPacket>(sql, (params ?? []) as mysql.ExecuteValues);
  return result;
}
