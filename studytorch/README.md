# StudySeek · 学习资料智能检索库

把 PDF / Markdown / TXT 学习资料切块向量化写进 **seekdb**（OceanBase 的 AI 原生搜索数据库），
用 **向量 + 全文混合检索** 找回内容，再让 **qwen-turbo** 基于检索到的片段回答并列出引用。

- 前端 + 后端：Next.js 14（App Router）+ TypeScript + Tailwind CSS
- 存储：seekdb，MySQL 协议（默认端口 2881），`mysql2` 客户端
- Embedding：阿里云 DashScope `text-embedding-v3`（1024 维）
- 解析：`pdf-parse`（PDF）、Markdown / TXT 直接读文本

---

## 1. 项目结构

```
studyseek/
├── .env.example              环境变量模板
├── next.config.mjs           Next 14 配置（serverComponentsExternalPackages + instrumentationHook）
├── package.json
├── postcss.config.mjs
├── tailwind.config.ts        品牌色板
├── tsconfig.json             @/* -> src/*
├── sql/documents.sql         建表 SQL 参考副本（含 WITH PARSER ik，代码里自动执行）
├── scripts/
│   ├── load-env.ts           脚本自读 .env.local
│   ├── rebuild-schema.ts     删表重建（切换全文分词器）
│   ├── seed.ts               10 条课程笔记入库
│   └── test-search.ts        混合 / 纯向量 / 纯全文 三路对比
└── src/
    ├── instrumentation.ts    启动时自动建库建表
    ├── types/pdf-parse.d.ts  pdf-parse 深路径导入的类型声明
    ├── app/
    │   ├── globals.css       Tailwind + .card/.btn-*/.input/.chip
    │   ├── layout.tsx        侧边栏外壳，读取分类与统计
    │   ├── page.tsx          首页：搜索框 + 拖拽上传
    │   ├── search/page.tsx   搜索结果页（混合检索）
    │   ├── browse/page.tsx   按分类浏览切块
    │   ├── ask/page.tsx      AI 问答页
    │   └── api/
    │       ├── upload/route.ts    POST 上传 -> 解析 -> 切块 -> 向量化 -> 入库
    │       ├── ask/route.ts       POST 问题 -> top5 检索 -> qwen-turbo 生成 -> 返回来源
    │       └── health/route.ts    GET 连接与配置自检
    ├── components/
    │   ├── Sidebar.tsx           分类列表 + 导航（点击过滤）
    │   ├── SearchBar.tsx         顶部搜索框
    │   ├── UploadDropzone.tsx    拖拽上传区
    │   ├── CategoryPicker.tsx    分类下拉（支持自定义新分类）
    │   ├── CategoryChips.tsx     分类筛选条
    │   ├── ResultCard.tsx        结果卡片（命中片段/文件名/分类/得分）
    │   ├── AskForm.tsx           问答表单 + 答案 + 引用来源
    │   └── Highlight.tsx         命中词高亮
    └── lib/
        ├── config.ts             环境变量与常量（500 字切块、批次 10 等）
        ├── types.ts              共享类型
        ├── ingest.ts             上传入库流水线
        ├── categories.ts         预置分类与库里分类合并
        ├── highlight.ts          高亮词提取 / 片段截取
        ├── cn.ts                 className 拼接
        ├── errors.ts             ApiError + 统一错误响应
        ├── ai/embeddings.ts      DashScope text-embedding-v3（自动分批）
        ├── ai/chat.ts            qwen-turbo Prompt 拼装与调用
        ├── db/pool.ts            mysql2 连接池单例
        ├── db/schema.ts          自动建库建表 + 结构自检
        ├── db/documents.ts       写入切块 / 分类聚合 / 浏览
        ├── db/hybrid-search.ts   DBMS_HYBRID_SEARCH 调用 + SQL 回退
        ├── documents/chunk.ts    500 字滑窗切块（50 字重叠）
        └── documents/extract.ts  PDF / MD / TXT -> 纯文本
```

---

## 2. 准备 seekdb

任选一种，能对外暴露 MySQL 协议 2881 端口即可。

**Docker（最快）**

```bash
docker run -d --name seekdb -p 2881:2881 -p 2222:2222 \
  -e OBDUMP_TIMEOUT=0 oceanbase/seekdb:latest
```

**本地二进制 / 已装好的 seekdb**：直接确认端口 2881 可连：

```bash
mysql -h 127.0.0.1 -P 2881 -u root -e "SELECT 1"
```

> 库和表不用手建：`documents` 表会在 Next.js 启动时自动创建（见 `src/lib/db/schema.ts`，
> 参考 SQL 在 `sql/documents.sql`）。

## 3. 配置环境变量

```bash
cp .env.example .env.local
```

编辑 `.env.local`：

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `SEEKDB_HOST` | seekdb 地址 | `127.0.0.1` |
| `SEEKDB_PORT` | MySQL 协议端口 | `2881` |
| `SEEKDB_USER` | 用户名 | `root` |
| `SEEKDB_PASSWORD` | 密码（本地默认空） | 空 |
| `DATABASE_NAME` | 库名，不存在会自动创建 | `studyseek` |
| `DASHSCOPE_API_KEY` | 阿里云百炼 DashScope Key，**必填** | — |

可选：`FULLTEXT_PARSER`（全文分词器，默认 `ik`，见第 6 节）、`DASHSCOPE_BASE_URL`、`EMBEDDING_MODEL`、
`EMBEDDING_DIMENSIONS`（改维度必须同步改建表 `VECTOR(n)`，最省事的做法是 `npm run db:rebuild -- --yes`）、`CHAT_MODEL`。

