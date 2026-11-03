# 浏览器本地知识库

文档和问题在浏览器 Worker 中生成向量，原文、向量、元数据和知识库状态由本地 seekdb 保存。全文与向量的 RRF 排序由一条数据库内查询完成。模型和依赖均固定版本，未调用云推理。

## 启动

需要 Node.js20以上、Python3标准库。本次实际环境为 Windows x64、Node24.22.1、SDK及官方原生绑定1.4.0；其他操作系统尚未独立验收。

在 `stepfun/` 运行：

```sh
npm ci
python tools/fetch_resources.py --include-optional-text
python tools/fetch_resources.py --include-optional-text --execute
npm test
npm run test:ui-state
npm run test:report-export
npm start
```

第一条Python命令只显示下载计划；`--execute` 下载固定官方NPM/HuggingFace资源并校验哈希。首次启动还会按固定官方build获取当前平台的seekdb原生包，保存在本项目 `runtime/native-bindings/`；Windows1.4包已实际加载验证。资源备妥后推理从本地文件加载。不要以 `file://` 打开网页。

打开 <http://127.0.0.1:34021/>。默认自动打开项目内独立进程内库 `runtime/embedded-db-v1.4/`，不需要数据库账号、另开server或SQL网络端口。HTTP只监听127.0.0.1；`/api/health`显示实际连接状态。退出应用前保存页面实验记录；数据库在原目录持久化，勿让多个应用进程同时打开该目录。

需要并行运行独立副本时，可在启动前将环境变量 `STEPFUN_HTTP_PORT` 设置为 1–65535 的整数，例如 `34022`，并通过对应端口访问。未设置时仍为 `34021`；服务始终只监听 `127.0.0.1`。不同进程必须使用不同的项目目录和嵌入式数据库目录，不能同时打开同一数据库。

如使用自己已部署且仅本机可达的server，可设置 `STEPFUN_DB_MODE=server`，并用 `STEPFUN_DB_PORT`（默认36143）、`STEPFUN_DB_USER`（默认root）和 `STEPFUN_DB_PASSWORD`（默认空）提供进程局部配置。不要把实际密码提交到仓库。旧Windows standalone实验库与默认进程内目录分开，不自动迁移数据。

## 使用和比较

选择推理模式并加载模型，再新建或选择对应精度知识库。粘贴或导入UTF-8文本，等待向量化、写入和索引刷新完成后查询。同ID导入用于更新正文和向量；不同精度知识库分别保存。界面显示实际后端、导入进度、检索原文和阶段耗时。

<http://127.0.0.1:34021/benchmark.html> 对比FP32/FP16 WebGPU与FP32/INT8 WASM。每模式新建知识库，执行完整20文档/10查询、每条3轮，以及batch1/4各3轮。保持页面前台并避免并行推理。重复运行会留下新知识库，当前没有自动清理接口。

比较完成后，点击“导出原始 JSON”保存本次完整记录。部分失败的比较也可导出；文件名包含 runId，导出不会重新执行模型或查询。请核对浏览器下载列表，页面提示“已发起下载”不代表文件已经保存。未导出前请勿刷新或关闭页面。

质量标签是检索前复核的AI辅助合成开发集，非官方gold或真人标注；每条问题有两篇完整相关文档，200个二值相关对全部纳入。源数据见 `fixtures/development-set/`、`fixtures/ROOT_REVIEW.md`。增量/切库样例另测，不混入固定质量集。

完整实验记录在页面中展示，未自动下载或上传；未导出前刷新会丢失本页记录。首次仅指新Worker/session，未清除HTTP、模型或设备缓存。分别记录结果ready与原文DOM更新后两个前台帧机会的延迟，不能称物理屏幕呈现时刻。实际测量与尚未覆盖的项目见[一页技术说明](docs/technical-note.md)。

## 实现和验证入口

- `public/embedding-worker.js`：本地模型、显式WebGPU和WASM推理。
- `public/embedding-client.mjs`：Worker生命周期及失败时完整重算的自动降级。
- `bridge.mjs`、`prepared-rrf.mjs`：公开SDK、数据库状态、全参数绑定的一条RRF查询。
- `native-hybrid.mjs`：严格结果/ID编码校验及供应商缺陷的历史诊断工具支持；实际检索不走有引号缺陷的SEARCH生成器。
- `evidence/`：实际依赖获取、只读协议诊断与回归结果，须按各自范围解释。

四模式开发集实测见下表。浏览器新增、同ID更新、切库和页面重载已另行真实验证；无GPU适配器时的自动WASM降级及单文档查询，以及数据库进程重启后的恢复，均为历史版本的真实验证，本次候选尚未复验这两项。前台计时校准仍待验收。没有正式平台得分结论。

## 独立候选实测

2026-11-03 14:13–14:17 UTC，独立候选源码提交 `a67ba18b886320b00b8ef13641f90f3c1cfd60b7` 使用新嵌入库，在 Edge 156 完成四模式比较；每模式 30 次查询、2 次预热，固定合成开发集 Recall@5 和 nDCG@5 均为 1.000。完整[原始报告](evidence/browser-run-41a5bb18/BENCHMARK.json)包含各轮阶段耗时和排名，结果与范围详见[技术说明](docs/technical-note.md)。报告本身不含提交号；版本绑定基于独立启动与进程记录。本次应用实际使用的设备与后端由报告记录，结果不代表官方评分。

