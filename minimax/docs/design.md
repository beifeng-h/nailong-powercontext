# MiniMax SDD 上下文模块设计

官方依据为 [MiniMax 题面](https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/hc3pio/qlqnoryzrs7gtqbw)。本候选从生态基线 `d647275c308e09b7b623f322a26f5c4e85734fb0` 独立整理，仅新增 `minimax/` 资产。历史真实模型调用来自 `b99c2e0a470cb92ddb5f0cc0a3161218e077b293`；这不是当前候选已经重新调用模型的声明。

## 范围与数据流

采用 Python CLI 完成一个局部业务修改。seekdb/OceanBase 保存规格、代码和测试，并通过参数化 SQL 返回任务资料；PowerContext 的文件 SQLite 保存进度并供新进程恢复；MiniMax 根据实际资料和恢复状态生成业务实现。资料库与状态库职责分别清楚，不用 SQLite 替代规定的资料库。

资料表按 `(project_id, logical_key)` 唯一定位当前文档，保存 kind、source_path、revision、content_sha256 和正文。同 key 重导入用实际 v2 来源覆盖 v1。查询转义 LIKE 特殊字符，context 校验任务所需的规格、代码、测试和来源版本。缺少或过时来源明确失败，不从本地文件兜底冒充 SQL 返回。

## 业务样例与固定验证

Taskboard 的 `list_tasks(tasks, state=None)` 从 v1 精确匹配演进为对筛选参数执行 `strip().casefold()`。`None` 返回全部、未知值返回空、原顺序与输入内容保持原行为。规格明确包含自定义 strasse 标签与 Straße 查询。同一测试文件共 9 项，含 3 项新增目标行为与 6 项回归；before 的红灯来自功能断言。

after 来自已记录的一次真实 MiniMax 输出。模型仅修改业务实现，不改规格、固定测试或数据。保留实际请求、来源版本、响应 id/model/usage、最终代码和应用差异；不保存授权头、凭据或私有 reasoning。测试及输入身份由 SHA-256 绑定。

## 进度保存与使用

PowerContext 固定公开源码 `dab240063bfcfa7917898dc44da4baadb3747bd0`，使用 Builtin runtime、文件 SQLite、scope 幂等键和显式 memory remember/list/get。关闭 dream，生成与 embedding 模型均为空。

`remember` 将真实 completed、pending、verification 写入新状态目录；进程退出后，新进程恢复同一 scope 的 citation 内容，pending 首项成为下一步输入，并可合入新的实际 SQL 上下文。历史证据保存 PID、命令、退出码、版本与 citation，不能用静态 fixture 冒充恢复。

## 验证范围与交付

已保存真实 SourceDB v1/v2 入库、查询、更新和旧要求拒绝，固定 SDK 的跨进程恢复，以及 SQL 与恢复状态组合的 CLI 历史输出；另有真实 MiniMax 调用与同轮 before/after 测试，3 项目标行为由失败转为通过，6 项回归继续通过。相关来源与双哈希见 [证据索引](../evidence/README.md)。

另一次隔离项目复核采用新状态目录及两个进程，但复用了既有依赖且没有真实 SQL。新离线环境验证了锁定依赖、`pip check` 和业务测试，没有完成数据库与状态恢复组合流程。最终候选的完整干净环境整链与官方固定提交评测仍待验证。

全部代码、锁定依赖、占位配置、初始化步骤、样例来源、前后实现、可见模型差异与技术记录位于 `minimax/`。13 个含本机路径的历史文件已变为明确标记的派生副本，原件保留不变；嵌入的旧 hash 仍指向原始历史字节，各 INDEX 只核验实际交付字节。原始模型上下文未交付，改用实际请求中使用的脱敏上下文。模式扫描只覆盖其定义的形式，不证明没有所有敏感内容，也不是发布授权。