## 4. 本地跑起来

需要 Node.js 18.17+（Next 14 要求）。

```bash
cd studyseek
npm install
npm run dev
```

打开 http://localhost:3000

自检顺序建议：

1. 访问 http://localhost:3000/api/health —— 期望 `seekdb.connected: true`、`tables: ["documents"]`、
   `dashscope.apiKeyConfigured: true`。左侧栏出现「seekdb 未连接」红字时，先看这里报什么。
2. 首页拖一个 PDF / MD / TXT 进去（先选或新建分类），成功后会显示「N 字 → M 块」。
3. 顶部搜索框搜一个只在你资料里出现过的词，进结果页看命中片段和得分。
4. 点「就这个问题问 AI」或在 `/ask` 输入问题，看答案下面的引用来源。

生产构建：

```bash
npm run build && npm start
```

### 命令行脚本（重建索引 / 灌种子 / 验证检索）

脚本跑在 Next.js 之外，会自己加载 `.env.local`（`scripts/load-env.ts`），用的是同一套 `src/lib` 代码，
所以 DSL、切块、embedding 行为和页面完全一致。

```bash
npm run db:rebuild -- --yes          # DROP 并重建 documents（全文分词器改动后必须做，会清空数据）
npm run seed                         # 写入 10 条课程笔记（机器学习 / 数据结构 / 操作系统）
npm run search:test                  # 用「什么是过拟合」+ 口语化查询，分别打印混合 / 纯向量 / 纯全文三路结果
npm run search:test -- 你的查询词     # 也可以只测自己的查询
```

`db:rebuild` 是破坏性操作，没带 `--yes` 会直接退出。若当前 seekdb 镜像不带 ik 词典，用
`npm run db:rebuild -- --yes --parser=ngram`（或 `space`）换一种分词器，脚本会把实际执行的 DDL 打出来。

---

## 5. 检索是怎么走的

`/api/upload`：`pdf-parse` 或文本读取 → 500 字滑窗切块（重叠 50 字）→ 每 10 块一批调
`text-embedding-v3` 拿 1024 维向量 → 一条多值 `INSERT` 把 `content / file_name / category / embedding` 写进
`documents`。

`/search` 与 `/api/ask`：问题文本先 embedding，然后交给 seekdb 的混合搜索：

```sql
SET @search_parm = '{ "query": {...query_string...}, "knn": {...}, "rank": {"rrf": {...}}, "size": 10, "_source": [...] }';
SELECT DBMS_HYBRID_SEARCH.SEARCH('documents', @search_parm) AS result;
```

返回的是 JSON 数组（每个元素含列值 + `_score`，`_source` 里额外要了 `_keyword_score` / `_semantic_score`），
代码解析后映射成 `SearchHit`。

`/api/ask`：取 top5 片段 → 拼进带编号的 Prompt → `qwen-turbo` 生成回答 → 前端在答案下面按编号列引用。

## 6. 已知约束与踩坑提示

- **堆表**：seekdb 的混合搜索只支持 heap table，所以建表语句末尾是 `) ORGANIZATION = HEAP`。
- **中文全文检索**：默认全文解析器是 `space`（按空格切词），整句中文会被当成一个词，全文那一路基本不命中。
  本项目建表默认已改成 `WITH PARSER ik`（可用 `FULLTEXT_PARSER` 覆盖）。全文索引的 parser 不能 ALTER，
  只能删表重建，所以从旧表切换过来要跑：

  ```bash
  npm run db:rebuild -- --yes   # 会清空 documents 表，之后重新导入
  npm run seed
  npm run search:test           # 看纯全文那一路是否有命中
  ```

  如果当前 seekdb 镜像不带 ik 词典、DDL 报错，换 `--parser=ngram`（或 `space`，此时中文全文那一路只能靠向量兜住）。
- **`DBMS_HYBRID_SEARCH.SEARCH` 是返回 JSON 的函数**，官方用法是 `SELECT`，不是 `CALL`。
  参数只有两个：表名 + JSON 串；`query_string` 里的字段名是 `query`（不是 `query_text`）；
  标量过滤（`category`）必须放在 `bool.filter` 或 `knn.filter`，放进 `must` / `should` 会被内核拒绝。
- **回退路径**：如果这个存储过程在当前 seekdb 版本上不可用，`hybrid-search.ts` 会自动改用
  `ORDER BY l2_distance(...) APPROXIMATE LIMIT k` + `MATCH(content) AGAINST(?)` 两路查询并在应用层做 RRF，
  结果页会标注「SQL 回退」。首次调用失败时会看到一条 warning。
- **Embedding 批量上限**：`text-embedding-v3` 单请求最多 10 条文本、单条 8192 token，代码已按 10 条分批。
- **切块长度**：`content VARCHAR(4096)`，切块按 500 字，写入前再兜一层 4000 字符截断。
- 上传大小上限 8MB（`config.ts` 里的 `MAX_UPLOAD_BYTES`），只支持 `.pdf / .md / .markdown / .txt`。
- 首次连接失败后 `ensureReady()` 会清掉缓存，下一次请求自动重试建表，不用重启进程。

## 7. 常用命令

```bash
npm run dev        # 开发
npm run build      # 生产构建
npm run start      # 跑构建产物
npm run lint       # ESLint（next/core-web-vitals）
npm run typecheck  # tsc --noEmit
```
