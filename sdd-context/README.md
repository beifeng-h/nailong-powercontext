# sddctx · 面向软件持续演进的 SDD 上下文管理系统

给 AI 开发助手用的**工程上下文模块**：开工之前先把"当前有效的规格、相关代码、
相关测试"捞出来给它，同时明确告诉它**哪些决策已经失效、哪些先前的验证已经过期**。

软件越演进而规格越多、越容易互相矛盾；只把文档塞给模型，它会拿着三年前的口径
继续写代码。这个模块解决的就是这件事：**上下文不是"检索出来的一堆文件"，
而是"检索出来 + 判定过是否还有效"的一组东西**。

```
开发任务 ──▶ 解析器 ──▶ 当前有效规格 / 相关代码 / 相关测试 / 有效决策
                            │
                            └──▶ 已失效决策、过期验证、冲突规格 ──▶ 阻塞项
```

## 不需要接入任何实例

**默认路径零外部依赖**：Python 标准库 + 嵌入式 SQLite（库文件落在 `.sddctx/context.db`）。
`clone` 下来就能 `python -m sddctx refresh`，不需要数据库、不需要网络、不需要模型。

如果确实想把上下文存到 OceanBase / MySQL 实例上，存储层是可替换的协议
（`ContextStore`），`sddctx/sqlstore.py` 提供了 DB-API 适配器，
`resolver` / `drift` / `assistant` 一行都不用改。详见
[`docs/instance-optional.md`](docs/instance-optional.md)。

## 30 秒上手

```bash
python -m unittest discover -s tests -t .      # 59 个用例，全绿
python -m sddctx refresh                       # 索引代码 + 导入 spec/ + 体检
python -m sddctx context --task "给上下文解析加按改动文件加权排序"
python -m sddctx doctor                        # 上下文体检（error 时退出码 1）
python scripts/demo_drift.py                   # 真实改代码 -> 检出漂移的完整演示
```

评审基线写在 `spec/reviews.json`（跟着仓库走，不在本地数据库里），
所以换台机器 clone 下来也知道"先前的验证验到哪儿了"。

`context` 的输出可以直接喂给模型：

```markdown
# 开发任务上下文：给上下文解析加按改动文件加权排序

## 当前有效的规格
### SPEC-001 上下文解析契约  (status=active)
必须满足：
- [REQ-CTX-2] 上下文包必须同时给出相关代码位置与改动后需要重跑的测试  <- 验证：tests/test_resolver.py::ResolverTests::test_resolve_returns_code_and_tests
相关代码：
- `sddctx/resolver.py:ContextResolver.resolve` — 上下文解析入口
...
## 已失效、不要依赖的决策
- ADR-003 仅靠 status 字段判断规格有效性，被 ADR-002 取代
```

## 它到底做了什么

### 1. 判断"当前有效"（哪些要求必须遵守）

规格有生命周期：`draft → active → superseded → deprecated`。只有 `active` 进上下文；
`draft` 作为"待评审"单列；`superseded` / `deprecated` 进"已失效"清单。
决策同理，`accepted` 才是有效决策。

### 2. 判断"哪些决策已经失效"

ADR 之间可以互相取代。系统把被取代的决策从有效决策里剔除，
但**保留在上下文里并标注取代者**——助手需要知道"以前那条规则作废了，
现在听这条"，否则它会按旧规则实现，或者干脆两条都遵守。

### 3. 判断"先前的验证是否还适用于当前代码"

这是最容易被忽略、也最容易出事的一环。四种检查：

| 情况 | 判定 | 含义 |
| --- | --- | --- |
| 规格引用的文件/符号没了 | error | 代码被重构或删除，规格已脱节 |
| 规格引用的验证用例没了 | error | 先前的验证不再适用 |
| 规格在上次评审后被改过 | warning | 验证结论可能已过期，需要重新确认 |
| 两份生效规格定义同一需求键但说法不同 | error | 口径没统一，不能开工 |

判定"改过没评审"靠的是**内容哈希 + 评审基线**（`sddctx review <spec-id>` 记录基线），
而不是只看 `status` 字段——人改了正文常常忘了改状态。

### 4. 组装成助手能直接用的上下文包

上下文包里除了规格，还有：相关代码位置、改完必须重跑的测试、仍然有效的决策、
已失效的决策、以及**阻塞项**。有 error 级阻塞项时，助手拿到的是
`ready = False`，不允许直接开工。

## 目录结构

