import { DEFAULT_CATEGORIES } from "@/lib/config";
import { listCategories } from "@/lib/db/documents";
import type { CategoryCount } from "@/lib/types";

/** 侧边栏分类：预置分类始终出现（即使还没有数据），再合并库里实际存在的分类。 */
export async function loadCategories(): Promise<CategoryCount[]> {
  const fromDb = await listCategories();
  const merged = new Map<string, CategoryCount>();

  for (const name of DEFAULT_CATEGORIES) {
    merged.set(name, { category: name, chunkCount: 0, fileCount: 0 });
  }
  for (const item of fromDb) {
    if (item.category) merged.set(item.category, item);
  }

  return [...merged.values()].sort((a, b) => b.chunkCount - a.chunkCount || a.category.localeCompare(b.category));
}
