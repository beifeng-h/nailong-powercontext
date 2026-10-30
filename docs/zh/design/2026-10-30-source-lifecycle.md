# 来源可用性与原生记忆状态

Runtime 的 `lifecycle.for_scope()` 注册固定的来源依赖 DAG。图、Source 生命周期版本与最后事件保存在同一数据库的新表 `pc_source_lifecycle_graphs`，每个 scope 独立；正文及历史 citation 不写入新版本。注册父节点须先存在，从构建过程拒绝环；重复注册保留原绑定，冲突注册失败。

事件字段严格验证类型，序号递增，同一事件可重放。Source 状态先作为持久意图保存，再按各节点 all/any 规则计算后代资格：Memory 用原生 forget/reactivate，Topic 用可逆 governance active/deprecated。Topic 搜索及浏览过滤非活跃资格，精确历史读取保持原行为。状态写入失败可用同一事件重试，已完成的状态不再写修订；新注册派生节点立即与父节点状态同步。

`generation` 拒绝不可用节点，`audit` 返回注册时的原始引用。Memory 资格更新不改变正文版本，恢复后仍返回原引用。单写者 scope 沿用 Runtime 锁，既有 SQLite 与 Topic 持久化组件保持复用；新表只保存依赖和事件，不缓存答案。

固定依赖云端环境的 4 项公开测试及生命周期补充测试通过，覆盖多层图、真实 Memory 数据库提交故障后的重启重放、成功重放幂等、scope 隔离与严格事件字段。
