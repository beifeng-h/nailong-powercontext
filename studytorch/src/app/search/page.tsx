import Link from "next/link";

import CategoryChips from "@/components/CategoryChips";
import ResultCard from "@/components/ResultCard";
import SearchBar from "@/components/SearchBar";
import { embedText } from "@/lib/ai/embeddings";
import { loadCategories } from "@/lib/categories";
import { hybridSearch } from "@/lib/db/hybrid-search";
import { buildTerms } from "@/lib/highlight";
import type { SearchHit } from "@/lib/types";

export const dynamic = "force-dynamic";

const RESULT_SIZE = 10;

interface SearchPageProps {
  searchParams: { q?: string; category?: string };
}

interface SearchState {
  hits: SearchHit[];
  engine: string;
  warning: string | null;
  error: string | null;
}

async function runSearch(query: string, category: string): Promise<SearchState> {
  try {
    const vector = await embedText(query);
    const result = await hybridSearch({
      text: query,
      vector,
      size: RESULT_SIZE,
      category: category || undefined,
    });
    return { hits: result.hits, engine: result.engine, warning: result.warning ?? null, error: null };
  } catch (error) {
    return {
      hits: [],
      engine: "none",
      warning: null,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

export default async function SearchPage({ searchParams }: SearchPageProps) {
  const query = (searchParams.q ?? "").trim();
  const category = (searchParams.category ?? "").trim();
  const categories = await loadCategories().catch(() => []);
  const terms = buildTerms(query);

  const state = query ? await runSearch(query, category) : null;

  return (
    <div className="space-y-6">
      <header className="space-y-4">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">搜索结果</h1>
        <SearchBar
          categories={categories.map((item) => item.category)}
          defaultValue={query}
          defaultCategory={category}
          size="lg"
        />
        <CategoryChips
          base="/search"
          active={category}
          categories={categories}
          extra={{ q: query }}
        />
      </header>

      {!query && (
        <p className="card px-5 py-8 text-center text-sm text-slate-500">输入关键词开始检索，或在首页直接提问。</p>
      )}

      {state?.error && (
        <p className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
          检索失败：{state.error}
          <span className="mt-1 block text-red-600">
            先确认 <Link className="underline" href="/api/health">/api/health</Link> 里 seekdb 已连接，且
            DASHSCOPE_API_KEY 可用。
          </span>
        </p>
      )}

      {state && !state.error && (
        <section className="space-y-4">
          <div className="flex flex-wrap items-center gap-3 text-sm text-slate-600">
            <span>
              「{query}」命中 {state.hits.length} 个片段
              {category && <span className="text-slate-400"> · 分类：{category}</span>}
            </span>
            <span className="ml-auto text-xs text-slate-400">
              {state.engine === "hybrid_search" ? "DBMS_HYBRID_SEARCH 混合搜索" : "SQL 回退：向量 + 全文 RRF"}
            </span>
          </div>

          {state.warning && (
            <p className="rounded-lg bg-amber-50 px-4 py-2 text-xs text-amber-800">
              混合搜索存储过程调用失败，已自动回退：{state.warning}
            </p>
          )}

          {state.hits.length === 0 ? (
            <div className="card px-5 py-8 text-center text-sm text-slate-500">
              没有匹配的资料。可以换个说法再试，或
              <Link href="/" className="mx-1 text-brand-600 hover:underline">
                上传相关文件
              </Link>
              。
            </div>
          ) : (
            <ul className="space-y-4">
              {state.hits.map((hit, index) => (
                <li key={hit.id}>
                  <ResultCard hit={hit} terms={terms} rank={index + 1} />
                </li>
              ))}
            </ul>
          )}

          <div className="card flex flex-wrap items-center justify-between gap-3 px-5 py-4">
            <p className="text-sm text-slate-600">想直接要一个答案？</p>
            <Link
              href={`/ask?${new URLSearchParams({ ...(query ? { q: query } : {}), ...(category ? { category } : {}) }).toString()}`}
              className="btn-primary"
            >
              就这个问题问 AI
            </Link>
          </div>
        </section>
      )}
    </div>
  );
}
