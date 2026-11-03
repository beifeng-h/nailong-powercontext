"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import CategoryPicker from "@/components/CategoryPicker";
import { cx } from "@/lib/cn";

interface SearchBarProps {
  defaultValue?: string;
  defaultCategory?: string;
  categories: string[];
  size?: "lg" | "sm";
}

export default function SearchBar({ defaultValue = "", defaultCategory = "", categories, size = "sm" }: SearchBarProps) {
  const router = useRouter();
  const [query, setQuery] = useState(defaultValue);
  const [category, setCategory] = useState(defaultCategory);

  const big = size === "lg";

  return (
    <form
      className={cx("flex flex-col gap-3", big ? "sm:flex-row sm:items-center" : "sm:flex-row sm:items-center")}
      onSubmit={(event) => {
        event.preventDefault();
        const trimmed = query.trim();
        if (!trimmed) return;
        const params = new URLSearchParams({ q: trimmed });
        if (category) params.set("category", category);
        router.push(`/search?${params.toString()}`);
      }}
    >
      <div className="relative flex-1">
        <svg viewBox="0 0 24 24" className="pointer-events-none absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 fill-slate-400">
          <path d="M11 4a7 7 0 105.2 11.9l4.3 4.3 1.4-1.4-4.3-4.3A7 7 0 0011 4zm0 2a5 5 0 110 10 5 5 0 010-10z" />
        </svg>
        <input
          name="q"
          className={cx("input pl-10", big ? "py-3 text-base" : "py-2 text-sm")}
          placeholder={big ? "搜点什么，例如：贝叶斯定理、React 服务端组件…" : "继续搜索…"}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>
      <CategoryPicker options={categories} value={category} onChange={setCategory} />
      <button type="submit" className={cx("btn-primary", big && "px-6 py-3")}>
        混合检索
      </button>
    </form>
  );
}
