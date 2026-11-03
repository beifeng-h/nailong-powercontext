# 提测说明 · 面向软件持续演进的 SDD 上下文管理系统

> 一句话：给 AI 开发助手装一个**工程上下文模块**——开工前把"当前有效的规格、
> 相关代码、相关测试"喂给它，同时明确告诉它**哪些决策已经失效、哪些先前的验证已经过期**。

交付目录：[`sdd-context/`](sdd-context/)，详见 [`sdd-context/README.md`](sdd-context/README.md)。

## 题目要求怎么落的

| 要求 | 做法 |
| --- | --- |
| 判断当前任务应遵守什么要求 | 规格带生命周期（`draft/active/superseded/deprecated`），**只有 `active` 进上下文**；草稿单列为"待评审"，失效规格单列为"已失效" |
| 判断哪些决策已经失效 | ADR 之间可互相取代；被取代的决策从有效列表剔除，但**保留在上下文里并注明取代者**，同时把取代者补进有效列表 |
| 判断先前验证是否仍适用于当前代码 | 四类检查：规格引用的**文件/符号**是否还在、**验证用例**是否还在、规格正文在上次评审后**是否被改过**（内容哈希 + 评审基线）、两份生效规格对同一需求键**是否口径冲突** |
| 提供当前有效的规格、相关代码和测试 | `sddctx context --task "..."` 直接产出提示词片段：规格 + 需求 + 验证用例、相关代码位置、改完必须重跑的测试、仍有效的决策、已失效的决策、阻塞项 |
| 通过实际代码修改验证效果 | `scripts/demo_drift.py` 把仓库复制到临时目录后**实际改代码**（改名一个被规格引用的函数 + 删掉被规格引用的测试文件），逐阶段看系统如何检出、助手如何被拦、改好后如何恢复 |

## 需要接入实例吗

**不需要。** 默认路径零外部依赖：Python 标准库 + 嵌入式 SQLite（`.sddctx/context.db` 一个文件），
不连数据库、不连网络、不调模型，clone 下来就能跑。

需要接 OceanBase / MySQL 实例时，存储层是 `ContextStore` 协议，
`sdd-context/sddctx/sqlstore.py` 提供 DB-API 适配器（自动适配 `qmark`/`format`/`pyformat`），
**resolver / drift / assistant 一行都不用改**；适配器本身已用 SQLite 的 `qmark` 风格跑通测试
（`tests/test_sqlstore.py`），接实例的风险只在连接与方言。见
[`sdd-context/docs/instance-optional.md`](sdd-context/docs/instance-optional.md)。

## 怎么验（评委 30 秒能跑完）

```bash
cd sdd-context
python -m unittest discover -s tests -t .    # 62 个用例
python -m sddctx refresh                     # 索引代码 + 导入 spec/ + 体检
python -m sddctx context --task "给上下文解析加上按改动文件加权排序"
python scripts/demo_drift.py                # 真实改代码 -> 检出漂移 -> 改好 -> 恢复
```

预期输出：

```text
Ran 62 tests in 3.0s
OK
索引 30 文件 / 288 符号 / 62 测试；导入 5 规格 / 3 决策
```

`doctor` 有 error 时退出码为 1，可直接接 CI。

## 目录

```text
sdd-context/
  sddctx/       模块本体（纯标准库，无第三方依赖）
    models.py       领域模型 + 上下文包渲染
    frontmatter.py  Markdown frontmatter 解析（YAML 受限子集）
    ingestion.py    文档 -> 模型，严格校验（错就报错，不静默跳过）
    indexer.py      代码/测试静态索引（ast）
    store.py        默认存储：嵌入式 SQLite
    sqlstore.py     可选：DB-API 适配器（OceanBase/MySQL）
    resolver.py     任务 -> 上下文包（相关性打分，可复现）
    drift.py        上下文有效性体检
    assistant.py    AI 助手宿主：提示词 + 执行清单 + 阻塞判断
    server.py       本地 HTTP 接口
    cli.py          命令行
  spec/         5 份 SDD 规格 + 3 条 ADR（含 1 条已失效决策）+ 评审基线
  tests/        62 个用例
  scripts/      可运行演示
  docs/         架构取舍 / 实跑证据 / 外部实例接入说明
```

## 设计要点

- **不绑模型**：模块只负责"检索 + 判定有效性"，产出提示词片段；用哪个模型是使用方的事。
- **可复现**：相关性用词元打分（ASCII 词 + 中文二元组），同分按规格 id 排序，
  同样输入必得同样输出——上下文系统不可复现就没法评审和排障。
- **规格即硬约束**：规格里的需求 id 必须逐条对应回复；
  改代码要同步改 `code_refs`，改规格要跑 `sddctx review` 重新记录评审基线。
- **评审基线随仓库走**：写在 `spec/reviews.json`（可提交），不是只存在本地数据库里，
  换机器 clone 下来也知道"这份规格上次验到哪儿了"。

实跑输出见 [`sdd-context/docs/evidence.md`](sdd-context/docs/evidence.md)。

