# KB选择/模型失败视图清理：窄设计复核

按根线程收敛后的策略，未发现确定冲突；这是设计审查，不是后续实现或浏览器验收。只读了app/client源码，未改产品，未运行UI/DB/Worker/测试。

必须保留的顺序和边界：

1. `clearSearchView()`只负责app自己的generation单调递增、清results和search-timing。不要采用回调的`status.generation`覆盖它，也不要在此close/reload client；UI token与EmbeddingClient Worker generation是不同作用域。
2. search保持现有顺序：先`await ensureModel()`，再取得selectedKB和新token。初始化成功/列表重建造成的generation变化须先结束，不能把token提前到ensureModel之前。
3. failed使activeModel、选择与视图失效；ready只在原activeModel为空或precision改变时重建兼容列表，不复活旧token。EmbeddingClient fatal会先failed、随后同一次embed仍可能fallback ready，这条边界必须覆盖。
4. 普通同precision、非fatal fallback不会先failed，ready不应重建列表；否则showBases的generation递增会吞掉本来有效的search响应。根线程已明确采用条件ready，因此此冲突已处理。
5. showBases只保留仍兼容的原选择；清理helper不应顺带重写selector、activeModel或client状态。程序化选择不依赖浏览器自动发出change事件，列表重建本身调用helper即可。

已收敛方案允许failed后的旧查询token继续失效，即使模型后来恢复也不让旧结果重现；下一次用户选择/查询使用新token。该语义与“failed使旧选择/视图失效”一致。

没有要求扩展状态机、重构client/worker/DB、增加新的恢复策略或扩大其他UI缺陷范围。最终实现仍由根线程按离线时序用例验证；本审查不据此声明真实自动降级/UI流程已验收。
