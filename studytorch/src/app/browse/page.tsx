import CategoryChips from "@/components/CategoryChips";
import { browseChunks, listFileNames } from "@/lib/db/documents";
import { ensureReady } from "@/lib/db/schema";
import { loadCategories } from "@/lib/categories";

export const dynamic = "force-dynamic";

const PAGE_SIZE = 60;

export default async function BrowsePage({ searchParams }: { searchParams: { category?: string } }) {
  const category = (searchParams.category ?? "").trim();
  const categories = await loadCategories().catch(() => []);

  let chunks: Awaited<ReturnType<typeof browseChunks>> = [];
  let fileNames: string[] = [];
  let error: string | null = null;

  try {
    await ensureReady();
    [chunks, fileNames] = await Promise.all([
      browseChunks(category || undefined, PAGE_SIZE),
      listFileNames(category || undefined),
    ]);
  } catch (caught) {
    error = caught instanceof Error ? caught.message : String(caught);
  }

  return (
    <div className="space-y-6">
      <header className="space-y-4">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">全部资料</h1>
        <p className="text-sm text-slate-600">
          {category ? `分类「${category}」` : "所有分类"} · 最近 {PAGE_SIZE} 个切块 · {fileNames.length} 个文件
        </p>
        <CategoryChips base="/browse" active={category} categories={categories} />
      </header>

      {error && <p className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">读取失败：{error}</p>}

      {!error && chunks.length === 0 && (
        <p className="card px-5 py-8 text-center text-sm text-slate-500">
          这个分类还没有内容，去首页上传几份 PDF / Markdown / TXT 吧。
        </p>
      )}

      <ul className="space-y-3">
        {chunks.map((chunk) => (
          <li key={chunk.id} className="card px-5 py-4">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="font-medium text-slate-800">{chunk.fileName}</span>
              <span className="chip border-slate-200 bg-slate-50 text-slate-600">{chunk.category}</span>
              <span className="ml-auto text-xs text-slate-400">片段 #{chunk.id}</span>
            </div>
            <p className="mt-2 line-clamp-4 text-xs leading-6 text-slate-600">{chunk.content}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}
