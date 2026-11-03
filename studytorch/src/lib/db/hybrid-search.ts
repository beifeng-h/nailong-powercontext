import type { RowDataPacket } from "mysql2";

import { seekdb } from "@/lib/config";
import { getPool, query } from "@/lib/db/pool";
import { ensureReady } from "@/lib/db/schema";
import { toVectorLiteral } from "@/lib/ai/embeddings";
import type { SearchHit } from "@/lib/types";

export interface HybridSearchOptions {
  /** 全文检索用的原始查询串 */
  text: string;
  /** 查询文本的向量 */
  vector: number[];
  /** 最终返回条数 */
  size?: number;
  /** 向量召回候选数 */
  knnK?: number;
  /** 按分类过滤 */
  category?: string;
}

export interface RecallOptions {
  k?: number;
  category?: string;
}

export type SearchEngine = "hybrid_search" | "sql_fallback";

export interface HybridSearchResult {
  hits: SearchHit[];
  engine: SearchEngine;
  warning?: string;
}

function clamp(value: number, min: number, max: number): number {
  const parsed = Math.trunc(Number(value));
  if (!Number.isFinite(parsed)) return min;
  return Math.min(Math.max(parsed, min), max);
}

/** query_string 语法里 ^ 是词权重、引号是短语，用户输入直接透传会破坏解析，这里剥掉控制字符和权重符号。 */
export function sanitizeQueryText(text: string): string {
  return text
    .replace(/[“”"'\\^]/g, " ")
    .replace(/[\u0000-\u001f]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 200);
}

/**
 * seekdb 混合搜索 DSL：全文（query_string）与向量（knn）同时发起，RRF 融合排名。
 * - query_string 的字段必须都有 FULLTEXT 索引，本表只有 content 建了索引，因此 file_name 不能出现在这里。
 * - `_score` 由内核自动返回，放进 `_source` 会报 Unknown column；`_keyword_score` / `_semantic_score` 可以显式取。
 * - 标量过滤（category）必须放在 bool.filter 或 knn.filter，放进 must/should 会被内核拒绝。
 */
export function buildSearchBody(options: HybridSearchOptions): Record<string, unknown> {
  const size = clamp(options.size ?? 10, 1, 50);
  const knnK = clamp(options.knnK ?? size * 3, size, 100);
  const queryText = sanitizeQueryText(options.text);

  const fulltextClause = {
    query_string: {
      fields: ["content^1"],
      query: queryText,
      default_operator: "OR",
    },
  };

  const knn: Record<string, unknown> = {
    field: "embedding",
    k: knnK,
    query_vector: options.vector,
  };

  const body: Record<string, unknown> = {
    query: fulltextClause,
    knn,
    rank: { rrf: { rank_window_size: Math.max(knnK, size), rank_constant: 60 } },
    size,
    _source: ["id", "content", "file_name", "category", "_keyword_score", "_semantic_score"],
  };

  if (options.category) {
    body.query = { bool: { must: [fulltextClause], filter: [{ term: { category: options.category } }] } };
    knn.filter = [{ term: { category: options.category } }];
  }

  return body;
}

function toChunk(row: Record<string, unknown>): { id: number; content: string; fileName: string; category: string } {
  return {
    id: Number(row.id ?? 0),
    content: String(row.content ?? ""),
    fileName: String(row.file_name ?? ""),
    category: String(row.category ?? ""),
  };
}

function mapHit(row: RowDataPacket | Record<string, unknown>): SearchHit {
  const numberOrNull = (value: unknown): number | null =>
    value === undefined || value === null || !Number.isFinite(Number(value)) ? null : Number(value);

  return {
    ...toChunk(row),
    score: Number(row._score ?? row.score ?? 0),
    keywordScore: numberOrNull(row._keyword_score ?? row.kw_score),
    semanticScore: numberOrNull(row._semantic_score ?? row.semantic_score),
  };
}

/** 首选路径：SELECT DBMS_HYBRID_SEARCH.SEARCH(表名, JSON 参数)，返回 JSON 数组。 */
async function runNativeSearch(body: Record<string, unknown>): Promise<SearchHit[]> {
  const connection = await getPool().getConnection();
  try {
    await connection.query("SET @search_parm = ?", [JSON.stringify(body)]);
    const [rows] = await connection.query<RowDataPacket[]>(
      `SELECT DBMS_HYBRID_SEARCH.SEARCH('${seekdb.table}', @search_parm) AS result`,
    );
    const raw = rows[0]?.result;
    const parsed: unknown = typeof raw === "string" ? JSON.parse(raw) : raw;
    const hits: Record<string, unknown>[] = Array.isArray(parsed) ? parsed : [];
    return hits.map(mapHit);
  } finally {
    connection.release();
  }
}

/** 纯向量召回：l2_distance + APPROXIMATE，语义得分归一化成 1/(1+dist)。 */
export async function vectorSearch(vector: number[], options: RecallOptions = {}): Promise<SearchHit[]> {
  await ensureReady();
  const k = clamp(options.k ?? 10, 1, 100);
  const where = options.category ? "WHERE category = ?" : "";
  const params = options.category ? [toVectorLiteral(vector), options.category] : [toVectorLiteral(vector)];

  const rows = await query<RowDataPacket[]>(
    `SELECT id, content, file_name, category, l2_distance(embedding, ?) AS dist
       FROM ${seekdb.table}
       ${where}
      ORDER BY dist APPROXIMATE LIMIT ${k}`,
    params,
  );

  return rows.map((row) => {
    const semantic = 1 / (1 + Number(row.dist ?? 0));
    return { ...toChunk(row), score: semantic, keywordScore: null, semanticScore: semantic };
  });
}

/** 纯全文召回：MATCH(content) AGAINST，BM25 得分。 */
export async function fulltextSearch(text: string, options: RecallOptions = {}): Promise<SearchHit[]> {
  await ensureReady();
  const queryText = sanitizeQueryText(text);
  if (queryText.length === 0) return [];

  const k = clamp(options.k ?? 10, 1, 100);
  const match = "MATCH(content) AGAINST(?)";
  const where = options.category ? `WHERE ${match} AND category = ?` : `WHERE ${match}`;
  const params = options.category ? [queryText, queryText, options.category] : [queryText, queryText];

  const rows = await query<RowDataPacket[]>(
    `SELECT id, content, file_name, category, ${match} AS kw_score
       FROM ${seekdb.table}
       ${where}
      ORDER BY kw_score DESC LIMIT ${k}`,
    params,
  );

  return rows.map((row) => {
    const keyword = Number(row.kw_score ?? 0);
    return { ...toChunk(row), score: keyword, keywordScore: keyword, semanticScore: null };
  });
}

/** SQL 回退：两路各自召回后在应用层做 RRF 融合。 */
async function runFallbackSearch(options: HybridSearchOptions): Promise<SearchHit[]> {
  const size = clamp(options.size ?? 10, 1, 50);
  const candidateK = clamp(options.knnK ?? size * 3, size, 100);
  const recall: RecallOptions = { k: candidateK, category: options.category };

  const [keywordHits, vectorHits] = await Promise.all([
    fulltextSearch(options.text, recall),
    vectorSearch(options.vector, recall),
  ]);

  const fused = new Map<number, { hit: SearchHit; rrf: number }>();
  const absorb = (hits: SearchHit[]) => {
    hits.forEach((hit, rank) => {
      const entry = fused.get(hit.id) ?? { hit, rrf: 0 };
      entry.rrf += 1 / (60 + rank + 1);
      fused.set(hit.id, entry);
    });
  };
  absorb(keywordHits);
  absorb(vectorHits);

  return [...fused.values()]
    .sort((a, b) => b.rrf - a.rrf)
    .slice(0, size)
    .map(({ hit, rrf }) => ({ ...hit, score: rrf }));
}

export async function hybridSearch(options: HybridSearchOptions): Promise<HybridSearchResult> {
  await ensureReady();
  const body = buildSearchBody(options);

  try {
    const hits = await runNativeSearch(body);
    return { hits, engine: "hybrid_search" };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.warn("[studyseek] DBMS_HYBRID_SEARCH.SEARCH 不可用，回退到 SQL 混合检索：", message);
    return {
      hits: await runFallbackSearch(options),
      engine: "sql_fallback",
      warning: message,
    };
  }
}
