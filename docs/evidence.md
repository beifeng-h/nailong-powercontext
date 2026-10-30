# seekdb 实跑证据

生成时间：2026-10-30 15:15:00　·　数据库：`5.7.25-OceanBase seekdb-v1.4.0.0`

全部输出由 `scripts/collect_evidence.py` 直接查库生成，可复现。

## 1. 表与索引

| 索引 | 类型 |
| --- | --- |
| `PRIMARY` | BTREE |
| `uk_code` | BTREE |
| `idx_genome` | VECTOR |
| `idx_text` | FULLTEXT |
| `idx_text` | FULLTEXT |
| `idx_text` | FULLTEXT |
| `idx_text` | FULLTEXT |

## 2. 种群概况

- 物种总数：**13**
- 稀有度分布：`{'少见': 4, '常见': 4, '稀有': 3, '传说': 2}`
- 平均世代：0.0　杂交后代：0
- 基因多样性（两两余弦距离均值）：**0.9275**
- 平均最近邻距离：0.8532　独苗（最近邻 > 0.9）：0

## 3. 图鉴记录（creatures 表里的一行）

```json
{
  "id": 13,
  "code": "ZK-0013",
  "name": "霜翼蝶",
  "latin": "Papilio Frigidus",
  "tagline": "开柜门时飞出来的一阵冷气",
  "rarity": "稀有",
  "novelty": 0.896599,
  "seeds": [
    "冰箱",
    "蝴蝶"
  ],
  "axes": {
    "亲和": 51,
    "体型": 40,
    "攻击": 50,
    "智慧": 37,
    "毒性": 51,
    "繁殖": 39,
    "速度": 53,
    "防御": 45
  },
  "traits": {
    "diet": "凝固的牛奶与水汽",
    "rarity": "稀有",
    "habitat": "冷藏室与老式冰柜",
    "behavior": "只在门被打开的瞬间活动，门一关就贴在灯管上装死。",
    "weakness": "断电两小时后翅膀化水",
    "appearance": "翅膀是半透明的霜层，翅脉像冷冻室的隔板，停在食物上会留下一圈白霜。"
  }
}
```

## 4. 亲缘检索（HNSW KNN）

```sql
SELECT id, code, name, COSINE_DISTANCE(genome, :vec) AS dist
FROM creatures WHERE id <> :self
ORDER BY dist APPROXIMATE LIMIT 5;
```

| 距离 | 编号 | 物种 |
| --- | --- | --- |
| 0.8966 | ZK-0003 | 麻辣水兵 |
| 0.9042 | ZK-0005 | 飓轮仓 |
| 0.9247 | ZK-0010 | 绿屏藻 |
| 0.9321 | ZK-0006 | 夜榴 |
| 0.9534 | ZK-0008 | 豆奶蜗 |

## 5. 混合检索：「冷气」

```sql
SELECT *, 0.62 * (1 - dist) + 0.38 * LEAST(IFNULL(text_score, 0), 1) AS score FROM ( SELECT id, code, name, latin, tagline, rarity, generation, novelty, seeds, traits, axes, parents, lore, COSINE_DISTANCE(genome, '[0.0123, -0.0456, ... 512 维 ...]') AS dist, MATCH(name, latin, tagline, lore) AGAINST('冷气') AS text_score FROM creatures ) ranked ORDER BY score DESC LIMIT 6
```

| 综合分 | 向量相似 | 全文得分 | 编号 | 物种 |
| --- | --- | --- | --- | --- |
| 0.4470 | 0.1851 | 0.8743 | ZK-0013 | 霜翼蝶 |
| 0.1188 | 0.1916 | 0.0000 | ZK-0003 | 麻辣水兵 |
| 0.1112 | 0.1794 | 0.0000 | ZK-0005 | 飓轮仓 |
| 0.1006 | 0.1623 | 0.0000 | ZK-0008 | 豆奶蜗 |
| 0.1002 | 0.1617 | 0.0000 | ZK-0001 | 汁弹 |
| 0.0956 | 0.1542 | 0.0000 | ZK-0011 | 搓衣球花 |

> 全文得分不为 0 的那一行，就是 ngram 全文索引真的命中了关键词；向量相似度那一列则来自 HNSW 近邻。两者在同一条 SQL 里加权。

