# StepFun 接口状态与文档追加审查

本轮只读文件核对实际 exit **0**，没有执行 state-probe、测试、数据库、模型或 UI，也没有重跑240事件/12资源检查。可复核检查和输入文件 SHA 见 `checks.py`、`audit.json`。

`RUN.json` 自洽：15个顺序请求=health1+registry1+新建2+import4+search7。两个UUID均是本run的 TEST_ONLY 库，与原四模式质量实验库不相交；记录中的写请求只有两次创建及对这两库的四次导入。绑定driver先收集既存ID，创建后拒绝既存/重复UUID，写操作受本次owned+createdThisRun限制，无自动重试或删除。

原import返回count/revision依次为 Harbor20/1→21/2→21/3、Beacon2/1，与文档ID集合upsert算术一致。同ID H05替换未增加计数；H21导入前缺席、之后出现；记录的H05/H21/B01正文与固定protocol fixture逐字一致。driver在实际运行中还断言所有返回正文、metadata revision、testOnly、vectorOrigin、runId；这些完整原始metadata载荷没有保存在收据中，本轮不能独立重新验证未序列化的载荷。

`REOPEN.json` 自洽：原客户端PID288788，新客户端288188，previousProcessId相符，六请求=health1+registry1+只读search4，零创建/导入，写意图全部false。服务PID另由BINDING报告为291436；这不是服务或数据库重启。正文、所选KB及KB revision3/1可读回；`freshCountAfterReopen=null`，21/2只是原import历史计数，不能用top-K长度当重开后新计数。

合成one-hot向量和API q8清单只用于状态协议；收据和两份文档都明确不把它们视为浏览器推理、量化精度、语义质量、UI切库、独立FTS正确性或崩溃恢复证据。

README/technical-note的ready中位数27.05/27.45/39.40/30.40 ms、batch比值2.147/2.793/1.018/0.967、四模式120查询及开发集质量1.0，与父线程归档的 `OBSERVED_SUMMARY.json` 舍入口径一致。0.985和1.296来自相应同后端的baseline/candidate ready中位数比值，算术一致。该归档明确是父线程DOM转录摘要，本轮没有独立读取DOM或原始120条浏览器样本来重算中位数。

发现过一处方向标签问题：源码公式是 `T_batch1/T_batch4`，原technical-note称“batch4/1墙钟比”会反向解释。根线程已统一改为“batch4墙钟加速比 T_batch1/T_batch4”，数值不改，当前两文通过核对；0.967仍表示batch4未提速。没有剩余明确不一致。可保留现有边界：完整浏览器原始报告尚未独立归档、双rAF约2秒未做物理前台校准、未清缓存、正式分数未验收。后续若要独立复算时序数值，需先保全完整raw报告；本轮不补写或虚构原始样本。
