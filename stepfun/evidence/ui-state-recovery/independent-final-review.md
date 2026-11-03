# app.mjs 实际diff最终窄复核

绑定app raw SHA256 `502963ad62d224218d58e77121c9802b98f6b19c5878cd43822be5af07fd03e9`。本轮只读实际HEAD diff及相关上下文；client/worker相对HEAD diff为空。未运行任何测试、UI、DB或Worker。

未发现新的确定问题。实现符合已收敛设计：

- ready先保存previousModel、再更新activeModel，仅此前为空或precision改变才showBases；普通同精度非fatal fallback保留现有token，failed后恢复ready会补回兼容选项且不复活旧token（app9–11）。
- failed先清activeModel、标backend未就绪，再showBases清选择/结果/耗时（16–20）。
- clearSearchView只递增app自己的generation并清results/timing；没有使用status.generation，也没有改动EmbeddingClient生命周期（63–70）。
- search仍先await ensureModel，然后快照selectedKB并生成token；返回结果前仍同时核token与当前KB（143–149）。初始化中的ready/loadModel列表重建都在该token之前结束。
- mode/KB事件复用helper；showBases每次重建时清理视图。新建KB后的额外generation++虽冗余，仍单调递增且发生在受busy锁保护的同一动作中，不构成确定回归。

根线程报告的离线红绿/5例UI-state与19例纯回归结果属于另存证据，本复核没有重跑或把它们扩大为真实浏览器自动降级/UI验收。修复与client/worker/DB策略分离，未要求进一步重构。
