import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { embedText } from "@/lib/ai/embeddings";
import { generateAnswer } from "@/lib/ai/chat";
import { hybridSearch } from "@/lib/db/hybrid-search";
import { ensureReady } from "@/lib/db/schema";
import { ApiError, toErrorResponse } from "@/lib/errors";
import type { AnswerSource } from "@/lib/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const TOP_K = 5;

export async function POST(request: NextRequest) {
  try {
    const payload = (await request.json().catch(() => ({}))) as { question?: string; category?: string };
    const question = (payload.question ?? "").trim();
    const category = (payload.category ?? "").trim() || undefined;

    if (question.length < 2) throw new ApiError("问题太短了，请至少输入 2 个字。", 400);

    await ensureReady();

    const vector = await embedText(question);
    const { hits, engine, warning } = await hybridSearch({ text: question, vector, size: TOP_K, category });
    const sources: AnswerSource[] = hits.map((hit, index) => ({ ...hit, index: index + 1 }));
    const answer = await generateAnswer(question, sources);

    return NextResponse.json({ question, answer, sources, engine, warning: warning ?? null });
  } catch (error) {
    return toErrorResponse(error);
  }
}
