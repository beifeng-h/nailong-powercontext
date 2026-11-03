# 架构与取舍

## 模块边界

```
frontmatter ──▶ ingestion ──▶ models.Spec / models.Decision
                                    │
indexer（ast 静态解析）─────────────┤
                                    ▼
                                  store.ContextStore（协议）
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
                 resolver        drift          assistant
              任务 -> 上下文包   有效性体检    提示词 + 清单
                                    │               │
                                    └───────┬───────┘
                                            ▼
                                    cli / server（对外接口）
```

四个环节只通过 `models` 里的数据结构交换信息，因此：

- 换存储（接 OceanBase 实例）只需要换一个 `ContextStore` 实现；
- 换语言（索引器只懂 Python）只需要加一个索引适配器；
- 换模型（助手侧）不影响本模块，它不产生任何自然语言决策，只做检索与判定。

## 数据模型

| 实体 | 关键字段 | 说明 |
| --- | --- | --- |
| `Spec` | `id` `status` `scope` `tags` `requirements` `code_refs` `test_refs` | 规格；`content_hash` 由正文算出 |
| `Requirement` | `id` `key` `text` `verified_by` | `key` 用于跨规格检测口径冲突；`verified_by` 是测试 id 列表 |
| `CodeRef` | `file` `symbol` `note` | 指向代码位置，`symbol` 可空（只指文件） |
| `TestRef` | `file` `test_id` `covers` | 指向验证用例，并声明覆盖哪些需求 |
| `Decision` | `id` `status` `superseded_by` | 架构决策；`superseded_by` 构成取代链 |
| `Finding` | `code` `severity` `target` `message` | 体检结论；`severity=error` 视为阻塞 |
| `ContextBundle` | `specs` `candidates` `decisions` `invalidated_*` `code_refs` `tests` `findings` | 一次任务的上下文包 |

### 为什么 `code_refs` 要指到符号级别

只指文件的话，文件还在但函数被改名，系统察觉不到——而这正是重构里最常见的改动。
指到符号级别（`sddctx/resolver.py:ContextResolver.resolve`）才能在改名当天就报警。
代价是规格要跟着重构一起改，这正是我们想要的：让"改代码"和"改规格"变成同一件事。

## 规格文档格式

frontmatter 支持的字段（`sddctx/frontmatter.py` 实现的 YAML 受限子集）：

| 字段 | 适用 | 说明 |
| --- | --- | --- |
| `id` | 两者 | 必填。规格 `SPEC-xxx`，决策 `ADR-xxx` |
| `title` | 两者 | 必填 |
| `status` | 两者 | 规格：`draft/active/superseded/deprecated`；决策：`proposed/accepted/superseded/rejected` |
| `scope` / `tags` | 两者 | 相关性打分的输入 |
| `supersedes` | 两者 | 取代了谁 |
| `superseded_by` | 两者 | 被谁取代 |
| `decided_at` | 决策 | 决策日期 |
| `requirements` | 规格 | 需求列表，每项含 `id` / `key` / `text` / `verified_by` |
| `code_refs` | 规格 | 代码引用，每项含 `file` / `symbol` / `note` |
| `test_refs` | 规格 | 测试引用，每项含 `file` / `test_id` / `covers` |

不支持 YAML 高级特性（锚点、多文档等），解析失败直接报错并带上文件路径——
规格写错必须立刻暴露，不能静默跳过。

## 相关性打分

没有用模型，用可解释的词元打分（ASCII 词 + 中文单字与二元组）：

| 信号 | 权重 | 理由 |
| --- | --- | --- |
| 标签命中 | 4.0 | 人工标注的意图，最可信 |
| 范围命中 | 3.0 | 模块级归属 |
| 标题命中 | 3.0/词 | 标题是规格的"索引词" |
| 需求正文命中 | 1.0/词 | 细节匹配 |
| 正文命中 | 0.2/词 | 兜底 |
| 引用文件命中本次改动 | 6.0 | 改到哪儿就带哪份规格 |

同分按规格 id 排序，保证**同样的输入必得同样的输出**——上下文系统如果不可复现，
评审和排障都会变得很痛苦。

## 有效性判定

### 代码漂移

规格引用的文件或符号在当前代码索引里找不到 → `error`。
索引来自 `ast` 静态解析，收集模块级函数/类/方法，测试文件额外收集
`test_*` 函数与测试类方法（兼容 `TestFoo` 与 `FooTests` 两种写法）。

### 验证漂移

- 规格引用的测试 id 不存在 → `error`（先前的验证不再适用）
- 需求的 `verified_by` 全部消失 → `error`
- 需求从未有验证用例 → `warning`

### 规格漂移

`sddctx review <spec-id>` 记录"正文哈希 + 时间"作为基线。当前哈希与基线不一致
→ `warning`（规格在上次评审后被改过，验证结论可能过期）。

基线只覆盖正文，格式调整不会误报。

### 决策失效

`status=superseded` 的决策不进有效列表，但会：

1. 以"已失效、不要依赖"的段落出现在上下文里，并注明取代者；
2. 把取代者（若有效）补进有效决策列表；
3. 在体检里记一条 `DECISION_SUPERSEDED`（info），让"为什么这条不见了"可追溯。

### 冲突

两份 `active` 规格出现相同 `requirement.key` 且正文不同 → `error`。
不允许系统自己挑一个，必须人来定口径。

## 取舍表

| 决定 | 备选 | 选了它 | 代价 |
| --- | --- | --- | --- |
| 存储 | 外部实例 / 纯文件 / 嵌入式 SQLite | 嵌入式 SQLite | 多人共享需换适配器 |
| 相关性 | 向量检索 / 模型重排 / 词元打分 | 词元打分 | 语义泛化能力弱，但可解释、可复现、离线 |
| 判定漂移 | git 历史 / 只看 status / 内容哈希加评审基线 | 内容哈希加评审基线 | 需要有人维护评审记录 |
| 索引 | 正则 / tree-sitter / `ast` | `ast` | 只支持 Python，其他语言需加适配器 |
| 阻塞策略 | 全部阻塞 / 只拦严重问题 | 只拦 error | 少数过期上下文仍可能进上下文，但都带 warning |
| 状态表达 | 自由文本标签 / 枚举加生命周期 | 枚举加生命周期 | 新增状态要改代码 |

## 扩展点

- **换存储**：实现 `ContextStore` 协议即可，`sddctx/sqlstore.py` 是现成模板。
- **换语言索引**：在 `indexer.py` 旁边加一个适配器，产出同样的 `Symbol` / `TestCase`。
- **换相关性**：替换 `ContextResolver.score_spec`，保持输出结构不变。
- **接模型**：把 `assistant.build_prompt()` 的输出直接送进模型即可，本模块不碰推理。

