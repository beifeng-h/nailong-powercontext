# 🧬 向量动物园 · Vector Zoo

> **Just for Fun**：说出两个八竿子打不着的词，让它们在向量空间里交配，生出一只从未存在过的物种，写进 seekdb 的图鉴。

`Dify`（理解人话 + 写图鉴） · `OceanBase seekdb`（基因组 / 亲缘 / 检索 / 统计） · `Qwen2.5`（本地或任意 OpenAI 兼容端点）

---

## 它长什么样

输入 `冰箱 × 蝴蝶`，十几秒后拿到一张图鉴：

```text
ZK-0013 · 霜翼蝶                            [稀有]
Papilio Frigidus
「开柜门时飞出来的一阵冷气。」

母本      冰箱 × 蝴蝶
基因指纹   G-23863F0B81
基因轴    攻击 50 · 防御 45 · 速度 53 · 体型 40 · 智慧 37 · 毒性 51 · 繁殖 39 · 亲和 51
亲缘      0.897 → ZK-0003 麻辣水兵
          0.904 → ZK-0005 飓轮仓
          0.925 → ZK-0010 绿屏藻

霜翼蝶是冰箱与蝴蝶的私生子，靠开柜门的气流完成迁徙。它最喜欢在剩菜上方盘旋，
把冷气均匀地铺在没盖保鲜膜的碗口。有人把它当作食物变质的征兆，其实它只是来乘凉的。
```

页面有四个部分：**合成台**（两个词 + 比例 + 突变率）、**图鉴**、**检索**、**生态**。
顶部三个数字（物种数、稀有度分布、基因多样性）是实时从 seekdb 查出来的。

## 三个"好玩"的点

1. **基因是真的**：基因组 = 两个词向量的加权混合 + 由 `sha256(a|b|mutation)` 播种的可复现突变；同一个组合永远得到同一只物种，所以能用 KNN 判重。
2. **稀有度是算出来的**：与全园最近邻的距离 → 全园分位 → 传说 / 稀有 / 少见 / 常见。新物种入库会挤动别人的稀有度。
3. **杂交会变异**：两只已存在的物种各取一半基因 + 更高突变率，越跨谱系越稀有。

## 为什么它"真的"用了 seekdb

不是把 PDF 塞进知识库，而是让数据库承担玩法本身：

| 玩法 | 用到的 seekdb 能力 | 具体实现 |
| --- | --- | --- |
| 基因组 | `VECTOR(512)` 列 | 两个母本词向量的加权混合 + 可复现突变 |
| 亲缘 / 亲戚 | HNSW 向量索引 + `COSINE_DISTANCE` | `ORDER BY dist APPROXIMATE LIMIT 4` |
| 稀有度 | KNN 结果 + 分位统计 | 与全园最近距离 → 传说/稀有/少见/常见 |
| 重复物种检测 | KNN 距离阈值 | 距离 < 0.03 判定"这个组合已经诞生过" |
| 图鉴检索 | 中文 ngram 全文索引 | `MATCH(name, latin, tagline, lore) AGAINST(...)` |
| 筛选 | JSON 列 | `traits->>'$.habitat'` / `rarity` |
| 混合排序 | 一条 SQL 里算两种分数 | `0.62·向量 + 0.38·全文` |
| 生态仪表盘 | 聚合查询 | 分布、平均世代、基因多样性 |

**一条 SQL 同时做向量 + 全文 + 结构化过滤**，这是选 seekdb 而不是"向量库 + ES + MySQL 三件套"的全部理由。实跑输出见 [docs/evidence.md](docs/evidence.md)（脚本自动生成，可复现）。

```sql
SELECT *, 0.62 * (1 - dist) + 0.38 * LEAST(IFNULL(text_score, 0), 1) AS score
FROM (
  SELECT id, code, name, latin, tagline, rarity, traits, lore,
         COSINE_DISTANCE(genome, :vec) AS dist,
         MATCH(name, latin, tagline, lore) AGAINST(:q) AS text_score
  FROM creatures
  WHERE traits->>'$.habitat' = :habitat
) ranked
ORDER BY score DESC
LIMIT 8;
```

## Dify 在里面干什么

[dify/vector-zoo.dsl.yml](dify/vector-zoo.dsl.yml) 是一个 9 节点的 Chatflow，导入即用：

