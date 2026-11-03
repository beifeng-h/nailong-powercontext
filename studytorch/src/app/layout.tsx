import { loadCategories } from "@/lib/categories";
import { stats } from "@/lib/db/documents";
import Sidebar from "@/components/Sidebar";
import type { CategoryCount } from "@/lib/types";

export const dynamic = "force-dynamic";

interface ShellData {
  categories: CategoryCount[];
  chunks: number;
  files: number;
  error: string | null;
}

async function loadShellData(): Promise<ShellData> {
  try {
    const [categories, counts] = await Promise.all([loadCategories(), stats()]);
    return { categories, chunks: counts.chunks, files: counts.files, error: null };
  } catch (error) {
    return {
      categories: [],
      chunks: 0,
      files: 0,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

export const metadata = {
  title: "StudySeek · 学习资料智能检索库",
  description: "把 PDF / Markdown / TXT 学习资料向量化写入 seekdb，用向量 + 全文混合检索和 AI 问答找回你学过的东西。",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const shell = await loadShellData();

  return (
    <html lang="zh-CN">
      <body>
        <div className="flex min-h-screen flex-col md:flex-row">
          <Sidebar categories={shell.categories} chunks={shell.chunks} files={shell.files} error={shell.error} />
          <main className="flex-1 px-5 py-8 md:px-10 md:py-10">
            <div className="mx-auto w-full max-w-4xl">{children}</div>
          </main>
        </div>
      </body>
    </html>
  );
}
