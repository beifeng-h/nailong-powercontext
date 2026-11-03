# 阶跃浏览器本地知识库设计

> 历史设计记录（2026-10-31），保留当时方案，不代表当前实现或验收状态。当前版本以[README](../README.md)、[技术说明](technical-note.md)和[自动回退证据](../evidence/automatic-wasm-20261102/README.md)为准。

依据2026-10-31通过正常Edge完整读取的[官方题面](https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/hc3pio/kw9wfx4bu9pyvat9)，原文规范化存档在工作区 `artifacts/project-continuation-20261031/stepfun-official-readonly/`。官方生态起点为d647275c308e09b7b623f322a26f5c4e85734fb0；本隔离分支从b99c2e0a470cb92ddb5f0cc0a3161218e077b293开始，保留高德获分实现及MiniMax准备成果。当时处于设计阶段，尚无阶跃实测结果；本文件不记录后续验收，正式分数以平台为准。

## 最小结构

选择原生HTML/JavaScript界面、独立浏览器Worker、Node内置HTTP服务器和seekdb-js。界面与本地API同源，只监听127.0.0.1；Node只做存储和查询，不做任何embedding或云模型调用。浏览器计算文档及查询向量，短暂保留推理/传输数据；最终原文、向量、元数据、知识库登记均在独立seekdb数据库，不能由浏览器内存检索替代。

不增加React、Python桥或完整Agent框架。浏览器直接加载固定Transformers.js的官方web bundle和配套WASM文件，减少构建与版本组合。

## 固定模型和端侧后端

模型为Apache2.0的 `Xenova/all-MiniLM-L6-v2`，固定revision `751bff37182d3f1213fa05d7196b954e230abad9`，384维、mean pooling、normalize。选同一模型的FP32基线、FP16和q8文件。实际字节、哈希、共享tokenizer/config总体积须由下载脚本记录；元数据大小不能冒充本次下载测量。

运行时固定 `@huggingface/transformers@3.8.1`。默认显式请求WebGPU+FP16；缺GPU、缺必要特性或初始化/推理失败时终止原Worker，创建独立WASM+q8 Worker并提示当前后端。重新创建Worker避免共享失败session缓存影响降级。模型仅从含固定revision的本地静态目录加载，禁remote model；WASM路径也指向本地固定vendor资源。

提供明确的FP32、FP16 WebGPU与q8 WASM实验模式，记录请求和实际后端，不能把手动WASM模式称为真实GPU不可用环境。若本机无法完成某种环境验证，记录未执行原因，不改变浏览器安全设置或伪造结果。

## 数据层和状态

使用官方 `seekdb@1.3.0`、server模式、独立数据库 `stepfun_kb_demo`。创建和重开集合都显式 `embeddingFunction:null`，schema同时开启向量与全文索引。浏览器必须传入有限、非零、384维向量。批量写入前检查ID唯一、数组长度、文本和请求大小；SDK upsert不承诺批次原子性，失败必须如实返回。

实际混合检索只调用 `collection.hybridSearch`，由 `DBMS_HYBRID_SEARCH.GET_SQL` 及数据库执行产生RRF次序。Node与浏览器都不分别拼合两路候选。共享连接上的整次SDK操作串行，避免 `@search_parm` 跨await交错。

每个知识库及精度profile对应独立collection，登记模型repo/revision/dimension/pooling/normalize/precision等指纹，防止混入不同向量空间。切库后重开集合，界面以知识库ID和请求编号排除旧响应。写入后调用真实refresh，并实测新增、覆盖与切库结果；不把refresh promise成功当作所有索引可见性的证明。

## 实际验证计划

1. 独立seekdb数据库真实建表，保存版本、schema/index及一次数据库内混合SQL证据；先不声称本机hybrid兼容已通过。
2. 浏览器实际导入文本、端侧生成向量、写库、检索并展示对应原文；记录网络和后端，不能回放预计算向量。
3. 新增、重复覆盖、刷新、切库及重启Node后重开，验证结果和当前知识库一致。
4. 使用同设备/浏览器/固定自建语料及完整相关性标注，分别测FP32与量化质量：Recall@K为相关文档交集数/全部相关数，另报告nDCG@K。标注为AI辅助合成开发样例并由root复核，非官方gold或真人用户实验。
5. 同口径测实际模型文件总字节、压缩比；逐阶段记录下载/加载、文档embedding、写入/刷新、查询embedding、seekdb检索、端到端延迟。冷启动与预热分开，保留全部原始重复样本和中位数。
6. 单独比较batch1与批处理，其他条件一致；质量下降或未测项目如实记录。不承诺未测的加速。

最终交付在 `stepfun/`：可本地启动应用、源码和锁定依赖、模型获取/量化方法、数据库结构和配置、测试语料/查询/相关性标注、实际日志及一页技术说明。正式提交仍服从主任务排序，不因准备完成自动提测。
