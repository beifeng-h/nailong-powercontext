/** 从查询里抽出用于高亮的词：整句 + 空格分词 + 连续中文串。 */
export function buildTerms(query: string): string[] {
  const raw = query.trim();
  if (!raw) return [];

  const parts = [
    raw,
    ...raw.split(/[\s,，。、；;:：!?？()（）\[\]{}]+/),
    ...(raw.match(/[\u4e00-\u9fa5]{2,}/g) ?? []),
  ];

  return [...new Set(parts.map((part) => part.trim()).filter((part) => part.length >= 2))].slice(0, 12);
}

function escapeForRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export interface TextSegment {
  text: string;
  matched: boolean;
}

/** 按命中词把文本切成片段，供 <Highlight> 渲染，不使用 innerHTML。 */
export function segmentByTerms(text: string, terms: string[]): TextSegment[] {
  const usable = terms.filter(Boolean).map(escapeForRegExp);
  if (usable.length === 0) return [{ text, matched: false }];

  const pattern = new RegExp(`(${usable.join("|")})`, "gi");
  const segments: TextSegment[] = [];

  // 单个捕获分组时，split 结果的奇数下标就是命中词本身
  text.split(pattern).forEach((chunk, index) => {
    if (chunk.length > 0) segments.push({ text: chunk, matched: index % 2 === 1 });
  });

  return segments;
}

/** 结果卡片只展示窗口片段：优先围绕第一个命中词取上下文。 */
export function excerpt(content: string, terms: string[], radius = 180): string {
  if (content.length <= radius * 2) return content;

  const lower = content.toLowerCase();
  const hitIndex = terms.reduce((best, term) => {
    const index = lower.indexOf(term.toLowerCase());
    return index >= 0 && (best === -1 || index < best) ? index : best;
  }, -1);

  if (hitIndex === -1) return content.slice(0, radius * 2) + "…";

  const start = Math.max(0, hitIndex - Math.floor(radius / 2));
  const end = Math.min(content.length, start + radius * 2);
  return `${start > 0 ? "…" : ""}${content.slice(start, end)}${end < content.length ? "…" : ""}`;
}
