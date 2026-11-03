import AskForm from "@/components/AskForm";
import { loadCategories } from "@/lib/categories";

export const dynamic = "force-dynamic";

export default async function AskPage({ searchParams }: { searchParams: { q?: string } }) {
  const categories = await loadCategories().catch(() => []);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">AI 问答</h1>
        <p className="mt-2 text-sm text-slate-600">只根据你上传的资料回答，并在答案下方列出引用片段。</p>
      </header>
      <AskForm categories={categories.map((item) => item.category)} initialQuestion={(searchParams.q ?? "").trim()} />
    </div>
  );
}
