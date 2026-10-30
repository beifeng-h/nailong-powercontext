# 上下文完整包与增量重建

`powercontext.builtin.runtime.context_pack` 定义不可变的 `ContextPack`、`ContextPackDelta` 和 `ContextPackError`。完整包从 UTF-8 有效分块构造，分块顺序和字节不变；正文按确定性的字符边界分块，默认每块不超过 512 bytes。

wire 使用固定 schema、严格字段集合、标准 Base64 和排序 key 的紧凑 UTF-8 JSON。完整包摘要覆盖仅含 schema 与 items 的规范 JSON。`byte_count` 通过固定点计算包含自身字段的实际 wire 长度；delta 字节数仅作为属性，不增加 wire 字段。解码拒绝重复、缺失或额外字段、错误 Base64、无效 UTF-8、摘要或字节数不符。

delta 复用完整包之间的最大公共分块前缀，并携带目标后缀及 base/target 摘要。应用 delta 前验证 base、自身 prefix 范围和重建后的目标摘要；接收方只需要独立解码的 base 与 delta，不依赖发送端缓存。空正文对应空分块完整包，首部、中部、尾部变化均通过替换相应后缀重建。

`ScopedContextApplication.prepare_incremental` 先调用普通 `prepare`，不改变正文或引用。首次返回完整包，已有 base 时返回 delta。Memory revision 或早部引用变化会缩短可复用前缀；实现不通过改写普通输出回避这项成本。

固定依赖云端环境的 14 项公开测试及协议补充测试通过，覆盖实际 Runtime 接入、Unicode 分块、序列化后重建、独立摘要 oracle 和非法 prefix。本机诊断中，10,000 bytes 相同正文的后续 delta 为 257 bytes，该数值只描述相同轮次，不代表真实 40 轮成本验收。正式 45% 净传输节省仍须平台核验；真实成本包含首次完整包、Base64、JSON 和摘要开销。
