# 按查询和完整预算选择 Memory 原文

`PrepareContextRequest.evidence_selection` 默认关闭。关闭时 `PreparedContextBuilder` 沿用普通组装路径；开启时只处理已召回的 Memory 候选，并通过 `PreparedContextBuild.fragments` 返回原文片段。

选择器在候选正文中识别句子及有界文本段，使用当前 query 的词项、词频和相邻词匹配计算相关度。先选择可装入预算的相关证据，再补充邻接上下文。相邻已选段合并为连续原文区间，减少重复 citation 开销；相距较远的证据保留为多个片段，不复制中间无关正文。

每个片段持有包含 scope 的 `MemoryEntryAddress`、半开 Python 字符坐标和该区间的原文；同文不同 scope 的身份分别保留。去重依据完整 scope、Memory revision、entry 和 entry version 身份，不以正文相同为由混用引用。`origins` 与片段按顺序逐项对应。

渲染保留既有 trust policy 和 prepared-context envelope。每项 JSON 包含原始 citation、content、start、end，正文通过 JSON 转义但不改写。每次装入都测量完整渲染的 UTF-8 字节，包括 policy、标记、JSON、引用及正文。无法装入任何片段时返回合法空 Context。

实现只读取 query、候选正文及引用，不读取相关性标签、证据区间、外部模型或在线服务，也不编码固定问题。补充测试覆盖文档后部与远距离双证据、同文跨 scope、Unicode/转义后的完整预算和默认关闭兼容。

固定依赖云端环境的 3 项公开测试及证据补充测试通过，覆盖实际 Runtime 接入、查询切换、远距离双片段、Unicode 和转义后预算及 scope 身份。正式 evidence token recall、完整证据覆盖比例仍须平台核验。
