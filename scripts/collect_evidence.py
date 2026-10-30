"""跑一遍真实查询，把 seekdb 的输出整理成 docs/evidence.md（可复现的"证据链"）。"""
import json
import sys
from datetime import datetime

sys.path.insert(0, "/workspace/vector_zoo/service")

from zoo import genome as G
from zoo.db import ZooDB, parse_vec

db = ZooDB()
lines: list[str] = []
w = lines.append

w("# seekdb 实跑证据\n")
w(f"生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}　·　数据库：`{db.ping()['version']}`\n")
w("全部输出由 `scripts/collect_evidence.py` 直接查库生成，可复现。\n")

# 1. 索引
w("## 1. 表与索引\n")
w("| 索引 | 类型 |\n| --- | --- |")
for i in db.ping()["indexes"]:
    w(f"| `{i['name']}` | {i['type']} |")

# 2. 种群概况
st = db.stats()
w("\n## 2. 种群概况\n")
w(f"- 物种总数：**{st['total']}**")
w(f"- 稀有度分布：`{st['rarities']}`")
w(f"- 平均世代：{st['avg_generation']}　杂交后代：{st['bred']}")
w(f"- 基因多样性（两两余弦距离均值）：**{st['diversity']}**")
w(f"- 平均最近邻距离：{st['avg_nearest']}　独苗（最近邻 > 0.9）：{st['endangered']}")

# 3. 一条原始记录
recs = db.list_creatures(limit=1)
if recs:
    r = recs[0]
    w("\n## 3. 图鉴记录（creatures 表里的一行）\n")
    w("```json")
    w(json.dumps({k: r[k] for k in ("id", "code", "name", "latin", "tagline", "rarity",
                                    "novelty", "seeds", "axes", "traits")},
                 ensure_ascii=False, indent=2))
    w("```")

# 4. KNN
if recs:
    with db.conn() as c, c.cursor() as cur:
        cur.execute("SELECT genome FROM creatures WHERE id=%s", [recs[0]["id"]])
        genome = parse_vec(cur.fetchone()["genome"])
    kin = db.nearest(genome, k=5, exclude_id=recs[0]["id"])
    w("\n## 4. 亲缘检索（HNSW KNN）\n")
    w("```sql")
    w("SELECT id, code, name, COSINE_DISTANCE(genome, :vec) AS dist")
    w("FROM creatures WHERE id <> :self")
    w("ORDER BY dist APPROXIMATE LIMIT 5;")
    w("```\n")
    w("| 距离 | 编号 | 物种 |\n| --- | --- | --- |")
    for k in kin:
        w(f"| {k['dist']:.4f} | {k['code']} | {k['name']} |")

# 5. 混合检索
q = "冷气"
qvec = G.embed([q])[0]
res = db.hybrid_search(q, qvec, k=6)
disp = res["sql"]
disp = disp.replace("COSINE_DISTANCE(genome, %s)",
                    "COSINE_DISTANCE(genome, '[0.0123, -0.0456, ... 512 维 ...]')")
disp = disp.replace("AGAINST(%s)", f"AGAINST('{q}')").replace("LIMIT %s", "LIMIT 6")
w(f"\n## 5. 混合检索：「{q}」\n")
w("```sql")
w(disp)
w("```\n")
w("| 综合分 | 向量相似 | 全文得分 | 编号 | 物种 |")
w("| --- | --- | --- | --- | --- |")
for x in res["results"]:
    w(f"| {x['score']:.4f} | {1 - x['dist']:.4f} | {x['text_score']:.4f} | {x['code']} | {x['name']} |")

w("\n> 全文得分不为 0 的那一行，就是 ngram 全文索引真的命中了关键词；"
  "向量相似度那一列则来自 HNSW 近邻。两者在同一条 SQL 里加权。\n")

open("/workspace/vector_zoo/docs/evidence.md", "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("\n".join(lines))
