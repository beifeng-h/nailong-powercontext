# 第五至第十一题实现与验证

验证日期：2026-10-30（北京时间）。本次实现沿用 `2026-competition` 分支，保留第四题 PDF 修复。官方 `competition/` 测试、输入与固定依赖未修改。

## 实现对应

| 题目 | 行为 |
| --- | --- |
| 5 HTTP 重排 | 先召回候选，再按 HTTP 评分全局稳定排序；批间 rank 保持原身份。 |
| 6 增量上下文 | 首轮发送完整包，后续复用公共分块前缀；独立接收端校验并重建原文。 |
| 7 数量触发 | 以 journal head 与成功 cursor 的差值判定新增来源数，复用原生 worker 和重试。 |
| 8 Embedding 合批 | 并发调用共享执行中请求，按上限分批，成功向量进入有界缓存。 |
| 9 来源生命周期 | 持久化依赖 DAG 与事件意图，将停用和恢复传播到原生 Memory/Topic 资格。 |
| 10 原文证据 | 按 query 从召回正文选取原文区间，保留精确身份，并限制完整 envelope 字节数。 |
| 11 混合查询 | 一条 statement 联合全文和 ANN 候选分支，各自在数据库中过滤和限额。 |

各题设计说明位于本目录对应的 `2026-10-30-*.md`。

## 云端结果

环境为 Linux x86_64、Python 3.12.3、pypdf 6.19.0、pylibseekdb 1.3.0.post4，使用官方 competition 固定依赖。14 个产品文件及 7 个补充测试文件的本地 SHA-256 与实际被测字节一致。Windows Git 将部分原有文件的 CRLF 规范为 LF；提交 blob 与云端文件在 LF 归一化后逐字节一致，转换前后的 Python AST 也完全相同。

| 测试组 | 通过数 |
| --- | ---: |
| 第 5 题公开 | 10 |
| 第 6 题公开 | 14 |
| 第 7 题公开 | 17 |
| 第 8 题公开 | 8 |
| 第 9 题公开 | 4 |
| 第 10 题公开 | 3 |
| 第 11 题公开 | 1 |
| CSV 回归 | 17 |
| Pi 回归 | 15 |
| PDF 回归 | 6 |
| 补充测试 | 43 |

共 95 项公开测试和 43 项补充测试通过，无失败、错误或跳过。第 11 题多 head/tag 补测还单独运行一次通过，未重复计入总数；真实 EXPLAIN 的两种查询均检查全文和向量索引。

首次补充运行因测试使用默认同名 Memory ID 发生冲突，42 项通过、1 项失败。测试改用公开 `MemoryService` 构造方式创建独立 artifact，保留多 head、旧投影、scope/artifact/tag 过滤、去重和两路索引断言；产品代码没有为该失败改变。原失败报告保留，修正后完整 43 项通过。

公开测试按题分进程运行，补充测试使用以下命令结构，避免导入非本次范围的顶层测试配置：

```bash
PRODUCT=/workspace/powercontext-pdf-repair/product
VALIDATION=/workspace/powercontext-pdf-repair/remaining-validation
RESULTS="$VALIDATION/results"
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
POWERCONTEXT_CANDIDATE="$PRODUCT" \
POWERCONTEXT_PUBLIC="$PRODUCT/competition" \
PYTHONPATH="$PRODUCT/src:$PRODUCT/competition:$PRODUCT" \
"$PRODUCT/competition/.venv/bin/python" -m pytest -q \
  -c "$PRODUCT/competition/pytest.ini" \
  --confcutdir="$PRODUCT/competition" \
  --junitxml="$RESULTS/supplemental.xml" \
  "$VALIDATION/tests/builtin/artifacts/memory/test_http_reranker.py" \
  "$VALIDATION/tests/builtin/inference/test_coalescing.py" \
  "$VALIDATION/tests/builtin/persistence/test_seekdb_hybrid_candidates.py" \
  "$VALIDATION/tests/builtin/runtime/test_source_count_admission.py" \
  "$VALIDATION/tests/builtin/runtime/test_source_lifecycle.py" \
  "$VALIDATION/tests/test_context_pack.py" \
  "$VALIDATION/tests/test_prepared_evidence.py"
```

## 验证边界

公开测试通过不代表正式评分满分。正式 SciFact 检索质量、PDF/原文证据覆盖、第 6 题完整 40 轮净传输节省、第 11 题完整语料 60 query 的质量与延迟仍待平台核验。未读取隐藏相关性标注、FinanceBench evidence/页清单或 SciFact qrels/evidence，未按固定题目硬编码。

本机完成 21 个改动 Python 文件的 AST 检查及 `git diff --check`。本机没有 uv、prek、Ruff 或 ty，未运行完整 `make check`、lint、类型检查或全仓测试；没有安装本机依赖。最终交付只创建本地提交，外部推送与正式提测由用户操作。
