import { CHUNK_OVERLAP, CHUNK_SIZE } from "@/lib/config";

/** documents.content 是 VARCHAR(4096)，切块后再兜一层长度，防止超长单块写入失败。 */
const HARD_LIMIT = 4000;

function normalize(raw: string): string {
  return raw
    .replace(/\r\n?/g, "\n")
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, " ")
    .replace(/[ \t]+\n/g, "\n")
    .trim();
}

/**
 * 按固定字符数滑窗切块：每块约 size 字，块之间保留 overlap 字，避免语义在边界被切断。
 */
export function chunkText(raw: string, size = CHUNK_SIZE, overlap = CHUNK_OVERLAP): string[] {
  const text = normalize(raw);
  if (text.length === 0) return [];

  const step = Math.max(1, size - overlap);
  const chunks: string[] = [];

  for (let start = 0; start < text.length; start += step) {
    const piece = text.slice(start, Math.min(start + size, text.length)).trim();
    if (piece.length > 0) chunks.push(piece.slice(0, HARD_LIMIT));
    if (start + size >= text.length) break;
  }

  return chunks;
}
