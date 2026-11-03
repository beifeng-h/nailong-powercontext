import { access, readFile, readdir, stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

import { localEmbed, tokenize } from "../src/lib/ai/embeddings";

const EXPECTED_DOCUMENTS = 12;
const EXPECTED_CHUNKS = 26;
const EXPECTED_DIMENSIONS = 1024;
const EXPECTED_CATEGORIES = ["课程资料", "项目文档", "笔记", "论文"];

interface CheckResult {
  name: string;
  ok: boolean;
  detail?: string;
}

const checks: CheckResult[] = [];

function expect(condition: unknown, message: string): void {
  if (!condition) throw new Error(message);
}

async function check(name: string, fn: () => string | void | Promise<string | void>): Promise<void> {
  try {
    const detail = await fn();
    checks.push({ name, ok: true, detail: typeof detail === "string" ? detail : undefined });
  } catch (error) {
    checks.push({ name, ok: false, detail: error instanceof Error ? error.message : String(error) });
  }
}

async function exists(file: string): Promise<boolean> {
  try {
    await access(file);
    return true;
  } catch {
    return false;
  }
}

async function walk(dir: string): Promise<string[]> {
  const entries = await readdir(dir, { withFileTypes: true });
  const files: string[] = [];

  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...(await walk(full)));
    else files.push(full);
  }

  return files;
}

function maxVectorDiff(a: number[], b: number[]): number {
  const length = Math.min(a.length, b.length);
  let diff = Math.abs(a.length - b.length);
  for (let i = 0; i < length; i += 1) diff = Math.max(diff, Math.abs(a[i] - b[i]));
  return diff;
}

function report(): void {
  for (const item of checks) {
    const status = item.ok ? "PASS" : "FAIL";
    console.log(`${status}  ${item.name}${item.detail ? " — " + item.detail : ""}`);
  }

  const passed = checks.filter((item) => item.ok).length;
  const failed = checks.length - passed;
  console.log("");
  console.log(`共 ${checks.length} 项检查：${passed} 通过，${failed} 失败`);
}

