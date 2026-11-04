# 一页技术说明

模块以 `python -m minimax_sdd` 处理 Taskboard 局部演进：筛选参数去除首尾空白并执行 Unicode casefold；其余行为由固定回归测试约束。

```mermaid
flowchart LR
    F[规格/代码/测试] --> I[import]
    I --> D[(seekdb 资料库)]
    D --> Q[参数化 SQL]
    Q --> C[带来源与哈希的上下文]
    P[(PowerContext 状态)] --> R[新进程 list/get]
    R --> C
    C --> M[MiniMax 修改业务实现]
    M --> V[固定目标与回归测试]
    V --> P
```

seekdb 按 project/logical key 保存资料和内容哈希；v2 覆盖同一规格，过时或缺失的必要来源明确失败。上下文只使用实际 SQL 返回的正文。PowerContext 使用固定源码 `dab240063bfcfa7917898dc44da4baadb3747bd0` 的 Builtin runtime 和文件 SQLite；关闭 dream 与模型配置，恢复真实进度和 citation，pending 首项成为下一步输入。

2026-11-03 一次真实中国区 `MiniMax-M3.1-Flash` 请求绑定源码 `b99c2e0a470cb92ddb5f0cc0a3161218e077b293`，根据实际 SQL 资料和恢复状态生成 after。请求、响应元信息、可见输出和应用差异保留；固定测试未改，9 项中 before 为 3 项目标失败、6 项回归通过，after 为 9 项通过。该历史调用身份没有改写为新候选版本。

真实 SQL 更新、旧要求拒绝、两个进程状态恢复及组合 CLI 记录见 [证据索引](../evidence/README.md)，模型与同轮测试见 [调用记录](../evidence/minimax/cn-dsh-20261103-run1/README.md)。13 个含路径历史文件为明确标记的脱敏派生件；原件与派生双哈希分开，原始模型上下文不交付。

2026-11-04 本候选在独立离线 venv 中通过业务前后测试、6项入口回归、无Key预检，并完成[真实SQL与状态组合](../evidence/sql-composition-20261104/README.md)：v1/v2更新、旧要求拒绝及3进程状态使用共9个CLI阶段、10项组合检查通过。使用本轮独立命名空间和全新任务状态；没有新模型请求。另一台机器的重新安装及官方评测尚未执行。
