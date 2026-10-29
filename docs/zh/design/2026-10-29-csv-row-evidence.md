# CSV 行级来源与原始记录回查

## 目标与范围

实现竞赛 `source-01-table-evidence` 声明的公共接口，使离线 CSV 的每条逻辑记录成为可持久化、可精确引用的原始证据。实现集中于 `src/powercontext/sources/csv_rows.py`，复用现有 Source Definition、标准文本投影、Runtime ingestion 和 Memory 引用回查，不改变全局存储冲突语义，不新增产品依赖。

## 数据与身份

- 文档输入包含 `document_id`、`primary_key` 和完整 UTF-8 字节。
- 解析使用标准库 CSV 的严格引号语义，接受开头 BOM，保留引号内 CRLF、原始列序和字符串值。
- 先验证完整文档，再返回不可分割的行 tuple；编码、表头、记录宽度或主键错误统一以 `ValueError` 失败。
- 行身份为 `csv:{quote(document_id, safe="")}:{quote(primary_key_value, safe="")}`，编码后不超过 256 字符，不依赖行号或非主键字段。
- 校验空白时不修改有效字段。带空格的有效列名、主键值按原值匹配和编码。

## 来源与投影

公开 `CSVDocumentInput`、`CSVRowInput`、`CSVRowSource`、`parse_csv_document`、`csv_row_source_id` 和 `CSV_ROW_SOURCE_DEFINITION`。Definition 名称为 `csv-row`、版本为 `1`。每行 Source 的 `name` 等于 `source_id`，materialization 为 `CAPTURED`。

标准 `powercontext.text-evidence` 投影将整行按列序序列化为紧凑 JSON，使用 `ensure_ascii=False`。metadata 恰好包含 `document_id`、`primary_key`、`primary_key_value`、`columns` 和 `row`。适配器的 read 返回完整行输入。

## 验证

使用官方 Linux x86_64、Python 3.12 和 `competition/requirements.txt` 固定依赖，在独立云端虚拟环境运行第二题完整公开测试。保留未实现版本的失败对照，检查真实注册、入库、重启、Memory 检索和精确引用回查。产品测试补充身份长度边界、Unicode/分隔符编码、字符串与换行保真及原子失败等契约边界；不修改竞赛测试或评分数据。

## 交付

本地提交包含产品实现、必要测试和使用说明。用户自行推送实际开发分支，并用仓库 URL、分支及完整 commit SHA 提测。公开自测结果与比赛评分分别记录。

## 验证结果

2026-10-29，在 Linux x86_64、Python 3.12.3 和官方固定依赖下，`make -C competition test-csv` 的 17 个公开实例全部通过，耗时 2.49 秒；既有补充测试文件的 11 个实例全部通过，耗时 0.21 秒。公开测试实际覆盖 Runtime 入库、重启、Memory 检索和精确引用回查。未运行全仓测试或其他平台测试，比赛评分由实际提测核验。