```text
① 对话入口
  → ② 读题（LLM：从人话里挑两个母本 + 比例）
  → ③ 解析意图（Code：JSON 兜底）
  → ④ 造基因组 + 亲缘检索（HTTP → seekdb：embedding 混合 + HNSW）
  → ⑤ 撰写图鉴（LLM：拿基因轴和亲戚写博物志）
  → ⑥ 打包 token + 图鉴（Code）
  → ⑦ 落库（HTTP → seekdb：向量 + JSON + 全文一次写入）
  → ⑧ 渲染卡片（Code）
  → ⑨ 图鉴出炉（Answer）
```

Dify 负责它最擅长的两件事：**理解人话**（"做个会飞的西瓜和章鱼的混种"）和**生成文案**；数据库侧的计算全部在服务里，512 维向量不来回搬运。DSL 由 [dify/build_dsl.py](dify/build_dsl.py) 生成，改流程改脚本即可。

## 两种跑法

### A. 纯本地 demo（不需要 Dify、不需要 Docker）

```bash
pip install -r requirements.txt
# 先确保 seekdb 在 127.0.0.1:2881（服务器模式；或改成 pyseekdb 嵌入式）
LLM_MODEL=/path/to/Qwen2.5-7B-Instruct bash scripts/start.sh
# 打开 http://127.0.0.1:8077
```

不想下模型？接任意 OpenAI 兼容端点：

```bash
LLM_BACKEND=openai OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1 \
OPENAI_API_KEY=sk-xxx LLM_MODEL=qwen-plus bash scripts/start.sh
```

### B. 接进 Dify（推荐用于演示）

见 [deploy/dify/README.md](deploy/dify/README.md)：用 Docker Compose 起 Dify，并让 **seekdb 同时当 Dify 的元数据库和向量库**（Dify ≥ 1.10.1），然后导入 `dify/vector-zoo.dsl.yml`，改一个 `ZOO_API` 环境变量即可。

> 机器没有 Docker 时，A 方案已经能完整演示；B 方案只是把编排搬到 Dify 里。

## 目录

```text
├─ service/
│  ├─ app.py              # FastAPI：本地 demo + Dify 工具接口
│  └─ zoo/
│     ├─ db.py            # 所有 seekdb SQL 都在这（建表 / KNN / 混合检索 / 统计）
│     ├─ genome.py        # embedding、基因混合、突变、8 条基因轴
│     ├─ domain.py        # 造物 / 杂交 / prompt / 兜底模板
│     └─ llm.py           # 本地 HF 或 OpenAI 兼容端点
├─ web/index.html         # 单页前端：合成台 / 图鉴 / 检索 / 生态
├─ dify/
│  ├─ vector-zoo.dsl.yml  # Dify Chatflow（导入即用）
│  ├─ build_dsl.py        # DSL 生成器
│  └─ README.md           # 导入步骤与排错
├─ deploy/dify/           # Dify 本地部署套件（Docker Compose + seekdb）
├─ sql/schema.sql
├─ scripts/
│  ├─ start.sh
│  └─ collect_evidence.py # 跑真实查询，生成 docs/evidence.md
├─ notebooks/vector_zoo_demo.ipynb
└─ docs/
   ├─ architecture.md     # 数据流、表结构、取舍
   ├─ evidence.md         # seekdb 实跑输出
   └─ demo_script.md      # 3 分钟演示脚本
```

## Demo 脚本（3 分钟）

1. **0:00–0:20** 打开页面：「输入两个词，让它们在向量空间里交配。」
2. **0:20–1:00** 输入 `冰箱 × 蝴蝶` → 出图鉴；指出"稀有度是刚才那次 KNN 算出来的"。
3. **1:00–1:40** 切到「检索」，搜「冷气」→ 展开下面那条 SQL，说明向量分 + 全文分 + JSON 过滤。
4. **1:40–2:20** 回到合成台，同样的词再点一次 → "这个组合已经诞生过了"，展示 KNN 去重。
5. **2:20–3:00** 切到「生态」：物种数、稀有度分布、基因多样性。

## 已知边界

- 本地 1.5B/7B 模型的文风不如 qwen-plus；接线上模型效果最好；
- 换 embedding 模型必须重建索引（维度变了）；
- 还没做文生图，图鉴只有文字 + 雷达图；
- 多人使用需要给 `creatures` 加 `user_id` 做基因池隔离。

## 参考

- [Dify × seekdb 官方集成文档](https://docs.seekdb.ai/seekdb/zh-CN/dify/)
- [seekdb 嵌入式模式](https://docs.seekdb.ai/seekdb/zh-CN/deploy-embedded-seekdb/)
- [Dify 官方仓库](https://github.com/langgenius/dify)
