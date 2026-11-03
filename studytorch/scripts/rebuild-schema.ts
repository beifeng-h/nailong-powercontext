import "./load-env";

import { closePool } from "../src/lib/db/pool";

/**
 * 重建 documents 表（全文索引分词器无法 ALTER，只能删表重建）。
 * 用法：
 *   npm run db:rebuild -- --yes
 *   npm run db:rebuild -- --yes --parser=ngram
 * 注意：表里已有的数据会被删掉，重建后需要重新 npm run seed 或重新上传文件。
 */
async function main(): Promise<void> {
  const args = process.argv.slice(2);
  const parserArg = args.find((arg) => arg.startsWith("--parser="));
  if (parserArg) {
    process.env.FULLTEXT_PARSER = parserArg.slice("--parser=".length);
  }

  // 改完环境变量再动态引入，config.ts 是在导入时读取 env 的
  const { FULLTEXT_PARSERS, dashscope, seekdb } = await import("../src/lib/config");
  const { createTableSql, rebuildTable } = await import("../src/lib/db/schema");

  if (!args.includes("--yes")) {
    console.error("这是破坏性操作：会 DROP TABLE documents 并重建。确认请加 --yes");
    process.exit(1);
  }

  console.log(`目标库：${seekdb.host}:${seekdb.port}/${seekdb.database}`);
  console.log(`全文分词器：${seekdb.fulltextParser}（可选：${FULLTEXT_PARSERS.join(" / ")}）`);
  console.log(`向量维度：${dashscope.dimensions}`);
  console.log("\n将执行的 DDL：");
  console.log(createTableSql().replace(/^\s+/gm, "  ").trim());
  console.log("");

  const { droppedRows } = await rebuildTable();
  console.log(`已删除旧表（${droppedRows} 行）并按 ${seekdb.fulltextParser} 分词器重建。`);
  console.log("下一步：npm run seed");
}

main()
  .catch((error: unknown) => {
    console.error("重建失败：", error instanceof Error ? error.message : error);
    process.exitCode = 1;
  })
  .finally(async () => {
    await closePool();
  });
