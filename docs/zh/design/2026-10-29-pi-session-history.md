# Pi 会话分支采集与断点恢复

## 目标与接口

在 `src/powercontext/sources/pi_session.py` 实现竞赛 `source-02-pi-history`。公开 `PiSessionInput`、`PiEventInput`、`parse_pi_session`、`PI_EVENT_SOURCE_DEFINITION` 和 `PiSessionConnector`，复用现有 Source、标准文本投影、Runtime ingestion 和 ConnectorLifecycle，不新增依赖或修改 CSV。

## 分支与原始证据

输入为允许开头 BOM 的 UTF-8 Pi v3 JSONL。先验证完整文件的 JSON、会话头、唯一节点 ID 和父节点关系；未指定 leaf 时使用最后节点。沿所选 leaf 的父链回溯，再按根到叶的顺序生成可见事件。控制节点参与连接，不产生文本证据。

消息文本、工具调用与结果、bash 输出、自定义消息及两类摘要按题面格式投影；thinking 和 image 不进入文本。摘要不删除祖先事件。每个 `PiEventInput` 保留完整输入 `record`，Source 保存完整正文，不按 Memory 单条文本上限截断。

Source Definition 名为 `pi-event`、版本为 `1`，Source 为 `CAPTURED`。身份取 session ID 与 event ID 的 JSON 数组序列化结果的 SHA-256，并加 `pi:` 前缀，长度为 67 字符。`read` 返回完整事件输入；标准 `powercontext.text-evidence/1` 投影保留正文，以及 session_id、event_id、parent_id、event_type、role 五项 metadata。

## 增量与持久化进度

`PiSessionConnector(path, leaf_id=None)` 声明名称 `pi-session-history`、版本 `1`。checkpoint 使用版本 `1` 和 `imported` 映射，保存各已导入事件身份及完整 `record` 的排序紧凑 JSON 哈希。切换分支时保留已导入集合的并集，共享祖先不重复提交，其他分支的已存证据继续保留。

每轮先完整解析输入与所选分支，再核对当前文件中所有已导入记录的哈希，包含当前分支之外的历史事件；发现改写即以 `ValueError` 失败。仅向 `session.submit` 提交当前分支的新可见事件，构造新 checkpoint，不原地修改已加载的进度。

只有事件成功持久化后，才返回完成状态，由 ConnectorLifecycle 比较并保存进度。解析异常、历史改写或提交失败不推进 checkpoint；此前已经入库的相同事件可以依靠现有幂等语义重试，不覆盖旧证据。

## 验证与交付

2026-10-29，在 Linux x86_64、Python 3.12.3 和竞赛固定依赖下，`make -C competition test-pi` 的 15 个公开实例全部通过，耗时 3.95 秒，退出码为 0；`make -C competition test-csv` 的 17 个公开实例全部通过，耗时 2.46 秒，退出码为 0。验收的 Pi 源码与本地哈希一致，固定依赖完整性和兼容性校验通过。

提交使用实际开发分支及完整 commit SHA；正式成绩仍待平台提测核验。
