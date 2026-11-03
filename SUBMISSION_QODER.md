# 提交说明 · StudySeek（Qoder 训练营）

一句话：把 PDF / Markdown / TXT 学习资料切块向量化写进 **seekdb**（OceanBase 的 AI 原生搜索数据库），用**向量 + 全文混合检索**找回内容，再基于检索到的片段给出带引用的回答；整个项目用 **Qoder** 开发，站点通过 **Qoder Sites** 发布。

## 提交信息（对应提交表单）

| 表单字段 | 填写内容 |
| --- | --- |
| 代码仓库地址 | https://github.com/beifeng-h/nailong-powercontext.git |
| Branch | `qoder-studytorch` |
| 作品链接 | https://studytorch-okhinknhvg0.qoder.website |
| Commit id | `83ac29b3f2e80ab9bbdc250d33c183d9d79b637b`（[permalink](https://github.com/beifeng-h/nailong-powercontext/commit/83ac29b3f2e80ab9bbdc250d33c183d9d79b637b)） |

## 用了什么

| 要求 | 我们的做法 |
| --- | --- |
| 必须使用 Qoder 开发 | 全部代码由 Qoder agent 在 Qoder IDE 工作区内生成、运行与自检（qodercli 驱动，Qoder Sites 官方 skill 参与构建与发布） |
| 必须实际使用 seekdb 或 PowerContext | **seekdb v1.3.0（本机实跑）**，见下方实测证据 |
| 项目网站必须通过 Qoder Sites 发布 | Qoder Sites 站点已发布并公开：published 为 true，readiness 为 publication_completed，access_mode 为 public，页脚带 Qoder 平台标识 |

## 挑战三项硬性要求逐条对照

1. **用 Qoder 开发** —— 项目在 Qoder IDE 打开的工作区内完成，开发、验证、发布三个阶段均由 Qoder agent 真实执行。prepare_site / get_publish_status / publish_site / update_access_policy 全部走 Qoder Sites 官方接口。
2. **实际使用 seekdb** —— 不是把 seekdb 当「知识库挂件」：向量检索、全文检索、混合排序、过滤、统计全部由数据库执行。表结构用了 seekdb 专有能力：VECTOR(1024)、VECTOR INDEX ... type=hnsw lib=vsag、FULLTEXT INDEX ... WITH PARSER ik、ORGANIZATION = HEAP。检索走原生 DBMS_HYBRID_SEARCH.SEARCH（query_string 与 knn 并行、rank.rrf 融合），并保留两路召回 + 应用层 RRF 的 SQL 回退。
3. **通过 Qoder Sites 发布** —— 站点地址 https://studytorch-okhinknhvg0.qoder.website ，无登录态访问返回 HTTP 200。

## 实测证据

### 建表（seekdb 实跑）

    CREATE TABLE IF NOT EXISTS documents (
        id INT PRIMARY KEY AUTO_INCREMENT,
        content VARCHAR(4096),
        file_name VARCHAR(255),
        category VARCHAR(64),
        embedding VECTOR(1024),
        VECTOR INDEX idx_vec(embedding) WITH (distance=l2, type=hnsw, lib=vsag),
        FULLTEXT INDEX idx_ft(content) WITH PARSER ik
    ) ORGANIZATION = HEAP;

ORGANIZATION = HEAP 是必须的：seekdb 只在堆表上支持混合搜索。WITH PARSER ik 是中文全文检索的关键，默认 space 分词会把整句中文当成一个词导致全文那一路不命中。

### 混合检索（原生 DBMS_HYBRID_SEARCH.SEARCH）

    [studyseek] seekdb 就绪：127.0.0.1:2881/studyseek（全文分词器 ik）
    查询：什么是过拟合
    检索路径：DBMS_HYBRID_SEARCH.SEARCH（原生混合搜索）
    1. id=1  机器学习-过拟合与正则化.md   score=0.0325 kw=0.8260 sem=0.4334
    2. id=2  机器学习-偏差与方差.md       score=0.0325 kw=0.8284 sem=0.4305
    纯向量 5 条 · 纯全文 5 条 · 向量与全文交集 3 条

### 服务自检

    GET /api/health
    {"seekdb":{"host":"127.0.0.1","port":2881,"database":"studyseek","connected":true,
                "tables":["documents"],"chunks":10},
     "dashscope":{"apiKeyConfigured":false,"embeddingModel":"text-embedding-v3",
                "dimensions":1024,"chatModel":"qwen-turbo"}}

### 站点自检

scripts/verify-site.ts 共 30 项检查，全部通过（产物完整性、无外部 CDN、无密钥、混合检索实现、上传链路、响应式与可访问性等）。

## 项目结构

    studytorch/                          # 本次提交新增的 Qoder 项目
    |-- src/app/                         # 首页（搜索 + 拖拽上传）、搜索结果页、浏览页、AI 问答页
    |   `-- api/                         # upload / ask / health 三个 Route Handler
    |-- src/components/                  # 侧边栏分类、搜索框、上传区、结果卡片、高亮
    |-- src/lib/
    |   |-- db/                          # pool / schema（自动建库建表）/ documents / hybrid-search
    |   |-- ai/                          # embeddings（DashScope + 本地降级）、chat（qwen-turbo + 抽取式降级）
    |   `-- documents/                   # chunk（500 字切块）、extract（pdf-parse / md / txt）
    |-- scripts/                         # rebuild-schema / seed / test-search / generate-site-data / verify-site / serve-site
    |-- site/                            # Qoder Sites 发布产物（纯静态，无构建步骤）
    |   |-- index.html
    |   `-- assets/                      # css / js（BM25 + 余弦 kNN 混合检索）/ vendor/pdfjs
    |-- .StudySeek.qoder.site            # Qoder Sites 自动生成的站点描述文件（发布凭证）
    `-- sql/documents.sql                # 建表 SQL 参考副本

## 怎么验

### 完整版（Next.js + 本机 seekdb）

    cd studytorch
    pnpm install
    pnpm run db:rebuild -- --yes   # 连接 seekdb 建库建表
    pnpm run seed                  # 导入示例资料
    pnpm run dev                   # http://127.0.0.1:3000

其他脚本：pnpm run search:test（混合 / 纯向量 / 纯全文 三路对比）、pnpm run build、pnpm run typecheck。

前置条件：本机 seekdb 监听 127.0.0.1:2881（root / 空密码），数据库名 studyseek。连接参数写在 .env，模板见 .env.example：SEEKDB_HOST / SEEKDB_PORT / SEEKDB_USER / SEEKDB_PASSWORD / DATABASE_NAME / DASHSCOPE_API_KEY。

### 线上站点（Qoder Sites，公开）

直接打开 https://studytorch-okhinknhvg0.qoder.website 。云端访问不到本机 seekdb，因此线上版把检索整体放在浏览器里完成：内置 12 篇示例资料 / 26 个片段，预计算向量由项目同一个 localEmbed 算法生成（与后端最大绝对误差 4.98e-7），检索为 BM25 + 余弦 kNN 按 0.6 / 0.4 加权融合；拖入 PDF/MD/TXT 后在浏览器内解析、切块 500 字、计算向量、入内存索引，可被检索。

本地预览：pnpm exec tsx scripts/serve-site.mjs，地址 http://127.0.0.1:4173 。

## 已知限制

- 本机没有配置 DASHSCOPE_API_KEY，因此嵌入与问答走的是**本地确定性降级实现**（归一化分词 + 哈希投影到 1024 维、L2 归一化；回答为检索片段抽取式组织），服务端日志有明确 warning。DashScope text-embedding-v3 与 qwen-turbo 的代码路径均已实现，在 .env 填入 Key 并重启后自动切回云端模型，无需改代码。
- 降级嵌入器只反映字面/词形重叠，语义召回能力弱于云端嵌入；这一点在实现里显式标注，未做掩饰。
- 线上站点为静态构建，不含 Functions 与后端数据库（databaseAccess 为 none）。

## 提交校验

本分支携带完整项目的提交为 `83ac29b3f2e80ab9bbdc250d33c183d9d79b637b`，
commit 链接： https://github.com/beifeng-h/nailong-powercontext/commit/83ac29b3f2e80ab9bbdc250d33c183d9d79b637b

仓库内 `studytorch/site/index.html` 的 SHA-256 与 Qoder Sites 站点描述文件
`studytorch/.StudySeek.qoder.site` 中记录的 `indexSha256` 完全一致，
即仓库里的静态产物与线上已发布的字节完全相同。

线上站点： https://studytorch-okhinknhvg0.qoder.website （无登录态 HTTP 200）