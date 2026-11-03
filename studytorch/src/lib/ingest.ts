import { embedTexts } from "@/lib/ai/embeddings";
import { insertChunks } from "@/lib/db/documents";
import { chunkText } from "@/lib/documents/chunk";
import { extractText, validateUpload } from "@/lib/documents/extract";

export interface IngestResult {
  fileName: string;
  category: string;
  characters: number;
  chunks: number;
  inserted: number;
}

/** 解析 -> 切块 -> 向量化 -> 写入 seekdb。 */
export async function ingestFile(fileName: string, bytes: Buffer, category: string): Promise<IngestResult> {
  validateUpload(fileName, bytes);

  const text = await extractText({ fileName, bytes });
  const chunks = chunkText(text);
  if (chunks.length === 0) {
    return { fileName, category, characters: text.trim().length, chunks: 0, inserted: 0 };
  }

  const vectors = await embedTexts(chunks);
  const inserted = await insertChunks(fileName, category, chunks.map((content, i) => ({ content, embedding: vectors[i] })));

  return { fileName, category, characters: text.trim().length, chunks: chunks.length, inserted };
}
