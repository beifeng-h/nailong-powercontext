# 规有所依：MiniMax 任务上下文 CLI

本模块用真实 seekdb SQL 检索规格、代码和测试，用 PowerContext 保存任务进度，在新进程中恢复，并把这些上下文交给 MiniMax 修改一个 Taskboard 业务函数。已保存真实 SQL、跨进程恢复、一次 MiniMax 调用及同组测试由失败转通过的历史证据。本目录是从官方生态基线整理的独立本地候选；完整干净环境与真实数据库组合复现、该候选的官方评测仍未完成。

## 安装和资料库

在本目录运行命令。历史环境是 Windows x64、CPython 3.12.14、seekdb 1.3.0.0、PyMySQL 1.2.3；PowerContext 固定源码 `dab240063bfcfa7917898dc44da4baadb3747bd0`，构建版本 `1.2.1.dev2+gdab240063`。运行依赖见 [requirements.lock](requirements.lock)。

```sh
python -m venv .venv
# Activate the environment, then install the locked runtime dependencies.
python -m pip install -r requirements.lock
```

使用自己的已有 seekdb/OceanBase 测试服务；也可参考[官方 Docker 部署说明](https://github.com/oceanbase/docker-images/blob/main/seekdb/README.md)。Docker 路线没有在本机执行。资料库必须实际执行 SQL；PowerContext 使用的文件 SQLite 只保存任务状态。

先在测试实例建立独立数据库，例如 `CREATE DATABASE minimax_sdd_demo DEFAULT CHARACTER SET utf8mb4;`。以下是占位配置，不包含真实密码：

```powershell
$env:MINIMAX_DB_HOST = '<seekdb-host>'
$env:MINIMAX_DB_PORT = '<sql-port>'
$env:MINIMAX_DB_USER = '<database-user>'
$env:MINIMAX_DB_PASSWORD = '<database-password>'
$env:MINIMAX_DB_DATABASE = '<test-database>'
```

主机与端口默认 `127.0.0.1:2881`；用户名、密码和数据库按自己的现有服务填写。不要将真实配置写入仓库。

## 完整使用步骤

命令输出 UTF-8 JSON，失败返回非零。资料导入只读取 manifest 中的实际文件；上下文只采用数据库查询结果，不从本地文件补造缺失正文。

```sh
python -m minimax_sdd init
python -m minimax_sdd import --project taskboard-demo --root . --manifest examples/import-v1.json
python -m minimax_sdd context --project taskboard-demo --task examples/task-v1.json
python -m minimax_sdd import --project taskboard-demo --root . --manifest examples/import-v2.json
python -m minimax_sdd context --project taskboard-demo --task examples/task-v2.json
python run_tests.py --implementation business/before --suite all
```

同一 logical key 的 v2 规格覆盖 v1。更新后再次用 `task-v1.json` 取上下文，应因旧来源要求失效而退出 2。固定业务测试在 before 上应退出 1：3 项目标行为失败、6 项回归通过。题目要求和数据见 [specs/v2.md](specs/v2.md)、[fixtures/tasks.json](fixtures/tasks.json) 与 [tests/test_taskboard.py](tests/test_taskboard.py)。

将自己的真实进度写成 `task_id/completed/pending/verification` JSON，结构可参考 [历史状态输入](evidence/task-state-input.json)。不要将历史测试结果当成本次运行结果。随后使用一个全新状态目录：

```sh
python -m minimax_sdd remember --task examples/task-v2.json --state-dir .state/run1 --record my-state.json
python -m minimax_sdd context --project taskboard-demo --task examples/task-v2.json --state-dir .state/run1
python -m minimax_sdd resume --task examples/task-v2.json --state-dir .state/run1
```

三个命令属于不同 OS 进程。`remember` 返回 PID、scope、citation；后续命令通过 PowerContext 的 `list/get` 恢复状态。`context.previous_task_state` 会包含真实恢复结果，pending 首项成为 `next_step`，SQL 资料正文仍来自 seekdb。新任务使用新的 project key 和状态目录即可，不需要删除已有数据。

## MiniMax 开发入口与已交付结果

`python -m minimax_sdd.develop` 执行显式的单次请求。先用无 Key 预检确认输入；当前 Git 版本用 `git rev-parse HEAD` 获取。下面的历史上下文是已标识的脱敏副本，适合离线核验；新的真实开发应使用自己刚从数据库生成的上下文。

```sh
python -B -m minimax_sdd.develop --root . --task examples/task-v2.json --context evidence/minimax/cn-dsh-20261103-run1/redacted-evidence/context.redacted.json --region cn --endpoint https://api.minimax.cn/v1/chat/completions --model MiniMax-M3.1-Flash --source-version <actual-git-head> --expected-before-sha256 482b90add2d94cf22df14b24302c818ccc003bc9a9bec8bc0d71fc9b39115062 --expected-tests-sha256 90a2d6dcebdbf00e6359aea493f116aa06b2081c4fd4f6006324ee2fd17f8abc --run-dir evidence/minimax/new-run --check-only
```

预检不读取 Key、不联网、不写 after；允许检查已交付的 after。真实调用需核实自己已有套餐的区域、模型与额度，安全配置专用进程变量 `MINIMAX_MPLAN_API_KEY`，移除 `--check-only` 并增加 `--confirm-mplan-entitlement-and-quota`。该参数是调用者的明确确认，不代替权益检查。程序不自动切模型、区域、Key 或重试，不保存凭据、私有 reasoning 或原始响应。

本候选已经包含真实模型产生的 [after](business/after/taskboard.py)。真实请求会在读取 Key 之前拒绝覆盖它；本次复核只需运行已交付代码的测试，无须再调用模型。

```sh
python run_tests.py --implementation business/after --suite all
python -m unittest discover -s tests -p test_develop_preflight.py -v
```

历史请求于 2026-11-03 使用中国区 `MiniMax-M3.1-Flash`，绑定当时源码 `b99c2e0a470cb92ddb5f0cc0a3161218e077b293`。新候选没有改写这一历史身份。before、固定测试、after 的 SHA-256 分别是 `482b90add2d94cf22df14b24302c818ccc003bc9a9bec8bc0d71fc9b39115062`、`90a2d6dcebdbf00e6359aea493f116aa06b2081c4fd4f6006324ee2fd17f8abc`、`6ff48b87ddf11e44bd62a980c1b9c12f128f30b3c7299d3f2c20a7d1358772ac`。同一组 9 项测试由 before 的 3 项目标失败、6 项回归通过，变为 after 的 9 项通过。

## 证据和验证边界

[证据索引](evidence/README.md)按官方六项要求列出记录；所有评审所需材料均在 `minimax/` 内。历史路径证据已制作明确标记的派生副本，原件未修改；[来源与双哈希清单](evidence/HISTORY_DERIVATIONS.json)区分原始与派生字节。各目录 `INDEX.json.files` 只核验当前交付字节。历史记录内保留的原始 hash、日期、PID 和 Git 版本属于原运行，不代表候选重新执行。

真实模型请求、最终代码和差异见 [模型记录](evidence/minimax/cn-dsh-20261103-run1/README.md)，同轮测试派生日志也位于该目录。原始 `context.json` 因含本机路径未交付；实际请求中的脱敏上下文与已交付 `context.redacted.json` 结构和值相同。

2026-11-03 的[隔离项目复核](evidence/isolated-repro-20261103/SUMMARY.json)验证了新状态目录和两个独立进程，但复用既有依赖，未执行真实 seekdb SQL。[离线环境摘要](evidence/offline-install-20261103/SUMMARY.json)记录 50 项锁定依赖、`pip check` 和业务前后测试；该轮未执行状态恢复或数据库整链。完整干净安装、真实 SQL、状态恢复与模型开发的同轮链路尚未完成，不能据此声明全部官方门槛通过。

Windows 受限执行上下文可能在 asyncio 的本地 socketpair 初始化处受阻。应保留具体失败和执行环境，区分环境故障与业务断言，不更改系统设置或用假状态代替实际恢复。

业务数据是合成 Taskboard 记录；资料检索使用符号与关键词 SQL，不宣称通用语义搜索。设计见 [design.md](docs/design.md)，一页结构说明见 [technical-note.md](docs/technical-note.md)，官方依据见 [MiniMax 赛题](https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/hc3pio/qlqnoryzrs7gtqbw)。本地材料和模式扫描均不是发布授权或官方成绩。
