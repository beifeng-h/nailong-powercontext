# 给 AI 助手的上下文说明

本仓库是 **SDD 上下文管理系统**（`sddctx`）：让 AI 开发助手在开工前拿到
当前有效的规格、相关代码、相关测试，并明确哪些决策已经失效、哪些先前的验证已经过期。

本文件就是这套系统的一个输出样例——它由 `sddctx context` 的产出结构写成。

## 动手之前

```bash
python -m sddctx refresh                                  # 索引代码 + 导入 spec/ + 体检
python -m sddctx context --task "<你这次要做的事>"        # 取上下文包
python -m sddctx doctor                                   # 看上下文还有没有效
```

`doctor` 出现 `error` 时，先把上下文修好再写代码：多半是规格里写的符号或测试
被改名/删掉了，或者是两份生效规格对同一件事说法不一。

## 硬性约定

1. **规格是硬约束**：`spec/specs/*.md` 里 `status: active` 的需求必须满足，
   需求 id 要在回复里逐条对应。
2. **改代码要改规格**：动了 `sddctx/` 里的函数名或签名，同步更新引用它的
   `code_refs`；这一步不做，`doctor` 会立刻报 `SPEC_CODE_SYMBOL_MISSING`。
3. **改规格要重新评审**：规格正文改完跑 `python -m sddctx review <spec-id>`，
   否则会报 `SPEC_CHANGED_AFTER_REVIEW`（旧验证结论可能已过期）。
4. **决策先看状态**：`spec/decisions/*.md` 里 `status: accepted` 的才算数；
   `superseded` 的只作历史参考，不要照着实现。
5. **测试必须重跑**：规格 `test_refs` 里列出的用例是验收口径，改完必须全绿。

## 代码地图

| 路径 | 职责 | 对应规格 |
| --- | --- | --- |
| `sddctx/models.py` | 领域模型与上下文包渲染 | SPEC-001 |
| `sddctx/frontmatter.py` | frontmatter 解析（YAML 受限子集） | SPEC-003 |
| `sddctx/ingestion.py` | 文档 -> 模型，严格校验 | SPEC-003 |
| `sddctx/indexer.py` | 代码/测试静态索引（`ast`） | SPEC-002 |
| `sddctx/store.py` | 默认存储（嵌入式 SQLite） | SPEC-003 |
| `sddctx/sqlstore.py` | 可选：DB-API 适配器（OceanBase/MySQL） | — |
| `sddctx/resolver.py` | 任务 -> 上下文包 | SPEC-001 |
| `sddctx/drift.py` | 上下文有效性体检 | SPEC-002 |
| `sddctx/assistant.py` | 助手宿主：提示词、清单、阻塞判断 | SPEC-004 |
| `sddctx/server.py` / `sddctx/cli.py` | 对外接口 | SPEC-005 |

## 验收

```bash
python -m unittest discover -s tests -t .   # 全部用例必须通过
python scripts/demo_drift.py                # 演示真实改动如何被检出
```

新增功能时：先在 `spec/specs/` 写规格（含 `requirements` 与 `verified_by`），
再写实现与测试，最后 `python -m sddctx review <spec-id>` 记录评审基线。

