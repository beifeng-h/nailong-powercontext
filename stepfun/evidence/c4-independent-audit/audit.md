# StepFun c4f99a1 只读审计

> 此文为历史审计的脱敏派生副本：审计脚本已重定位、两份历史报告含脱敏字段，原始哈希见 `../REDACTION_PROVENANCE.json`；一份历史检查日志未交付。不能用当前副本声称已完整重放当次审计。

指定提交 `c4f99a1a9c94da7111291f16cafc5eb30ff7c657`；本次 exact checks 实际 exit **0**。没有修改产品、运行测试/模型/数据库、读取浏览器报告/存储或调用任何 UI 控制。当次审计方法、逐项数值与边界的脱敏派生材料见 `audit.py`、`audit.json` 和 `RUN_RECEIPT.json`；原始内容和完整复跑范围不可由当前副本代替。

83 个该提交的 tracked 文件中，81 个磁盘原始字节直接等于 Git blob；`prepared-rrf.mjs`、`public/benchmark.mjs` 为 CRLF，只有归一化 CRLF→LF 后与 blob 精确相同。两份的 raw SHA、raw Git OID、LF SHA 与 canonical Git OID 分开保留，不能称全部 raw-byte 相同。当时还有未跟踪文档；不将当时整棵工作树称为 clean。既有19项纯回归的 receipt 源码 raw SHA 与当前文件相同，TAP 的19 pass/0 fail/0 skip可对照；本轮未重跑。

`main` 生产入口未注入 SDK 替身；bridge 的创建/加载 collection 均显式 `embeddingFunction:null`，模型清单固定 revision/384维/mean/normalize，写入和查询使用调用者经校验后的向量。benchmark 直接传 `query.query` 与当次 encoder 返回的查询向量；prepared 查询7值绑定保留两次原文及两次原向量 JSON，只有32hex collection ID可进入表标识。两路RANK、FTS1000/ANN50、cosine分数round至8位、FULL JOIN hidden PK、reciprocal rank求和和稳定排序均位于同一DB语句。结果解析仅转换类型/校验，不做客户端融合。

直接依赖 `seekdb` 与 `@seekdb/js-bindings` 的 package.json、lock 和已安装元数据均为1.4.0。原生运行时URL固定469a55dc…；SQL结构参考源0e49209e…是另一个组件标识，不混称同一commit。worker调用真实Transformers feature-extraction encoder；回退也是重新执行模型，没有在本轮审查的应用源代码中发现手写或伪向量替代。

## 指定 API 日志

`bridge-api-events-1793494763413.jsonl` 快照为240行：120 start及120 complete，一一同KB/revision配对；只含父线程正常只读DOM所给这四KB。所有完成记录均revision1、count5、transport embedded，SQL/完整7参数包的SHA256字段均为有效64hex；每KB一个statement hash、10个parameter hash各出现3次。

|父线程DOM提供的模式映射|KB|完成记录|
|---|---|---:|
|fp32-gpu|84564b7d-dcbc-4f11-8395-3a48c35a4d9f|30|
|fp16-gpu|60f59a02-65dc-482a-9cce-410fa47fac41|30|
|fp32-wasm|49241595-e41f-4b38-9f5f-703edfc50bfb|30|
|q8-wasm|47758c27-2fde-4350-ab3c-bbf7dda03f1b|30|

全部240事件落在父线程给出的run `77153f14-da1b-4e20-b6b9-d5d033b1c4f5` 时间窗内，最后一条为 `2026-11-01T01:04:52.861Z`。日志raw SHA256为 `c6518fe0e43b98a5e2ce6f92fede8d6143d1c61da172811676d6dfae4d64c538`，当次临时目录曾保留其原样快照；当前候选另提供与原始哈希一致的240事件副本。

## 资源与冻结数据

12个现存资源的实际字节数及SHA逐项等于已提交的 acquisition receipt（4 runtime、5公共配置/tokenizer、3 ONNX）。固定Transformers.js3.8.1、ORT Web1.22.0-dev.20250409-89f8206ba4、Xenova/all-MiniLM-L6-v2 revision751bff37182d3f1213fa05d7196b954e230abad9。三个模型含公共文件总大小分别91,331,916 /46,242,135 /23,916,680 B，runtime22,540,034 B，与 measured receipt一致。收据的not-runtime-tested标记是资源收集时的边界，不将它改写成后续运行验收。

corpus/queries/mutations三文件的实际SHA均等于旧 `ROOT_REVIEW.json` 冻结值。依当前benchmark相同Q01–Q10/H01–H20顺序展开200对binary qrels，SHA为 `a6daf86d05c60688ee8c6cda29b5d5e7e76845cbaefd3b3e0fcd3c72c397d894`，供父线程与正常DOM manifest核对。标签是AI协助的合成开发集，不是official/human gold。

## 证据边界

- 这是public-SDK API完成事件，发生在execute返回且结果解析成功后；不是网络wiretrace或引擎执行计划。日志没有queryID/原文/向量内容，不能独立重算参数hash或从摘要推断各查询内容；collection ID也未记录，无法在这里逐KB重生成statement hash。
- 模式↔KB映射和run时间窗由父线程正常只读DOM转述，本审计没有自行读取。日志不含推理backend/dtype；不能据此推断GPU实际内部精度，也不把约两秒的双rAF边界当已校准前台端到端性能。
- 当前源码/资源绑定和事件时间相容，但日志没有进程加载模块时的密码学版本证明；start前发生的HTTP错误也不在这些事件的覆盖内。
- 本轮验证了资源原始文件/收据及依赖版本元数据，未重新下载npm包、逐字审计全部node_modules/native DLL，未做ONNX initializer类型检查（父线程独立负责）。已审查的应用源中未见替代算法，不将该结论扩大为实际GPU kernel精度证明。
