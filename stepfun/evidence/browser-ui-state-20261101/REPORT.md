# 真实浏览器状态验收

2026-11-01 14:50–14:56 UTC，正常Edge浏览器、本地应用`http://127.0.0.1:34021/`。功能代码为`bfa6126106e58ef242af2e3340c8630bddaa3c1d`；实际SDK1.4.0、引擎`5.7.25-OceanBase seekdb-v1.4.0.0`、进程内数据库。应用复用既有资源及数据库，未下载资源或重置数据。只操作两个新建且明确标注TEST_ONLY的开发知识库，未修改其他库。

自动模式中，真实浏览器Worker报告`WEBGPU · FP16`。操作通过正常界面完成，输入来自既有`fixtures/development-set/STATE_SCENARIOS.json`及初始/变更语料，不是服务器预计算向量或结果回放。本轮共11次新查询，没有重跑四模式120查询实验。

| 操作 | 实际观察 |
|---|---|
| 导入20篇初始Harbor样例，再新增H21 | 明确刷新成功后，原先未返回H21的问题以H21为第一条，正文含east lobby与cobaltmesa418 |
| 同ID更新H05 | 更新前返回seven calendar days；刷新后第一条H05正文为eleven calendar days并含ledgermint604，见01截图 |
| Harbor→Beacon→Harbor | 切库立即清空结果和耗时，见02；同一问题在Beacon只显示B01/B02及23天政策，见03，切回Harbor返回11天新正文；H21仍可检索，见04 |
| 仅重载自己的测试页面，重新加载模型 | 两个测试库重新出现，无重新导入；H05新正文、H21、Beacon B01/B02分别读回，见05、06、07 |

测试库ID：Harbor为`c3f99cab-6473-478b-93a4-b7d39b163f40`，Beacon为`71278345-a316-4599-9b4f-92a763dde5e0`。截图及其字节SHA256见同目录`SCREENSHOT_SHA256.txt`。

输入SHA256：

- `documents.initial.jsonl`：`0038906009f362ac5e92f2b8f72e9d5c2e45916df90a9f3bbf46df60d2937384`
- `documents.mutations.jsonl`：`72c3bac54e63b4f80f163cd0c327ad3bd6ae6db9a6f19fe86e5cfb4b0d54a066`
- `public/fixtures/corpus.json`：`a8c6c7bbe74dba8535009a5d8151ef9ab186856b55a164474d8db49cb9891793`

边界：同一Node进程保持运行，页面重载读回不等于数据库进程重启恢复；UI未显示总行数或唯一H05行数，typed-text入口没有设置revision2元数据，所以不作这些断言。WebGPU当前可用，未伪装其不可用、未修改浏览器图形/安全设置；唯一现有正常浏览器为Edge，IAB不可用，截至该次 2026-11-01 验收，真实自动WASM降级仍待测试；2026-11-02 的独立后续验收见自动回退证据。单次页面计时不是校准后的性能统计。

本轮未点击导出、下载应用JSON、读取或刷新旧c4报告，也未通过其他端点保存旧导出。没有正式平台得分结论。
