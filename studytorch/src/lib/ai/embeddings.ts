import { EMBEDDING_BATCH_SIZE, dashscope } from "@/lib/config";
import { ApiError } from "@/lib/errors";

interface EmbeddingResponse {
  data?: { index: number; embedding: number[] }[];
  error?: { message?: string };
  message?: string;
  code?: string;
}

function batch<T>(items: T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
}

async function embedBatch(texts: string[]): Promise<number[][]> {
  const response = await fetch(`${dashscope.baseUrl}/embeddings`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${dashscope.apiKey()}`,
    },
    body: JSON.stringify({
      model: dashscope.embeddingModel,
      input: texts,
      dimensions: dashscope.dimensions,
      encoding_format: "float",
    }),
  });

  const payload = (await response.json().catch(() => ({}))) as EmbeddingResponse;

  if (!response.ok || !payload.data) {
    const reason = payload.error?.message ?? payload.message ?? `HTTP ${response.status}`;
    throw new ApiError(`Embedding 调用失败（${dashscope.embeddingModel}）：${reason}`, 502);
  }

  return [...payload.data]
    .sort((a, b) => a.index - b.index)
    .map((item) => item.embedding);
}

/* ------------------------------------------------------------------ */
/* 本地确定性降级嵌入器：没有 DASHSCOPE_API_KEY 时使用                    */
/* ------------------------------------------------------------------ */

let warnedLocalFallback = false;

function warnLocalFallbackOnce(): void {
  if (warnedLocalFallback) return;
  warnedLocalFallback = true;
  console.warn(
    `[studyseek] DASHSCOPE_API_KEY 未配置：当前使用本地确定性降级嵌入器（归一化分词 + 哈希投影到 ${dashscope.dimensions} 维、L2 归一化），` +
      "而不是 DashScope text-embedding-v3。同一文本始终得到同一向量，但只反映字面/词形重叠，语义能力有限；配置 Key 后会自动恢复云端嵌入。",
  );
}

const CJK_RUN = /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]+/u;
const TOKEN_RUN =
  /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]+|[\p{Letter}\p{Number}_]+/gu;

/**
 * 归一化分词：NFKC + 小写；中文按单字 + 相邻二元组切分（无需词典），
 * 西文/数字按整词切分，较长单词再补 3-gram，缓解词形变化带来的不命中。
 */
export function tokenize(text: string): string[] {
  const normalized = text.normalize("NFKC").toLowerCase();
  const tokens: string[] = [];

  for (const segment of normalized.match(TOKEN_RUN) ?? []) {
    if (CJK_RUN.test(segment)) {
      const chars = Array.from(segment);
      chars.forEach((char, index) => {
        tokens.push(char);
        const next = chars[index + 1];
        if (next) tokens.push(char + next);
      });
    } else {
      tokens.push(segment);
      if (segment.length >= 5) {
        for (let i = 0; i + 3 <= segment.length; i += 1) tokens.push(segment.slice(i, i + 3));
      }
    }
  }

  return tokens;
}

/** FNV-1a 32 位哈希：无随机种子，跨进程稳定。 */
function fnv1a(input: string, seed = 0x811c9dc5): number {
  let hash = seed >>> 0;
  for (let i = 0; i < input.length; i += 1) {
    hash ^= input.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash >>> 0;
}

/**
 * 哈希投影：每个 token 映射到固定维度，用另一个哈希位决定符号（类似 feature hashing），
 * 然后对维度做 log1p 压缩并 L2 归一化。纯函数，结果可复现。
 */
export function localEmbed(text: string): number[] {
  const dimensions = Math.max(1, dashscope.dimensions);
  const vector = new Array<number>(dimensions).fill(0);

  for (const token of tokenize(text)) {
    const index = fnv1a(token) % dimensions;
    const sign = (fnv1a(token, 0x9e3779b9) & 1) === 0 ? 1 : -1;
    const weight = Array.from(token).length > 1 ? 1 : 0.5;
    vector[index] += sign * weight;
  }

  let norm = 0;
  for (let i = 0; i < dimensions; i += 1) {
    const value = vector[i];
    if (value === 0) continue;
    const compressed = Math.sign(value) * Math.log1p(Math.abs(value));
    vector[i] = compressed;
    norm += compressed * compressed;
  }

  if (norm === 0) return vector;

  const scale = 1 / Math.sqrt(norm);
  return vector.map((value) => value * scale);
}

/* ------------------------------------------------------------------ */

/** 统一入口：有 Key 走 DashScope，无 Key 走本地降级嵌入器。 */
export async function embedTexts(texts: string[]): Promise<number[][]> {
  if (texts.length === 0) return [];

  if (!dashscope.apiKeyConfigured()) {
    warnLocalFallbackOnce();
    return texts.map(localEmbed);
  }

  const vectors: number[][] = [];
  for (const group of batch(texts, EMBEDDING_BATCH_SIZE)) {
    vectors.push(...(await embedBatch(group)));
  }
  return vectors;
}

/** 单条文本向量化（兼容原 embedQuery 调用方）。 */
export async function embedText(text: string): Promise<number[]> {
  const [vector] = await embedTexts([text]);
  if (!vector) throw new ApiError("未能生成查询向量。", 502);
  return vector;
}

/** 查询向量化：与 embedText 完全等价，保留旧名称供现有调用方使用。 */
export async function embedQuery(text: string): Promise<number[]> {
  return embedText(text);
}

/** VECTOR(1024) 列写入时使用的是 JSON 数组字符串。 */
export function toVectorLiteral(vector: number[]): string {
  return `[${vector.map((value) => (Number.isFinite(value) ? value : 0)).join(",")}]`;
}
