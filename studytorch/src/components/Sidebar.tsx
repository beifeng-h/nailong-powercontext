"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";

import { cx } from "@/lib/cn";
import type { CategoryCount } from "@/lib/types";

interface SidebarProps {
  categories: CategoryCount[];
  chunks: number;
  files: number;
  error: string | null;
}

const NAV = [
  { href: "/", label: "检索与上传", icon: "M11 4a7 7 0 105.2 11.9l4.3 4.3 1.4-1.4-4.3-4.3A7 7 0 0011 4zm0 2a5 5 0 110 10 5 5 0 010-10z" },
  { href: "/ask", label: "AI 问答", icon: "M12 3a9 9 0 019 9 9 9 0 01-9 9H5l-2 2V12a9 9 0 019-9zm0 2a7 7 0 00-7 7v3.2l.8-.2H12a7 7 0 000-14z" },
  { href: "/browse", label: "全部资料", icon: "M4 5h7v6H4V5zm9 0h7v6h-7V5zM4 13h7v6H4v-6zm9 0h7v6h-7v-6z" },
];

export default function Sidebar({ categories, chunks, files, error }: SidebarProps) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const activeCategory = searchParams.get("category");

  return (
    <aside className="w-full shrink-0 border-b border-slate-200 bg-white px-5 py-6 md:h-screen md:w-64 md:border-b-0 md:border-r">
      <Link href="/" className="flex items-center gap-2">
        <span className="grid h-9 w-9 place-items-center rounded-lg bg-brand-600 text-sm font-bold text-white">S</span>
        <span className="text-lg font-semibold tracking-tight text-slate-900">StudySeek</span>
      </Link>
      <p className="mt-2 text-xs text-slate-500">学习资料智能检索库</p>

      <nav className="mt-6 flex gap-1 md:flex-col">
        {NAV.map((item) => {
          const active = pathname === item.href || (item.href === "/browse" && pathname.startsWith("/browse"));
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cx(
                "flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition",
                active ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100",
              )}
            >
              <svg viewBox="0 0 24 24" className="h-4 w-4 fill-current">
                <path d={item.icon} />
              </svg>
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="mt-8">
        <p className="px-3 text-xs font-semibold uppercase tracking-wide text-slate-400">分类</p>
        <ul className="mt-2 space-y-1">
          {categories.map((item) => {
            const active = pathname === "/browse" && activeCategory === item.category;
            return (
              <li key={item.category}>
                <Link
                  href={`/browse?category=${encodeURIComponent(item.category)}`}
                  className={cx(
                    "flex items-center justify-between rounded-lg px-3 py-2 text-sm transition",
                    active ? "bg-brand-50 font-medium text-brand-700" : "text-slate-600 hover:bg-slate-100",
                  )}
                >
                  <span className="truncate">{item.category}</span>
                  <span className="ml-2 shrink-0 text-xs text-slate-400">{item.chunkCount}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      </div>

      <div className="mt-8 space-y-2 border-t border-slate-100 pt-4 text-xs text-slate-500">
        {error ? (
          <p className="rounded-lg bg-amber-50 px-3 py-2 text-amber-800">
            seekdb 未连接：{error}
            <br />
            请检查 .env.local 与数据库服务，详见 README。
          </p>
        ) : (
          <p className="px-3">
            {files} 个文件 · {chunks} 个切块
          </p>
        )}
        <Link href="/api/health" className="block px-3 text-brand-600 hover:underline">
          查看连接状态
        </Link>
      </div>
    </aside>
  );
}
