"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import CategoryPicker from "@/components/CategoryPicker";
import { ACCEPTED_EXTENSIONS, DEFAULT_CATEGORIES } from "@/lib/config";
import { cx } from "@/lib/cn";
import type { IngestResult } from "@/lib/ingest";

interface UploadResponse {
  category: string;
  results: IngestResult[];
  failures: { fileName: string; reason: string }[];
  totalChunks: number;
  error?: string;
}

function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default function UploadDropzone({ categories }: { categories: string[] }) {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [category, setCategory] = useState<string>(DEFAULT_CATEGORIES[0]);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [summary, setSummary] = useState<UploadResponse | null>(null);

  const options = Array.from(new Set([...DEFAULT_CATEGORIES, ...categories]));

  const addFiles = (incoming: FileList | null) => {
    if (!incoming) return;
    setFiles((current) => [...current, ...Array.from(incoming)]);
    setMessage(null);
  };

  const submit = async () => {
    if (files.length === 0 || busy) return;
    setBusy(true);
    setMessage(null);
    setSummary(null);

    try {
      const form = new FormData();
      form.set("category", category.trim() || DEFAULT_CATEGORIES[0]);
      files.forEach((file) => form.append("files", file));

      const response = await fetch("/api/upload", { method: "POST", body: form });
      const payload = (await response.json()) as UploadResponse;

      if (!response.ok) {
        setMessage(payload.error ?? `上传失败（HTTP ${response.status}）`);
        return;
      }

      setSummary(payload);
      setFiles([]);
      router.refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "上传失败，请检查服务是否正常运行。");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card p-5">
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          addFiles(event.dataTransfer.files);
        }}
        className={cx(
          "rounded-xl border-2 border-dashed px-6 py-10 text-center transition",
          dragging ? "border-brand-400 bg-brand-50" : "border-slate-300 bg-slate-50",
        )}
      >
        <p className="text-sm font-medium text-slate-700">把 PDF / Markdown / TXT 拖到这里</p>
        <p className="mt-1 text-xs text-slate-500">
          上传后自动解析、按 500 字切块、逐块调用 {`text-embedding-v3`} 生成 1024 维向量写入 seekdb。
        </p>
        <button type="button" className="btn-ghost mt-4" onClick={() => inputRef.current?.click()}>
          选择文件
        </button>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ACCEPTED_EXTENSIONS.join(",")}
          className="hidden"
          onChange={(event) => addFiles(event.target.files)}
        />
      </div>

      {files.length > 0 && (
        <ul className="mt-4 space-y-1">
          {files.map((file, index) => (
            <li key={`${file.name}-${index}`} className="flex items-center justify-between text-sm text-slate-600">
              <span className="truncate">
                {file.name} <span className="text-xs text-slate-400">{humanSize(file.size)}</span>
              </span>
              <button
                type="button"
                className="text-xs text-slate-400 hover:text-red-500"
                onClick={() => setFiles((current) => current.filter((_, i) => i !== index))}
              >
                移除
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <CategoryPicker options={options} value={category} onChange={setCategory} allowCustom placeholder="归入分类" />
        <button type="button" className="btn-primary" disabled={busy || files.length === 0} onClick={submit}>
          {busy ? "解析并向量化中…" : `入库 ${files.length} 个文件`}
        </button>
      </div>

      {message && <p className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{message}</p>}

      {summary && (
        <div className="mt-4 space-y-2 rounded-lg bg-slate-50 px-4 py-3 text-sm">
          <p className="font-medium text-slate-800">
            已写入「{summary.category}」：{summary.results.length} 个文件 · {summary.totalChunks} 个切块
          </p>
          <ul className="space-y-1 text-slate-600">
            {summary.results.map((item) => (
              <li key={item.fileName}>
                {item.fileName}：{item.characters} 字 → {item.chunks} 块
              </li>
            ))}
            {summary.failures.map((item) => (
              <li key={item.fileName} className="text-red-600">
                {item.fileName}：{item.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
