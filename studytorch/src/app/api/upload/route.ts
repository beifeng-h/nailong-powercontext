import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { DEFAULT_CATEGORIES } from "@/lib/config";
import { ApiError, toErrorResponse } from "@/lib/errors";
import { ensureReady } from "@/lib/db/schema";
import { ingestFile, type IngestResult } from "@/lib/ingest";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function normalizeCategory(raw: string | null): string {
  const value = (raw ?? "").trim();
  if (value.length === 0) return DEFAULT_CATEGORIES[0];
  if (value.length > 64) throw new ApiError("分类名称不能超过 64 个字符。", 400);
  return value;
}

export async function POST(request: NextRequest) {
  try {
    const form = await request.formData();
    const category = normalizeCategory(form.get("category") as string | null);
    const files = form.getAll("files").filter((entry): entry is File => entry instanceof File);

    if (files.length === 0) throw new ApiError("没有收到文件，请拖入 PDF / Markdown / TXT 文件。", 400);

    await ensureReady();

    const results: IngestResult[] = [];
    const failures: { fileName: string; reason: string }[] = [];

    for (const file of files) {
      try {
        const bytes = Buffer.from(await file.arrayBuffer());
        results.push(await ingestFile(file.name, bytes, category));
      } catch (error) {
        failures.push({
          fileName: file.name,
          reason: error instanceof Error ? error.message : String(error),
        });
      }
    }

    if (results.length === 0) {
      throw new ApiError(failures[0]?.reason ?? "文件解析失败。", 400);
    }

    return NextResponse.json({
      category,
      results,
      failures,
      totalChunks: results.reduce((sum, item) => sum + item.chunks, 0),
    });
  } catch (error) {
    return toErrorResponse(error);
  }
}
