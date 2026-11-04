# 证据索引与来源边界

本目录保存真实历史运行的可审阅记录，以及明确标识的脱敏派生件。它不代表候选已经重新执行全部流程、获得官方成绩或取得发布授权。

| 官方要求 | 交付证据 | 能支持的结论与限制 |
| --- | --- | --- |
| 能够运行 | [入口与安装步骤](../README.md)、[SQL组合复核](sql-composition-20261104/README.md)、[离线安装摘要](offline-install-20261103/SUMMARY.json) | 独立离线venv中执行本候选，真实资料库、新状态、业务测试已验证；另一台机器重新安装未执行 |
| MiniMax 实际参与 | [真实调用](minimax/cn-dsh-20261103-run1/README.md) | 一次真实中国区 M3.1-Flash 请求，源码身份 b99c2e0a；实际 request、model-final、diff 与 after 可核验 |
| 上下文正确 | [本轮实际SQL上下文](sql-composition-20261104/INDEX.json)、[历史SourceDB记录](sourcedb-real/INDEX.json) | 本候选v2覆盖v1、旧要求精确失效；3次上下文的9份真实来源正文及SHA独立核对 |
| 数据库实际参与 | [本轮SQL回执](sql-composition-20261104/RECEIPT.json) | 真实seekdb 1.3.0.0实际入库与查询；SQL正文直接合入新进程任务上下文 |
| 状态能够复用 | [本轮组合CLI](sql-composition-20261104/README.md)、[候选状态复核](candidate-verification-20261104/README.md) | 空状态保存后由两个新进程恢复；状态、scope、citation和next_step一致，并实际用于SQL上下文 |
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
- `candidate-verification-20261104/` 是直接执行本候选的业务前后测试、开发入口回归、无Key预检与新状态跨进程复核；复用此前独立安装的离线venv，不是重新安装或真实SQL组合验证。收据中的sourceHashes绑定被测Python字节；该轮Git HEAD仍是提交前的生态基线，不能把这些文件说成生态基线自带。
- `sql-composition-20261104/` 是其后的真实seekdb与全新状态组合复核，9个CLI阶段、10项组合检查通过；输入绑定21份源码/样例/规格字节和起始提交0b9826dd。原服务器和OS辅助记录及存储留在本地，不是运行依赖；交付副本与原件的哈希归属在本目录INDEX中说明。

本候选整理历史模型开发记录，并补做了2026-11-04的实际业务、资料库与状态组合复核；本轮没有新模型请求。模式扫描无法排除所有敏感内容，最终发布范围和官方判题以单独核实的目标与回执为准。
