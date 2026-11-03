export async function register() {
  if (process.env.NEXT_RUNTIME !== "nodejs") return;

  try {
    const { ensureReady } = await import("@/lib/db/schema");
    await ensureReady();
  } catch (error) {
    // 启动时 seekdb 可能还没起来：这里只记录，后续请求会重试建表。
    console.error("[studyseek] 启动时初始化 seekdb 失败：", error instanceof Error ? error.message : error);
  }
}