同一候选的真实浏览器自动模式使用 WebGPU/FP16：在独立空库导入两篇文档，同 ID 更新后查到新正文；切至另一库后未混入首库数据，切回并重载页面后仍能查到更新内容。[重载后的原始导出](evidence/browser-run-41a5bb18/AFTER_RELOAD.json)只记录重载后的加载和查询；此前导入和切库由单独的界面观察记录支持，不能把该导出称为此前操作的原始日志。这里的重载为页面重载，不是应用进程重启；本次未验证自动 WASM 降级。比较中的两种 WASM 模式为显式选择，不能作为自动降级证据。

## 先前四模式原始记录

2026-11-03 的先前实际运行 `84b3efd7-396f-4d2b-814b-e368f1d4b068` 绑定源码提交 `f11ab8b26bb740a98af9adac398dafbadcda74f8`，四模式均有效、各 30 次查询及 2 次预热；完整原始记录及阶段样本见 [BENCHMARK.json](evidence/browser-run-84b3efd7/BENCHMARK.json)。它与上面的独立候选运行是两次实验，不能混为同一次。以下历史实验保留原有证据边界。

## 已完成的开发验证

功能版本 `c4f99a1a9c94da7111291f16cafc5eb30ff7c657`，运行 `77153f14-da1b-4e20-b6b9-d5d033b1c4f5`，2026-11-01 01:00:30–01:04:54 UTC。Edge 156 / Windows，WebGPU 报告 Intel gen-12lp、支持 shader-f16。每模式20篇文档、10个完整问题各3轮，共120次；所有模式的开发集 Recall@5、nDCG@5 均为1.0。该小型合成集只用于开发，不能据此推断官方结果或通用质量。

| 模式 | Worker报告的后端/精度 | 后续20次查询 ready 中位数 | batch4 墙钟加速比 T_batch1/T_batch4 |
|---|---|---:|---:|
| FP32 GPU | webgpu / fp32 | 27.05 ms | 2.147× |
| FP16 GPU | webgpu / fp16 | 27.45 ms | 2.793× |
| FP32 WASM | wasm / fp32 | 39.40 ms | 1.018× |
| q8 WASM | wasm / q8 | 30.40 ms | 0.967× |

ready 指查询向量生成和本地检索返回，不含模型初始化、语料向量生成或写入。batch加速比为batch1和batch4墙钟中位数之商，来自20篇文档、各3次，不代表端到端导入加速。FP16未带来查询提速，q8的batch4也没有提速。DOM更新加两帧的样本约2秒，物理前台尚未校准，不作为可见交互延迟结论；没有清空模型/HTTP缓存，不作为全冷启动成绩。

完整浏览器报告当时保留在测试页，尚未保存为独立原始文件，本轮没有恢复原页；`evidence/browser-run-77153f14/` 保存的是240条SDK API事件及绑定说明，不是浏览器完整原始报告、网络抓包或GPU内核精度证明。ONNX顶层initializer类型另有 `evidence/model-precision/` 的只读检查；q8图含INT8/UINT8权重和FP32数据，不能称所有运算均为INT8。

`evidence/api-state-protocol/` 的独立测试库检查已通过：20→21篇新增、同ID更新后仍21篇、两库隔离和新客户端进程读回。该检查使用明确标记的Node合成向量，只证明协议状态与正文可见性，不是浏览器embedding、UI切库、服务重启或崩溃恢复验证。不要在正常语义实验中选择 `TEST_ONLY_PROTOCOL_SYNTHETIC_` 开头的库。

界面状态另修正了程序化切库后的旧结果残留、失败后模型仍被误认作就绪两处缺陷。`test:ui-state` 的5例使用VM DOM/Worker/API替身，保留真实app/client代码和禁止外部请求；它们验证状态与回调顺序，不能当作真实WebGPU/WASM执行或浏览器交互验收。2026-11-01 的 c4 历史四模式实验未因这项界面修正重跑；上文 2026-11-03 的 f11 实验是另一次真实运行。

2026-11-01 14:50–14:56 UTC另对功能版本`bfa6126106e58ef242af2e3340c8630bddaa3c1d`完成真实Edge页面验收，自动模式报告WebGPU/FP16，共11次新查询：20篇样例导入后新增H21可检索；同ID H05替换后返回11天新正文；Harbor/Beacon切换先清空旧结果，再分别返回各库正文；只刷新测试页面并重新加载模型后，H21、更新H05及Beacon两篇仍可读出。没有重新导入，也没有重启数据库进程。截图、输入哈希和具体边界见[浏览器状态验收](evidence/browser-ui-state-20261101/REPORT.md)。本轮没有证明总行数、唯一H05存储行数或revision2元数据。

2026-11-02 09:30–09:34 UTC，在保留localhost白名单、禁用远端模型的隔离headless Edge中，Worker实际返回无WebGPU适配器，自动模式随后使用WASM/q8。新q8知识库完成一条文档的真实向量化、写入、刷新，查询返回正确的`WASM01`及原文。修复了module Worker首消息就绪时序及blob Worker内本地相对URL解析问题，并为启动与请求设置等待上限。源码预后哈希、原界面事件和截图见[自动回退验证](evidence/automatic-wasm-20261102/README.md)。这是一条文档/一次查询的功能验收；原导出文件因CLI socket超时尚未取得，保留的是DOM、截图及源码哈希，没有新增质量或性能比较结论。

候选材料中的历史记录已作明确标注的隐私脱敏，原始与派生哈希见 `evidence/REDACTION_PROVENANCE.json`。八张截图已逐张目视检查，范围和局限见 `evidence/IMAGE_VISUAL_REVIEW_20261103.json`；该检查不构成公开发布批准。
