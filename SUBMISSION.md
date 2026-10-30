# 提交说明 · 「Just for Fun」

> 一句话：说出两个八竿子打不着的词，Dify 让它们在 512 维向量空间里交配，生出一只新物种，写进 OceanBase seekdb 的图鉴。

## 用了什么

| 要求 | 我们的做法 |
| --- | --- |
| 必须使用 Dify | `dify/vector-zoo.dsl.yml`：9 节点 Chatflow（LLM ×2 / Code ×3 / HTTP ×2 / Start / Answer），负责理解人话、决定母本比例、撰写图鉴、多轮对话 |
| 必须实际使用 seekdb 或 PowerContext | **seekdb v1.4.0**：`VECTOR(512)` 基因组 + HNSW 亲缘检索 + ngram 中文全文索引 + JSON 元数据过滤，全部在一张 `creatures` 表里 |

没有把 seekdb 当"知识库挂件"：亲缘、稀有度、判重、检索排序、生态统计都由数据库算出来（见 `docs/architecture.md` 的取舍表，`docs/evidence.md` 的实跑输出）。

## 玩法（评委 30 秒能看懂）

1. 输入 `冰箱 × 蝴蝶`；
2. 两个词 → 两个 512 维向量 → 加权混合 + 可复现突变 = 基因组；
3. 拿基因组去 seekdb 做 KNN，找最近的"亲戚"，顺便算出**稀有度**（越不像别人越稀有）；
4. Dify 的 LLM 根据"基因轴 + 亲戚"写名字、习性、图鉴正文；
5. 落库；同一组合再点一次会提示"已经诞生过了"（KNN 判重）。

## 怎么验

```bash
pip install -r requirements.txt
LLM_MODEL=/path/to/Qwen2.5-7B-Instruct bash scripts/start.sh   # 需要 seekdb 在 127.0.0.1:2881
# 浏览器打开 http://127.0.0.1:8077
```

没有本地模型：`LLM_BACKEND=openai OPENAI_BASE_URL=... OPENAI_API_KEY=... LLM_MODEL=qwen-plus bash scripts/start.sh`

接 Dify：见 `deploy/dify/README.md`（Docker Compose 起 Dify，seekdb 同时当元数据库和向量库），导入 `dify/vector-zoo.dsl.yml`，改 `ZOO_API`，选模型。

## 已验证

- seekdb 1.4.0 实跑：建表 / HNSW / ngram 全文 / JSON 过滤 / 混合排序 / 统计，输出见 `docs/evidence.md`；
- 造物链路实测：`ZK-0013 霜翼蝶`（冰箱 × 蝴蝶，稀有，最近亲缘距离 0.897）；
- Dify 侧接口联调：`/api/dify/forge`（造基因组 + KNN）→ LLM 写图鉴 → `/api/dify/commit`（落库 + 返回 Markdown 卡片）；
- 判重：同组合第二次调用返回 `duplicate`。

## 目录

- `service/`：FastAPI + bge-small-zh-v1.5 + Qwen2.5；`service/zoo/db.py` 收敛全部 SQL
- `dify/`：Chatflow DSL + 生成器 + 导入说明
- `web/`：单页前端（合成台 / 图鉴 / 检索 / 生态）
- `deploy/dify/`：Dify 本地部署套件
- `docs/`：架构、证据、演示脚本
- `notebooks/`：端到端 demo notebook
