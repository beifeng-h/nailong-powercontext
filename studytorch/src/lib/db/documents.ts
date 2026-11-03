import type { RowDataPacket } from "mysql2";

import { seekdb } from "@/lib/config";
import { toVectorLiteral } from "@/lib/ai/embeddings";
import { execute, query } from "@/lib/db/pool";
import type { CategoryCount, StoredChunk } from "@/lib/types";

export interface ChunkToInsert {
  content: string;
  embedding: number[];
}

function limitClause(limit: number): number {
  const value = Math.trunc(Number(limit));
  if (!Number.isFinite(value) || value <= 0) return 20;
  return Math.min(value, 200);
}

/** 一次写入一个文件的全部切块，返回写入条数。 */
export async function insertChunks(
  fileName: string,
  category: string,
  chunks: ChunkToInsert[],
): Promise<number> {
  if (chunks.length === 0) return 0;

  const placeholders = chunks.map(() => "(?, ?, ?, ?)").join(", ");
  const params = chunks.flatMap((chunk) => [
    chunk.content.slice(0, 4000),
    fileName,
    category,
    toVectorLiteral(chunk.embedding),
  ]);

  const result = await execute(
    `INSERT INTO ${seekdb.table} (content, file_name, category, embedding) VALUES ${placeholders}`,
    params,
  );
  return Number(result.affectedRows ?? chunks.length);
}

export async function listCategories(): Promise<CategoryCount[]> {
  const rows = await query<RowDataPacket[]>(
    `SELECT category, COUNT(*) AS chunk_count, COUNT(DISTINCT file_name) AS file_count
       FROM ${seekdb.table}
      GROUP BY category
      ORDER BY chunk_count DESC`,
  );
  return rows.map((row) => ({
    category: String(row.category ?? ""),
    chunkCount: Number(row.chunk_count ?? 0),
    fileCount: Number(row.file_count ?? 0),
  }));
}

/** 按分类浏览最近写入的切块；category 为空表示不过滤。 */
export async function browseChunks(category: string | undefined, limit: number): Promise<StoredChunk[]> {
  const size = limitClause(limit);
  const where = category ? "WHERE category = ?" : "";
  const sql = `SELECT id, content, file_name, category FROM ${seekdb.table} ${where} ORDER BY id DESC LIMIT ${size}`;
  const params = category ? [category] : undefined;

  const rows = await query<RowDataPacket[]>(sql, params);
  return rows.map((row) => ({
    id: Number(row.id),
    content: String(row.content ?? ""),
    fileName: String(row.file_name ?? ""),
    category: String(row.category ?? ""),
  }));
}

export async function listFileNames(category?: string): Promise<string[]> {
  const where = category ? "WHERE category = ?" : "";
  const sql = `SELECT DISTINCT file_name FROM ${seekdb.table} ${where} ORDER BY file_name ASC LIMIT 200`;
  const params = category ? [category] : undefined;
  const rows = await query<RowDataPacket[]>(sql, params);
  return rows.map((row) => String(row.file_name ?? ""));
}

export async function stats(): Promise<{ chunks: number; files: number; categories: number }> {
  const rows = await query<RowDataPacket[]>(
    `SELECT COUNT(*) AS chunks, COUNT(DISTINCT file_name) AS files, COUNT(DISTINCT category) AS categories FROM ${seekdb.table}`,
  );
  const row = rows[0];
  return {
    chunks: Number(row?.chunks ?? 0),
    files: Number(row?.files ?? 0),
    categories: Number(row?.categories ?? 0),
  };
}
