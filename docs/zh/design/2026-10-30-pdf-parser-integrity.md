# 完整 PDF 与内容流的原子失败

题面要求损坏或无法完整解析的 PDF 以 `ValueError` 整体失败。`PdfReader(strict=True)` 仍可能容忍部分截断：固定 pypdf 6.19.0 的 `_find_eof_marker` 对残缺的 `%%EOF` 只记录警告；ASCII85、ASCIIHex、RunLength 和 LZW 解码器也有将输入耗尽当作正常终止的恢复路径。库能恢复部分文字不等于输入符合本题的完整性要求。

`parse_pdf_document` 在构建读取器前，要求完整的 `%%EOF`，允许末尾没有换行，或者带有 PDF 定义的六种空白字节。检查不限制文件中的历史结束标记数量，增量修订仍可包含多组 trailer 与结束标记。

页面内容与 Form 资源的完整性检查覆盖实际解码的流。对过滤器链的每一步，先按对应参数解码此前缀，再校验当前编码的终止条件：

- Flate 必须真正到达压缩流结束，不能依赖库恢复出的部分数据。
- ASCIIHex 必须含有 `>`；ASCII85 必须有完整 `~>`，保留库接受的终止符间空白。
- RunLength 沿 run 边界查找 128，拒绝越界数据，不能把 literal 内容中的同值字节当作结束符。
- LZW 跟踪 9 至 12 位代码、字典大小、CLEAR 和 STOP，支持 EarlyChange 0/1，不展开额外的正文或字典字串。该检查只确认代码流完整性；正文提取仍由锁定的 pypdf 执行，不替代其解码质量验证。

这些检查在返回任何页面前完成。空白页仍按物理顺序保留，摘要仍计算完整原字节，报表检索逻辑不变。

## 验证范围

本机已有 pypdf 6.10.0，通过 AST 加载实际解析定义执行了 29 个构造输入；旧提交 `4b59c889` 在其中 16 个损坏输入上未按要求失败，当前实现全部符合预期。另对五份完整原 PDF 共 1258 页分别执行旧、新解析器，完整页面数据逐项一致。该检查不是完整 Runtime 或 pytest 执行，不能冒充固定 6.19.0 的云端验收。

另有 26 个独立 LZW framing 探针，覆盖两种 EarlyChange、全部位宽、满表与 CLEAR 重置、合法 next-code、非法字典代码及截断。原财报与独立 pdfplumber 的 755 页词项对照未发现词数比例或整页 F1 的阈值异常；独立解析器不是官方 gold。

新增 pytest 回归覆盖文件结束标记、合法尾部空白、四种编码及外层 ASCIIHex 过滤器链。固定 Python 3.12、pypdf 6.19.0 与全部 78 个官方依赖的云端环境中，旧解析器的 43 项解析回归有 16 项失败；候选两份 PDF 测试 62 项、公开 PDF 6 项、CSV 17 项和 Pi 15 项共 100 项全部通过，无错误或跳过。五份完整原 PDF 共 1258 页的新旧正文、页码、完整摘要逐项相同，全部被测源码与测试的 SHA 已再次核对。

第一次云端检查启动时依赖尚未装完，在环境核验处因缺少 packaging 停止；原日志保留，依赖齐全后使用新结果目录完整重跑，没有跳过检查或修改断言。完整仓库 lint、类型检查未运行。正式第四题的失败维度仍未由平台披露，不能将已修复的契约漏洞直接写成正式 0 分的已确认根因。

## 参考

- [pypdf 6.19.0 读取器源码](https://pypdf.readthedocs.io/en/6.19.0/_modules/pypdf/_reader.html)
- [pypdf 6.19.0 过滤器源码](https://raw.githubusercontent.com/py-pdf/pypdf/6.19.0/pypdf/filters.py)
- [Adobe PDF Reference 1.5](https://opensource.adobe.com/dc-acrobat-sdk-docs/pdfstandards/pdfreference1.5_v6.pdf)，文件结束、流过滤器及 EarlyChange 定义。
