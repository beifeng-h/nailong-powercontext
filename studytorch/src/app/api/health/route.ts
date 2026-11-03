import { NextResponse } from "next/server";

import { dashscope, seekdb } from "@/lib/config";
import { inspectSchema } from "@/lib/db/schema";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** 本地排障入口：确认 seekdb 连接、建表结果和 API Key 是否就绪。 */
export async function GET() {
  const schema = await inspectSchema();

  return NextResponse.json({
    seekdb: {
      host: seekdb.host,
      port: seekdb.port,
      database: seekdb.database,
      connected: schema.connected,
      tables: schema.tables,
      chunks: schema.rowCount,
      detail: schema.detail ?? null,
    },
    dashscope: {
      apiKeyConfigured: Boolean(process.env.DASHSCOPE_API_KEY),
      embeddingModel: dashscope.embeddingModel,
      dimensions: dashscope.dimensions,
      chatModel: dashscope.chatModel,
    },
  });
}
