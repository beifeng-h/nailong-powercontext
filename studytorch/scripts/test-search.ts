import "./load-env";

import { embedText } from "../src/lib/ai/embeddings";
import { seekdb } from "../src/lib/config";
import { fulltextSearch, hybridSearch, vectorSearch } from "../src/lib/db/hybrid-search";
import { closePool } from "../src/lib/db/pool";
import { ensureReady } from "../src/lib/db/schema";
import type { SearchHit } from "../src/lib/types";

/** 默认跑两个查询：一个含关键词，一个纯口语化（考察语义路）。命令行传参可覆盖。 */
const DEFAULT_QUERIES = ["什么是过拟合", "模型记住答案但考试不会"];

function snippet(content: string, width = 46): string {
  const flat = content.replace(/\s+/g, " ").trim();
  return flat.length <= width ? flat : `${flat.slice(0, width)}…`;
}

function fmt(value: number | null): string {
  return value === null ? "  --  " : value.toFixed(4).padStart(7);
}

function printHits(label: string, hits: SearchHit[]): void {
  console.log(`\n  ${label}（${hits.length} 条）`);
  if (hits.length === 0) {
    console.log("    （无命中）");
    return;
  }
  hits.forEach((hit, index) => {
    console.log(
      `    ${String(index + 1).padStart(2)}. id=${String(hit.id).padEnd(4)} ${hit.fileName.padEnd(30)} ${hit.category.padEnd(5)} ` +
        `score=${fmt(hit.score)} kw=${fmt(hit.keywordScore)} sem=${fmt(hit.semanticScore)}`,
    );
    console.log(`        ${snippet(hit.content)}`);
  });
}

function mentionsOverfitting(hits: SearchHit[]): number {
  return hits.filter((hit) => hit.content.includes("过拟合")).length;
}

function intersect(a: SearchHit[], b: SearchHit[]): number[] {
  const ids = new Set(a.map((hit) => hit.id));
  return b.map((hit) => hit.id).filter((id) => ids.has(id));
}

async function runQuery(query: string): Promise<void> {
  console.log("\n" + "=".repeat(78));
  console.log(`查询：${query}`);
  console.log("=".repeat(78));

  const vector = await embedText(query);
  console.log(`查询向量：${vector.length} 维（首 4 维 ${vector.slice(0, 4).map((v) => v.toFixed(4)).join(", ")} …）`);

  const hybrid = await hybridSearch({ text: query, vector, size: 5 });
  const [vectorHits, keywordHits] = await Promise.all([
    vectorSearch(vector, { k: 5 }),
    fulltextSearch(query, { k: 5 }),
  ]);

  console.log(`\n  检索路径：${hybrid.engine === "hybrid_search" ? "DBMS_HYBRID_SEARCH.SEARCH（原生混合搜索）" : "SQL 回退（两路 RRF）"}`);
  if (hybrid.warning) console.log(`  回退原因：${hybrid.warning}`);

  printHits("【A. 混合搜索 DBMS_HYBRID_SEARCH】", hybrid.hits);
  printHits("【B. 纯向量检索 l2_distance APPROXIMATE】", vectorHits);
  printHits("【C. 纯全文检索 MATCH(content) AGAINST】", keywordHits);

  const overlap = intersect(vectorHits, keywordHits);
  console.log("\n  三路对比：");
  console.log(`    混合 ${hybrid.hits.length} 条 · 纯向量 ${vectorHits.length} 条 · 纯全文 ${keywordHits.length} 条 · 向量与全文交集 ${overlap.length} 条`);
  console.log(`    含「过拟合」字样：混合 ${mentionsOverfitting(hybrid.hits)} 条 / 纯向量 ${mentionsOverfitting(vectorHits)} 条 / 纯全文 ${mentionsOverfitting(keywordHits)} 条`);

  if (keywordHits.length === 0) {
    console.log("    提示：全文路 0 命中。若查询里确实有资料中出现过的词，说明全文索引分词器还没生效（跑 npm run db:rebuild -- --yes 切成 ik）。");
  }
}

async function main(): Promise<void> {
  const queries = process.argv.slice(2).filter((arg) => !arg.startsWith("--"));
  const list = queries.length > 0 ? queries : DEFAULT_QUERIES;

  await ensureReady();
  console.log(`seekdb：${seekdb.host}:${seekdb.port}/${seekdb.database}.${seekdb.table}`);

  for (const query of list) {
    await runQuery(query);
  }

  console.log("\n" + "=".repeat(78));
  console.log("验证判读：");
  console.log("  1) 三个查询里 C 段（全文）有命中 => MATCH/AGAINST 在 ik 分词下生效");
  console.log("  2) 口语化查询下 C 段可能 0 命中，但 B 段（向量）仍召回「过拟合」笔记 => 语义检索生效");
  console.log("  3) A 段（混合）排名里同时受益于两路，且 _keyword_score / _semantic_score 有非空值 => RRF 融合正常");
}

main()
  .catch((error: unknown) => {
    console.error("检索测试失败：", error instanceof Error ? error.message : error);
    process.exitCode = 1;
  })
  .finally(async () => {
    await closePool();
  });
