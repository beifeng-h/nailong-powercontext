# PDF 显式 Crypt 流的解析

固定 pypdf 6.19 的 Crypt 解码分支拒绝带 `/Name` 或 `/Type` 的参数。合法空密码 PDF 可以通过 `/Crypt` 指定流使用的加密过滤器，包括透传的 `/Identity` 和加密字典 `/CF` 中声明的 `/StdCF`。这些页面必须完整解析并保留正文。

根据 [ISO 32000-1 的 7.4.10 与 7.6.5](https://opensource.adobe.com/dc-acrobat-sdk-docs/standards/pdfstandards/pdf/PDF32000_2008.pdf)，Crypt 必须是过滤链的第一项，Name 可以引用加密字典中声明的过滤器。缺省或 null Name 使用 Identity。多个过滤器的参数按位置对应。

## 解密与解码边界

解析专属 Reader 在流进入原生解密器前读取 Crypt 声明。Identity 选择透传方法；命名过滤器从原始 `Encrypt.CF` 字典读取 `CFM`，选择固定 pypdf 支持的 V2、AESV2 或 AESV3 方法。复制已授权的 Encryption 对象，仅设置副本的流方法 `StmF`；字符串仍使用原 `StrF`。普通流委托原解密器。Reader 在成功和异常路径均恢复原 Encryption 对象，不修改全局 pypdf 解码器或认证状态。读取 Encrypt 和 CF 间接引用时使用父类读取路径，避免重新安装包装器。

完成流解密后移除 Crypt 及其对应参数，保留后续过滤器和参数的顺序。单独的 Crypt 保留显式空过滤器数组，由原生解码器返回流内容。已有完整性校验继续检查压缩流。

不能只在解码失败后删除 `/Name`：文档默认使用 AES 时，原生解密阶段可能已经错误处理了本应明文的 Identity 流。也不能捕获任意异常后返回空页，否则会接受损坏的压缩内容。

原始输入字节、整份 PDF 摘要、文档身份、物理页边界和 Source 协议保持原有行为。未知名称、不支持的方法、非法过滤链及非空密码以 `ValueError` 原子失败。`CFM /None` 表示由安全处理器决定解密方式，不被当作 Identity 透传。本适配只覆盖已声明并受固定解密器支持的方法。

## 验证要求

独立 Writer 夹具包含 AES-128 的普通流和 Identity 流，以及 PDF 2.0 / AES-256 的命名 StdCF 流。夹具核对普通流实际加密、Identity payload 为明文、字典字符串仍受 StrF 加密。命名过滤器正例使用 StdCF，未知名称负例使用 MissingCF；夹具不调用产品的规范化逻辑。

十六项权限回归核对全局 Identity 空白页、普通 AES、显式 Identity、命名 AESV3、后接 Flate、缺省 Name、间接参数、null Name/Type，以及截断压缩流、非空密码、未知名称、Crypt 非首项、重复 Crypt 和缺失参数等拒绝场景。正文、物理页顺序和原始 PDF SHA-256 均直接核对。

固定依赖环境需重跑原有 PDF 回归和公开 PDF 测试。局部诊断另外核对原 Encryption 对象恢复、字典字符串解密和重复读取缓存。正式零分不披露失败维度，不能把这个已复现的解析缺陷直接认定为唯一正式原因。

## 实际结果

本机 pypdf 6.10 的隔离诊断已复现命名 AESV3 有、无 Flate 两项旧版失败，候选十项通过。PDFium 能独立读取无 Flate 的命名 AESV3 原件；对 Crypt+Flate 组合返回空的第二页，该局限保留。组合用例另以原生 AESV3 解密后的原始字节进行完整 zlib 解码，核对实际内容指令。

Python 3.12.3、官方固定 pypdf 6.19.0 与全部 78 项固定依赖下，旧解析器的两项命名 AESV3 正例精确失败。候选 99 项 PDF 回归与六项公开测试全部通过，无错误或跳过，依赖前后版本一致。该公开测试包含全部 503 页的真实入库与重开后引用回查。候选源码 SHA256 为 `f7f255f0d1b805f8eb6b69e264e675d48e5e81ccdbbaad0a000f4aab15b512bc`。

官方冻结词数、证据文本和整页参考不分发，相关 90%—110%、0.95、0.95 门槛仍须由平台验收；不能用本地回归数量或人工页面命中率代替。完整官方沙箱及全库 lint/type 未在本地重现。
