import Link from "next/link";

import SearchBar from "@/components/SearchBar";
import UploadDropzone from "@/components/UploadDropzone";
import { loadCategories } from "@/lib/categories";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const categories = await loadCategories().catch(() => []);

  return (
    <div className="space-y-8">
      <header className="pt-4">
        <h1 className="text-3xl font-semibold tracking-tight text-slate-900">StudySeek</h1>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          把课程资料、项目文档和笔记丢进来，用向量 + 全文混合检索找回那句你记得「好像在哪里看过」的话。
        </p>
      </header>

      <section className="card p-5">
        <SearchBar categories={categories.map((item) => item.category)} size="lg" />
        <p className="mt-3 text-xs text-slate-500">
          检索会同时走向量近邻（knn）和全文索引（query_string），在 seekdb 内部用 RRF 融合排名。
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">上传资料</h2>
        <UploadDropzone categories={categories.map((item) => item.category)} />
      </section>

      <section className="grid gap-4 sm:grid-cols-3">
        <Link href="/ask" className="card p-5 transition hover:border-brand-300">
          <h3 className="text-sm font-semibold text-slate-900">AI 问答</h3>
          <p className="mt-2 text-xs leading-6 text-slate-600">先检索 top5 片段，再交给 qwen-turbo 组织答案并标注引用。</p>
        </Link>
        <Link href="/browse" className="card p-5 transition hover:border-brand-300">
          <h3 className="text-sm font-semibold text-slate-900">按分类浏览</h3>
          <p className="mt-2 text-xs leading-6 text-slate-600">侧边栏的分类可以直接过滤，看看每个分类里都存了哪些片段。</p>
        </Link>
        <Link href="/api/health" className="card p-5 transition hover:border-brand-300">
          <h3 className="text-sm font-semibold text-slate-900">连接状态</h3>
          <p className="mt-2 text-xs leading-6 text-slate-600">排查 seekdb 连接、建表结果和 DashScope Key 是否配置。</p>
        </Link>
      </section>
    </div>
  );
}
