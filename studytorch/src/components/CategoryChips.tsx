import Link from "next/link";

import { cx } from "@/lib/cn";
import type { CategoryCount } from "@/lib/types";

interface CategoryChipsProps {
  /** 点击后跳转的路径，例如 /search 或 /browse */
  base: string;
  active: string;
  categories: CategoryCount[];
  /** 需要透传的额外查询参数，例如搜索词 */
  extra?: Record<string, string | undefined>;
}

function href(base: string, category: string, extra?: Record<string, string | undefined>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(extra ?? {})) {
    if (value) params.set(key, value);
  }
  if (category) params.set("category", category);
  const query = params.toString();
  return query ? `${base}?${query}` : base;
}

export default function CategoryChips({ base, active, categories, extra }: CategoryChipsProps) {
  const items = [{ category: "", chunkCount: 0 }, ...categories];

  return (
    <div className="flex flex-wrap items-center gap-2">
      {items.map((item) => (
        <Link
          key={item.category || "__all__"}
          href={href(base, item.category, extra)}
          className={cx(
            "chip transition",
            active === item.category
              ? "border-brand-300 bg-brand-50 text-brand-700"
              : "border-slate-200 bg-white text-slate-600 hover:bg-slate-100",
          )}
        >
          {item.category || "全部分类"}
          {item.category && <span className="ml-1 text-slate-400">{item.chunkCount}</span>}
        </Link>
      ))}
    </div>
  );
}
