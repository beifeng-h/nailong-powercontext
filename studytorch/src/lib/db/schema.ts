import type { RowDataPacket } from "mysql2";

import { FULLTEXT_PARSERS, dashscope, seekdb } from "@/lib/config";
import { connectServerLevel, execute, query } from "@/lib/db/pool";

/**
 * seekdb 只在堆表（ORGANIZATION = HEAP）上支持混合搜索。
 * 全文索引默认 `WITH PARSER ik`：默认的 space 分词会把整句中文当成一个词，导致全文那一路检索不命中。
 */
export function createTableSql(dimensions = dashscope.dimensions, parser = seekdb.fulltextParser): string {
  const withParser = parser === "space" ? "" : ` WITH PARSER ${parser}`;

  return `
    CREATE TABLE IF NOT EXISTS ${seekdb.table} (
      id INT PRIMARY KEY AUTO_INCREMENT,
      content VARCHAR(4096),
      file_name VARCHAR(255),
      category VARCHAR(64),
      embedding VECTOR(${dimensions}),
      VECTOR INDEX idx_vec(embedding) WITH (distance=l2, type=hnsw, lib=vsag),
      FULLTEXT INDEX idx_ft(content)${withParser}
    ) ORGANIZATION = HEAP
  `;
}

function assertParserSupported(): void {
  if (!FULLTEXT_PARSERS.includes(seekdb.fulltextParser as (typeof FULLTEXT_PARSERS)[number])) {
    throw new Error(
      `FULLTEXT_PARSER=${seekdb.fulltextParser} 不受支持，可选值：${FULLTEXT_PARSERS.join(" / ")}`,
    );
  }
}

function safeDatabaseName(): string {
  if (!/^[A-Za-z0-9_]+$/.test(seekdb.database)) {
    throw new Error(`DATABASE_NAME 只能包含字母、数字和下划线，当前值：${seekdb.database}`);
  }
  return seekdb.database;
}

async function createDatabase(): Promise<void> {
  const database = safeDatabaseName();
  const serverConnection = await connectServerLevel();
  try {
    await serverConnection.query(
      `CREATE DATABASE IF NOT EXISTS \`${database}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci`,
    );
  } finally {
    await serverConnection.end();
  }
}

let readyPromise: Promise<void> | null = null;

async function initialize(): Promise<void> {
  assertParserSupported();
  await createDatabase();
  await execute(createTableSql());
  console.log(
    `[studyseek] seekdb 就绪：${seekdb.host}:${seekdb.port}/${seekdb.database}（全文分词器 ${seekdb.fulltextParser}）`,
  );
}

/** 幂等：首次调用建库建表，之后复用同一个 Promise；失败时清除缓存以便重试。 */
export function ensureReady(): Promise<void> {
  if (!readyPromise) {
    readyPromise = initialize().catch((error: unknown) => {
      readyPromise = null;
      throw error;
    });
  }
  return readyPromise;
}

/**
 * 删表重建（切换到新的全文分词器时用）。
 * 全文索引的 parser 无法 ALTER，且旧数据是在旧分词下建的索引，所以必须重建后重新导入。
 */
export async function rebuildTable(): Promise<{ droppedRows: number }> {
  assertParserSupported();
  await ensureReady();

  let droppedRows = 0;
  try {
    const rows = await query<RowDataPacket[]>(`SELECT COUNT(*) AS total FROM ${seekdb.table}`);
    droppedRows = Number(rows[0]?.total ?? 0);
  } catch {
    droppedRows = 0;
  }

  await execute(`DROP TABLE IF EXISTS ${seekdb.table}`);
  await execute(createTableSql(dashscope.dimensions, seekdb.fulltextParser));

  return { droppedRows };
}

export interface SchemaInfo {
  connected: boolean;
  tables: string[];
  rowCount: number;
  detail?: string;
}

export async function inspectSchema(): Promise<SchemaInfo> {
  try {
    await ensureReady();
    const tableRows = await query<RowDataPacket[]>("SHOW TABLES");
    const countRows = await query<RowDataPacket[]>(`SELECT COUNT(*) AS total FROM ${seekdb.table}`);
    return {
      connected: true,
      tables: tableRows.map((row) => String(Object.values(row)[0] ?? "")),
      rowCount: Number(countRows[0]?.total ?? 0),
    };
  } catch (error) {
    return {
      connected: false,
      tables: [],
      rowCount: 0,
      detail: error instanceof Error ? error.message : String(error),
    };
  }
}
