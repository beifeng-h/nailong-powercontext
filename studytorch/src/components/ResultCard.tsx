import Highlight from "@/components/Highlight";
import { excerpt } from "@/lib/highlight";
import type { SearchHit } from "@/lib/types";

function formatScore(value: number | null): string | null {
  if (value === null || !Number.isFinite(value)) return null;
  return value.toFixed(4);
}

export default function ResultCard({ hit, terms, rank }: { hit: SearchHit; terms: string[]; rank: number }) {
  const keyword = formatScore(hit.keywordScore);
  const semantic = formatScore(hit.semanticScore);

  return (
    <article className="card p-5">
      <header className="flex flex-wrap items-center gap-2">
        <span className="chip border-slate-200 bg-slate-100 text-slate-600">#{rank}</span>
        <h3 className="min-w-0 flex-1 truncate text-sm font-semibold text-slate-900">{hit.fileName}</h3>
        <span className="chip border-brand-100 bg-brand-50 text-brand-700">{hit.category}</span>
      </header>

      <p className="mt-3 text-sm leading-6 text-slate-700">
        <Highlight text={excerpt(hit.content, terms)} terms={terms} />
      </p>

      <footer className="mt-4 flex flex-wrap items-center gap-3 text-xs text-slate-500">
        <span>片段 ID {hit.id}</span>
        <span>综合得分 {hit.score.toFixed(4)}</span>
        {keyword !== null && <span>全文 {keyword}</span>}
        {semantic !== null && <span>向量相似度 {semantic}</span>}
      </footer>
    </article>
  );
}
