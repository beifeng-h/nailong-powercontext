# 财报 PDF 全文解析与证据页检索

## 接口与全文解析

`powercontext.sources.pdf_pages` 提供 `PDFDocumentInput`、`PDFPageInput`、`parse_pdf_document`、`PDF_PAGE_SOURCE_DEFINITION` 和 `search_pdf_pages`。解析与页级 Source 位于 `pdf_pages.py`，离线检索位于 `_pdf_search.py`，复用现有 Runtime、scoped Memory 和精确引用接口，不增加依赖。

输入必须是完整原 PDF 字节和非空白文档 ID。使用 pypdf 默认文本提取，遍历全部物理页，保留每页可提取的正文、表格数字和原页关系；页码从 1 开始，空白页仍返回空文本。读取整份文档后才返回 tuple，解析异常统一为 `ValueError`，不返回部分页。空密码权限文件自动尝试空密码解密；不执行 OCR。

每页都记录原始完整 PDF 的 SHA-256，不以页面文本或文件名代替文档摘要。页面文本不截断，不用摘要、预解析正文或占位页替代全文。

## 页级身份与引用

`pdf-page` Definition 版本为 `1`，Source 为 `CAPTURED`。身份由 `(document_id, document_sha256, page_number)` 的 JSON 数组编码及 SHA-256 生成，加 `pdf:` 前缀后为 68 字符；修订 PDF 会改变摘要和页身份，旧引用继续对应原修订。

Source 保存完整 `PDFPageInput`，`read` 返回同一页输入。标准文本投影正文为 `DOCUMENT_ID\nPAGE_TEXT`，metadata 恰好包含 `document_id`、`document_sha256`、`page_number`。引用中的页码始终为物理页码，不能与财报印刷页码混用。

## 离线证据页检索

`search_pdf_pages` 只操作调用方传入的 scoped Memory。通过公开 `memory.list` 取得当前范围的实际页条目，以 `pdf-page` Source 身份去重，并保留原条目的 `MemoryCitation`；不直接读取数据库或创建引用。

检索采用词项规范化、停用词过滤、通用财务同义词扩展和离线 BM25 排序。公司与年份线索来自问题和已存页的文档 ID，不编码具体文档或问题答案。有限的公开 FTS 查询提供补充排序信号，轻度多样性选择减少近似重复正文占满结果。返回至多 `limit` 个不同页的原始精确 citation；空问题或非正上限返回空 tuple。

全文提取和证据召回是两项独立要求：保留完整页面不能保证问题命中正确页，排序也不能弥补丢失的原文。结果须经 `memory.get` 回查实际条目及 Source，以文档摘要和物理页码定位原 PDF。

## 数据边界与验证状态

产品实现只读取传入 PDF、文档 ID、问题及当前 scope 的 Memory。没有网络或模型调用，不读取答案、标注证据、预解析文本、证据页清单或判题资产，不硬编码文档及问题答案。

2026-10-29，在锁定 pypdf 6.19.0 的云端环境执行 `make -C competition test-pdf`，6 个公开实例全部通过，耗时 24.23 秒，退出码为 0；使用真实 Runtime 的 3 个合成补充实例全部通过，耗时 3.37 秒，退出码为 0。代码包及原公开 PDF 的 SHA-256 已核对一致。

重新打开公开测试的持久化数据库并定位含 `pdf-page` 条目的 scope 后，5 个原公开问题均返回 20 个不同页面，100 条 citation 逐一通过 `memory.get` 与 Source 投影正文、文档摘要和物理页码核对；检查未读取标注证据，返回完整引用不等于 Recall@20 达标。

上述公开测试和合成补充测试不等于正式质量门槛验收。正式评测要求的每页词项数 90%–110%、证据词项召回 0.95、整页 F1 0.95 和 evidence-page Recall@20 0.70 仍未核验，当前不能宣称这些质量指标或正式得分通过。提交使用实际分支和完整 commit SHA。
