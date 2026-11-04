# 证据索引与来源边界

本目录保存真实历史运行的可审阅记录，以及明确标识的脱敏派生件。它不代表候选已经重新执行全部流程、获得官方成绩或取得发布授权。

| 官方要求 | 交付证据 | 能支持的结论与限制 |
| --- | --- | --- |
| 能够运行 | [入口与安装步骤](../README.md)、[离线安装摘要](offline-install-20261103/SUMMARY.json) | 50 项锁定依赖、pip check 与业务测试已有记录；新环境完整真实数据库整链未完成 |
| MiniMax 实际参与 | [真实调用](minimax/cn-dsh-20261103-run1/README.md) | 一次真实中国区 M3.1-Flash 请求，源码身份 b99c2e0a；实际 request、model-final、diff 与 after 可核验 |
| 上下文正确 | [SourceDB 记录](sourcedb-real/INDEX.json)、[组合上下文](task-context-real/INDEX.json) | 规格 v2 覆盖 v1、旧要求被拒、SQL 返回规格/代码/测试；属于历史运行 |
| 数据库实际参与 | [SourceDB 回执](sourcedb-real/RECEIPT.json) | 实际 seekdb SQL 入库与查询，非本地文件替代；新离线环境未复跑 SQL |
| 状态能够复用 | [SDK 跨进程记录](powercontext-real/INDEX.json)、[组合 CLI](task-context-real/INDEX.json)、[隔离复核摘要](isolated-repro-20261103/SUMMARY.json) | 保存与恢复 PID 不同；恢复状态被实际上下文使用；隔离复核复用既有依赖 |
| 代码修改有效 | [同轮测试派生回执](minimax/cn-dsh-20261103-run1/redacted-evidence/tests/RECEIPT.redacted.json)、[固定测试](../tests/test_taskboard.py) | 3 项目标由失败转通过、6 项回归通过；测试和前后代码 SHA-256 固定，无官方结果推断 |

## 派生文件的核验规则

[HISTORY_DERIVATIONS.json](HISTORY_DERIVATIONS.json)逐个记录 13 个历史文件的原始与派生 SHA-256、替换字段以及重建索引的原始身份。JSON 派生件有 `_derivation`，文本日志有派生标头。原件保留在本地，未覆盖，未并入候选 Git 历史。

`powercontext-real`、`sourcedb-real`、`task-context-real` 的 `INDEX.json.files` 均为当前交付文件的实际字节哈希；其中 `historical_original_index` 只归档原始索引事实。其他记录内部既有 payload/context 等 hash 仍标识历史原件，不能用它们校验已修改的派生件。历史命令中的路径占位符用于审阅，不是可以原样执行的命令。

`before/before-input-manifest.json` 是历史临时快照的原始清单，包括未交付的旧 DESIGN.md/README；它不描述当前候选文件。`before/before-all.json` 的旧 input_manifest 字段也属于该次历史记录。当前代码身份以候选文件与包装清单核对。

原始模型 `context.json` 含本机路径，未交付。`attempt-started.json` 中该文件的 hash 是原始身份；实际发送的 `request.json` 则使用脱敏上下文，其结构和值与交付的 `redacted-evidence/context.redacted.json` 相同。请求和模型输出没有替换成新的运行。

## 各轮不能混用

- `before/` 是早期功能红灯，不是模型调用后的同轮对照。
- `minimax/cn-dsh-20261103-run1/redacted-evidence/tests/` 才是一次真实模型调用后的固定 before/after 对照，派生日志的原始与交付 hash 见其 MANIFEST。
- `isolated-repro-20261103/` 是隔离项目/新状态的复核，复用依赖、没有真实 SQL，且复制时 develop.py 早于后续预检修复。
- `offline-install-20261103/` 是新离线 venv 的依赖和业务测试摘要，没有状态恢复或真实 SQL。摘要引用的是独立历史结果，不是当前候选整链成功。

本候选只整理既有真实记录；没有新增模型或数据库调用。模式扫描无法排除所有敏感内容，最终发布范围和官方判题以单独核实的目标与回执为准。