async function main(): Promise<void> {
  const siteDir = fileURLToPath(new URL("../site", import.meta.url));
  const requiredAssets = [
    "index.html",
    "assets/css/styles.css",
    "assets/js/data.js",
    "assets/js/embed.js",
    "assets/js/search.js",
    "assets/js/answer.js",
    "assets/js/app.js",
    "assets/vendor/pdfjs/pdf.js",
    "assets/vendor/pdfjs/pdf.worker.js",
    "assets/vendor/pdfjs/LICENSE.txt",
  ];

  await check("产物目录存在 index.html", async () => {
    expect(await exists(path.join(siteDir, "index.html")), "缺少 site/index.html");
    return path.relative(process.cwd(), path.join(siteDir, "index.html"));
  });

  for (const asset of requiredAssets.slice(1)) {
    await check(`静态资源存在：${asset}`, async () => {
      expect(await exists(path.join(siteDir, asset)), `缺少 ${asset}`);
      const info = await stat(path.join(siteDir, asset));
      expect(info.size > 0, `${asset} 为空文件`);
      return `${(info.size / 1024).toFixed(1)} KB`;
    });
  }

  if (!(await exists(path.join(siteDir, "index.html")))) {
    report();
    process.exitCode = 1;
    return;
  }

  const html = await readFile(path.join(siteDir, "index.html"), "utf-8");
  const css = await readFile(path.join(siteDir, "assets/css/styles.css"), "utf-8");
  const appJs = await readFile(path.join(siteDir, "assets/js/app.js"), "utf-8");
  const searchJs = await readFile(path.join(siteDir, "assets/js/search.js"), "utf-8");
  const embedJs = await readFile(path.join(siteDir, "assets/js/embed.js"), "utf-8");

  const allFiles = await walk(siteDir);
  const vendorPrefix = path.join(siteDir, "assets", "vendor") + path.sep;
  const ownTextFiles = allFiles.filter(
    (file) => !file.startsWith(vendorPrefix) && /\.(html|css|js)$/.test(file),
  );
  const ownTexts = new Map<string, string>();
  for (const file of ownTextFiles) ownTexts.set(file, await readFile(file, "utf-8"));

  await check("标题为 StudySeek 学习资料智能检索库", () => {
    expect(html.includes("<title>StudySeek · 学习资料智能检索库</title>"), "title 不匹配");
    return "StudySeek · 学习资料智能检索库";
  });

  await check("包含 meta description 与内联 SVG favicon", () => {
    expect(/<meta\s+name="description"\s+content="[^"]+"/.test(html), "缺少 meta description");
    expect(/rel="icon"/.test(html) && /href="data:image\/svg\+xml/.test(html), "favicon 不是内联 SVG data URI");
    return "description + data:image/svg+xml";
  });

  await check("HTML 不含外部 CDN / 外链资源", () => {
    const externalResource =
      /<(?:script|link|img|iframe|source|video|audio)\b[^>]*(?:src|href)\s*=\s*["'](?:https?:)?\/\//i;
    expect(!externalResource.test(html), "index.html 含 http(s) 外部资源引用");

    const cdnHosts = /(unpkg\.com|jsdelivr\.net|cdnjs\.cloudflare\.com|esm\.sh|skypack\.dev)/i;
    for (const [file, text] of ownTexts) {
      expect(!cdnHosts.test(text), `${path.relative(siteDir, file)} 含 CDN 域名`);
    }

    return `${ownTextFiles.length} 个自有文本文件通过`;
  });

  await check("自有代码不发起网络请求", () => {
    expect(!/\bfetch\s*\(/.test(appJs + searchJs + embedJs), "app/search/embed 中出现 fetch(");
    expect(!/XMLHttpRequest|WebSocket\(/.test(appJs + searchJs + embedJs), "出现网络请求 API");
    return "检索、上传、问答均为本地计算";
  });

  await check("无密钥、令牌或内网地址", () => {
    const patterns = [
      /DASHSCOPE_API_KEY\s*=/i,
      /\bsk-[a-z0-9_-]{8,}/i,
      /BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY/i,
      /\b127\.0\.0\.1\b/,
      /\blocalhost\b/i,
      /\b192\.168\.\d+\.\d+\b/,
      /\b10\.\d+\.\d+\.\d+\b/,
    ];

    for (const [file, text] of ownTexts) {
      for (const pattern of patterns) {
        expect(!pattern.test(text), `${path.relative(siteDir, file)} 命中敏感模式 ${pattern}`);
      }
    }

    return "未发现密钥、令牌、内网 IP 或 localhost";
  });

  await check("无 npm 构建依赖或框架运行时", async () => {
    expect(!(await exists(path.join(siteDir, "package.json"))), "site 下不应有 package.json");
    expect(!(await exists(path.join(siteDir, "node_modules"))), "site 下不应有 node_modules");
    expect(!/\b(react-dom|vue@|next\/dist|node_modules)\b/.test(html + appJs), "出现框架运行时引用");
    return "纯 HTML / CSS / JS";
  });

  await check("包含混合检索实现代码", () => {
    expect(searchJs.includes("BM25_WEIGHT") && searchJs.includes("VECTOR_WEIGHT"), "缺少融合权重常量");
    expect(searchJs.includes("0.6") && searchJs.includes("0.4"), "缺少 0.6 / 0.4 融合");
    expect(searchJs.includes("function bm25Scores"), "缺少 BM25 实现");
    expect(searchJs.includes("cosineSimilarity") && searchJs.includes("knnVectorScores"), "缺少余弦 kNN 实现");
    return "BM25 + cosine kNN + 0.6/0.4 加权融合";
  });

  await check("包含浏览器内切块、嵌入与上传链路", () => {
    expect(embedJs.includes("function localEmbed") && embedJs.includes("DIMENSIONS = 1024"), "缺少 1024 维本地嵌入");
    expect(embedJs.includes("function chunkText"), "缺少切块实现");
    expect(appJs.includes("embed.localEmbed(content)"), "上传后未计算向量");
    expect(appJs.includes("search.createIndex(state.documents)"), "上传后未重建索引");
    expect(
      appJs.includes("assets/vendor/pdfjs/pdf.js") && appJs.includes("pdf.worker.js"),
      "缺少本地 PDF.js 引用",
    );
    return "PDF.js 本地解析 → 500 字切块 → 1024 维向量 → 重建索引";
  });

  await check("具备键盘可达与响应式标记", () => {
    expect((html.match(/role="list"/g) ?? []).length >= 1, "缺少 role=list");
    expect(
      /<div[^>]+id="dropzone"[^>]+role="button"[^>]+tabindex="0"/.test(html),
      "上传区缺少键盘触发标记",
    );
    expect(/aria-label="/.test(html), "缺少 aria-label");
    expect(css.includes('html[data-theme="dark"]'), "缺少深色模式样式");
    expect(css.includes("@media (max-width: 900px)"), "缺少窄屏横向分类条断点");
    return "role=list / role=button+tabindex / aria-label / dark / mobile breakpoint";
  });

  const sandbox = { window: {} as Record<string, unknown>, console };
  vm.createContext(sandbox);
  for (const script of ["data.js", "embed.js", "search.js", "answer.js"]) {
    const code = await readFile(path.join(siteDir, "assets/js", script), "utf-8");
    vm.runInContext(code, sandbox, { filename: script });
  }

  const siteWindow = sandbox.window as {
    STUDYSEEK_DATA: {
      meta: {
        dimensions: number;
        documents: number;
        chunks: number;
        categories: string[];
        vectorWeight: number;
        bm25Weight: number;
      };
      documents: {
        id: string;
        fileName: string;
        category: string;
        source: string;
        chunks: { id: string; chunkIndex: number; chunkCount: number; content: string; embedding: number[] }[];
      }[];
    };
    StudySeekEmbed: {
      DIMENSIONS: number;
      localEmbed: (text: string) => number[];
      tokenize: (text: string) => string[];
      chunkText: (text: string, size?: number, overlap?: number) => string[];
    };
    StudySeekSearch: {
      VECTOR_WEIGHT: number;
      BM25_WEIGHT: number;
      createIndex: (documents: unknown[]) => unknown;
      hybridSearch: (
        index: unknown,
        query: string,
        options?: { size?: number; category?: string },
      ) => {
        id: string;
        fileName: string;
        category: string;
        source: string;
        content: string;
        score: number;
        vectorScore: number;
        bm25Score: number;
        vectorNorm: number;
        bm25Norm: number;
      }[];
      bm25Scores: (index: unknown, query: string) => number[];
      knnVectorScores: (index: unknown, queryVector: number[]) => number[];
      browse: (index: unknown, category: string, size: number) => { score: number | null }[];
    };
    StudySeekAnswer: {
      compose: (
        question: string,
        hits: unknown[],
      ) => { points: { text: string; citation: number }[]; sources: { index: number }[] };
    };
  };

  const data = siteWindow.STUDYSEEK_DATA;
  const siteEmbed = siteWindow.StudySeekEmbed;
  const siteSearch = siteWindow.StudySeekSearch;

  await check("示例资料条数与元数据正确", () => {
    expect(data.documents.length === EXPECTED_DOCUMENTS, `资料数 ${data.documents.length}，期望 ${EXPECTED_DOCUMENTS}`);
    const chunkCount = data.documents.reduce((sum, doc) => sum + doc.chunks.length, 0);
    expect(chunkCount === EXPECTED_CHUNKS, `切块数 ${chunkCount}，期望 ${EXPECTED_CHUNKS}`);
    expect(data.meta.documents === EXPECTED_DOCUMENTS, "meta.documents 不一致");
    expect(data.meta.chunks === EXPECTED_CHUNKS, "meta.chunks 不一致");
    expect(data.meta.dimensions === EXPECTED_DIMENSIONS, "meta.dimensions 不是 1024");
    expect(data.meta.vectorWeight === 0.6 && data.meta.bm25Weight === 0.4, "meta 融合权重不是 0.6/0.4");
    return `${data.documents.length} 篇 / ${chunkCount} 片段 / ${data.meta.dimensions} 维`;
  });

  await check("覆盖 4 个分类且每篇都有多个片段", () => {
    for (const category of EXPECTED_CATEGORIES) {
      expect(data.meta.categories.includes(category), `缺少分类 ${category}`);
    }
    const thin = data.documents.filter((doc) => doc.chunks.length < 2);
    expect(thin.length === 0, `以下资料不足 2 个片段：${thin.map((doc) => doc.fileName).join("、")}`);
    return `分类 ${data.meta.categories.join(" / ")}；每篇 ≥ 2 片段`;
  });

  await check("所有片段向量为 1024 维且已 L2 归一化", () => {
    let maxNormError = 0;
    for (const doc of data.documents) {
      for (const chunk of doc.chunks) {
        expect(chunk.embedding.length === EXPECTED_DIMENSIONS, `${chunk.id} 维度 ${chunk.embedding.length}`);
        expect(chunk.embedding.every((value) => Number.isFinite(value)), `${chunk.id} 含非法数值`);
        const norm = Math.sqrt(chunk.embedding.reduce((sum, value) => sum + value * value, 0));
        maxNormError = Math.max(maxNormError, Math.abs(norm - 1));
      }
    }
    expect(maxNormError < 1e-5, `最大范数误差 ${maxNormError}`);
    return `最大 |‖v‖₂-1| = ${maxNormError.toExponential(2)}`;
  });

  await check("预计算向量与项目 localEmbed() 一致（6 位小数）", () => {
    let maxDiff = 0;
    for (const doc of data.documents) {
      for (const chunk of doc.chunks) {
        maxDiff = Math.max(maxDiff, maxVectorDiff(chunk.embedding, localEmbed(chunk.content)));
      }
    }
    expect(maxDiff < 1e-6, `最大绝对误差 ${maxDiff}`);
    return `最大绝对误差 ${maxDiff.toExponential(2)}（共 ${EXPECTED_CHUNKS} × 1024 个数）`;
  });

  await check("站点 embed.js 与项目本地嵌入器输出一致", () => {
    const texts = [
      data.documents[0].chunks[0].content,
      data.documents[6].chunks[0].content,
      "混合检索 BM25 融合权重 HNSW efSearch",
    ];
    let maxDiff = 0;
    for (const text of texts) {
      maxDiff = Math.max(maxDiff, maxVectorDiff(siteEmbed.localEmbed(text), localEmbed(text)));
      expect(JSON.stringify(siteEmbed.tokenize(text)) === JSON.stringify(tokenize(text)), "分词结果不一致");
    }
    expect(maxDiff < 1e-12, `最大差异 ${maxDiff}`);
    return `3 条文本分词与向量完全一致，最大差异 ${maxDiff}`;
  });

  const index = siteSearch.createIndex(data.documents);

  await check("BM25 与余弦 kNN 两路都真实产生得分", () => {
    const bm25 = siteSearch.bm25Scores(index, "混合检索 融合权重");
    const cosine = siteSearch.knnVectorScores(index, siteEmbed.localEmbed("混合检索 融合权重"));
    expect(bm25.some((score) => score > 0), "BM25 全为 0");
    expect(cosine.some((score) => score > 0), "余弦相似度全为 0");
    return `BM25 命中 ${bm25.filter((score) => score > 0).length} 个片段；kNN 正相似 ${cosine.filter((score) => score > 0).length} 个片段`;
  });

  await check("混合检索按 0.6/0.4 融合并命中项目文档", () => {
    const hits = siteSearch.hybridSearch(index, "混合检索", { size: 5 });
    expect(hits.length > 0, "没有检索结果");
    expect(
      hits.some((hit) => hit.fileName === "StudySeek-混合检索设计说明.md"),
      "top5 未命中《StudySeek-混合检索设计说明》",
    );
    const fusedError = Math.max(
      ...hits.map((hit) => Math.abs(hit.score - (0.6 * hit.vectorNorm + 0.4 * hit.bm25Norm))),
    );
    expect(fusedError < 1e-9, `融合得分误差 ${fusedError}`);
    return `top1 = ${hits[0].fileName}（综合 ${hits[0].score.toFixed(4)}，向量 ${hits[0].vectorScore.toFixed(4)}，BM25 ${hits[0].bm25Score.toFixed(4)}）`;
  });

  await check("分类过滤同时作用于两路召回", () => {
    const hits = siteSearch.hybridSearch(index, "混合检索", { size: 10, category: "项目文档" });
    expect(hits.length > 0, "项目文档分类无结果");
    expect(hits.every((hit) => hit.category === "项目文档"), "过滤后仍混入其他分类");
    return `项目文档分类 ${hits.length} 个命中，全部属于该分类`;
  });

  await check("上传链路：切块 → 向量 → 入内存索引 → 可检索", () => {
    const content =
      "量子退火实验记录：本次实验比较了模拟退火与量子退火的收敛速度。量子退火在低温下表现出不同的能量隧穿行为，实验记录编号 QA-2026-11。";
    const chunks = siteEmbed.chunkText(content, 500, 50);
    expect(chunks.length > 0, "切块为空");

    const doc = {
      id: "upload-test",
      fileName: "量子退火实验记录.md",
      category: "笔记",
      source: "upload",
      chunks: chunks.map((piece, indexOfChunk) => ({
        id: `upload-test-c${indexOfChunk + 1}`,
        chunkIndex: indexOfChunk,
        chunkCount: chunks.length,
        content: piece,
        embedding: siteEmbed.localEmbed(piece),
      })),
    };

    const uploadIndex = siteSearch.createIndex([...data.documents, doc]);
    const hits = siteSearch.hybridSearch(uploadIndex, "量子退火 实验记录", { size: 5 });
    expect(
      hits.some((hit) => hit.source === "upload" && hit.fileName === "量子退火实验记录.md"),
      "上传片段未被检索到",
    );
    return `${chunks.length} 个切块已加入索引，并命中上传文件`;
  });

  await check("AI 问答返回 top5 来源与带编号引用", () => {
    const hits = siteSearch.hybridSearch(index, "混合检索的融合权重是怎么设计的？", { size: 5 });
    const composed = siteWindow.StudySeekAnswer.compose("混合检索的融合权重是怎么设计的？", hits);
    expect(composed.sources.length === 5, `来源数 ${composed.sources.length}`);
    expect(composed.points.length > 0, "没有生成要点");
    expect(
      composed.points.every((point) => point.citation >= 1 && point.citation <= composed.sources.length),
      "引用编号越界",
    );
    return `${composed.points.length} 条要点，引用 ${composed.sources.length} 个片段`;
  });

  await check("空查询回退为浏览列表且不显示得分", () => {
    const hits = siteSearch.browse(index, "", 12);
    expect(hits.length === 12, `浏览列表 ${hits.length} 条`);
    expect(hits.every((hit) => hit.score === null), "浏览模式不应有得分");
    return "12 条浏览结果，得分为空";
  });

  report();
  process.exitCode = checks.some((item) => !item.ok) ? 1 : 0;
}

main().catch((error: unknown) => {
  console.error("校验脚本异常：", error instanceof Error ? error.message : error);
  process.exitCode = 1;
});