```
sddctx/                  模块本体（纯标准库）
  models.py              领域模型：规格/决策/引用/上下文包
  frontmatter.py         Markdown frontmatter 解析（YAML 受限子集）
  ingestion.py           文档 -> 领域模型，严格校验
  indexer.py             代码/测试静态索引（ast）
  store.py               默认存储：嵌入式 SQLite
  sqlstore.py            可选：DB-API 适配器（OceanBase/MySQL）
  resolver.py            任务 -> 上下文包（相关性打分）
  drift.py               上下文有效性体检
  assistant.py           AI 助手宿主：提示词 + 执行清单 + 阻塞判断
  server.py              本地 HTTP 接口
  cli.py                 命令行
spec/
  specs/                 SDD 规格（本仓库自己的规格）
  decisions/             架构决策 ADR
tests/                   59 个用例
scripts/                 可运行演示
docs/                    架构、取舍、证据、外部实例接入说明
```

## 规格文档长什么样

`spec/specs/*.md` 是规格，`spec/decisions/*.md` 是决策，都是 Markdown + frontmatter：

```markdown
---
id: SPEC-001
title: 上下文解析契约
status: active
scope: [resolver, models]
tags: [context, resolve, sdd]
requirements:
  - id: REQ-CTX-1
    key: context.resolve.effective_only
    text: 只有 status=active 的规格可以进入开发上下文
    verified_by:
      - tests/test_resolver.py::ResolverTests::test_resolve_excludes_superseded_spec
code_refs:
  - file: sddctx/resolver.py
    symbol: ContextResolver.resolve
    note: 上下文解析入口
test_refs:
  - file: tests/test_resolver.py
    test_id: tests/test_resolver.py::ResolverTests::test_resolve_excludes_superseded_spec
    covers:
      - REQ-CTX-1
---
```

`code_refs` / `test_refs` 是体检的抓手：指向的符号或用例消失，系统立刻知道。

## 命令行

```
python -m sddctx init                       # 建库
python -m sddctx index                      # 索引代码与测试
python -m sddctx ingest                     # 导入 spec/
python -m sddctx refresh                    # index + ingest + 体检摘要
python -m sddctx context --task "..."       # 取上下文包（--format json）
python -m sddctx doctor [--json] [--spec SPEC-001]
python -m sddctx review SPEC-001            # 记录评审基线
python -m sddctx assistant --task "..."     # 生成提示词 + 执行清单
python -m sddctx serve --port 8787          # 本地 HTTP 接口
```

全局参数：`--db`（库文件）、`--root`（被管理的代码根目录）、`--spec-dir`（规格目录）。
`doctor` 发现 error 时退出码为 1，可以直接接进 CI。

## HTTP 接口

```bash
python -m sddctx serve --port 8787
curl "http://127.0.0.1:8787/api/context?task=上下文解析&format=markdown"
```

| 路由 | 说明 |
| --- | --- |
| `GET /api/health` | 存活与统计 |
| `GET /api/specs` | 全部规格 |
| `GET /api/decisions` | 全部决策 |
| `GET /api/context?task=...` | 上下文包（`format=markdown` 返回提示词） |
| `GET /api/doctor` | 体检结果 |
| `POST /api/refresh` | 重新索引并导入 |

## 作为库使用

```python
from sddctx import AssistantRuntime, SqliteStore

store = SqliteStore(".sddctx/context.db")
runtime = AssistantRuntime(store, root=".")
runtime.refresh()

packet = runtime.prepare_task("给任务列表加上按状态过滤")
print(packet.prompt)      # 喂给模型
print(packet.checklist)   # 助手要逐条走完
if not packet.ready:
    print(packet.blocking) # 上下文有问题，先解决再开工
```

## 验证

```bash
python -m unittest discover -s tests -t .    # 59 passed
python scripts/demo_drift.py                 # 真实代码改动的完整演示
python scripts/demo_assistant.py             # 助手拿到上下文的样子
```

真实运行输出见 [`docs/evidence.md`](docs/evidence.md)。

## 设计取舍

| 决定 | 理由 |
| --- | --- |
| 嵌入式 SQLite 做默认存储 | 零依赖、可离线、可直接交付；外部实例是可插拔选项 |
| 相关性用词元打分而不是模型 | 离线、确定性、可解释；同样的输入必得同样的输出 |
| frontmatter 自带 YAML 子集解析器 | 全系统只依赖标准库；解析失败明确报错而不是静默跳过 |
| 用内容哈希 + 评审基线判定有效性 | 比只看 `status` 强，能抓住"正文改了状态没改" |
| error 才阻塞，warning 只提醒 | 上下文过期要拦，口径未定也要拦；其余不阻塞日常开发 |

更完整的取舍见 [`docs/architecture.md`](docs/architecture.md)。

