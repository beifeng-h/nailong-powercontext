"use client";

import { useState } from "react";

import CategoryPicker from "@/components/CategoryPicker";
import Highlight from "@/components/Highlight";
import { buildTerms, excerpt } from "@/lib/highlight";
import type { AnswerSource } from "@/lib/types";

interface AskResponse {
  answer?: string;
  sources?: AnswerSource[];
  engine?: string;
  warning?: string | null;
  error?: string;
}

export default function AskForm({ categories, initialQuestion = "" }: { categories: string[]; initialQuestion?: string }) {
  const [question, setQuestion] = useState(initialQuestion);
  const [category, setCategory] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [answer, setAnswer] = useState<string | null>(null);
  const [sources, setSources] = useState<AnswerSource[]>([]);
  const [engine, setEngine] = useState<string | null>(null);
  const terms = buildTerms(question);

  const ask = async () => {
    const trimmed = question.trim();
    if (trimmed.length < 2 || busy) return;

    setBusy(true);
    setError(null);
    setAnswer(null);
    setSources([]);

    try {
      const response = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: trimmed, category }),
      });
      const payload = (await response.json()) as AskResponse;

      if (!response.ok) {
        setError(payload.error ?? `请求失败（HTTP ${response.status}）`);
        return;
      }
      setAnswer(payload.answer ?? "");
      setSources(payload.sources ?? []);
      setEngine(payload.engine ?? null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "请求失败。");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      <section className="card p-5">
        <label htmlFor="ask-question" className="text-sm font-medium text-slate-700">
          你的问题
        </label>
        <textarea
          id="ask-question"
          className="input mt-2 h-28 resize-y leading-6"
          placeholder="例如：课程资料里是怎么解释梯度下降的？"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
        />
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          <CategoryPicker options={categories} value={category} onChange={setCategory} />
          <div className="flex items-center gap-2">
            <button type="button" className="btn-ghost" onClick={() => setQuestion("")} disabled={busy || !question}>
              清空
            </button>
            <button type="button" className="btn-primary" onClick={ask} disabled={busy || question.trim().length < 2}>
              {busy ? "检索并生成中…" : "提问"}
            </button>
          </div>
        </div>
        <p className="mt-2 text-xs text-slate-500">流程：混合检索 top5 片段 → 拼进 Prompt → qwen-turbo 生成 → 列出引用来源。</p>
      </section>

      {error && <p className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p>}

      {busy && <p className="animate-pulse text-sm text-slate-500">正在读取你的资料并生成回答…</p>}

      {answer !== null && (
        <section className="card p-5">
          <h2 className="text-sm font-semibold text-slate-900">回答</h2>
          <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-slate-700">{answer}</p>

          <div className="mt-5 border-t border-slate-100 pt-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">引用来源</p>
            {sources.length === 0 ? (
              <p className="mt-2 text-sm text-slate-500">没有检索到可引用的片段。</p>
            ) : (
              <ol className="mt-3 space-y-3">
                {sources.map((source) => (
                  <li key={source.id} className="rounded-lg bg-slate-50 px-4 py-3">
                    <p className="flex flex-wrap items-center gap-2 text-sm">
                      <span className="chip border-brand-100 bg-white text-brand-700">[{source.index}]</span>
                      <span className="font-medium text-slate-800">{source.fileName}</span>
                      <span className="text-xs text-slate-500">{source.category}</span>
                      <span className="ml-auto text-xs text-slate-400">得分 {source.score.toFixed(4)}</span>
                    </p>
                    <p className="mt-2 text-xs leading-6 text-slate-600">
                      <Highlight text={excerpt(source.content, terms)} terms={terms} />
                    </p>
                  </li>
                ))}
              </ol>
            )}
            {engine && <p className="mt-3 text-xs text-slate-400">检索路径：{engine === "hybrid_search" ? "DBMS_HYBRID_SEARCH 混合搜索" : "SQL 回退（向量 + 全文 RRF）"}</p>}
          </div>
        </section>
      )}
    </div>
  );
}
