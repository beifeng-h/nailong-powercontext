# 一次真实 MiniMax 调用及同轮业务测试

2026-11-03 使用中国区 `MiniMax-M3.1-Flash` 真实调用一次，输入绑定源码 `b99c2e0a470cb92ddb5f0cc0a3161218e077b293`。[attempt-started.json](attempt-started.json)记录发起与输入指纹，[attempt-result.json](attempt-result.json)记录响应 id/model/usage 以及 after 指纹。后者的 `code_saved_not_tested` 是模型生成时的真实历史状态，后续测试不回写这一原记录。

[request.json](request.json)是去凭据后的实际请求，SHA-256 为 `55fa15ad831ec0ab9e76f099c4e61c252db95f5b6023280409c10e680c7d8e99`；其 `retrieved_context` 与 [context.redacted.json](redacted-evidence/context.redacted.json)结构和值一致。原始上下文未交付，其历史指纹 `be3a5cdca3a30d8c7e37b18d8d383e044312af2bd9cbe80b20f9076b849b1f6c` 只用于识别保留在本地的原件，不是脱敏副本的 hash。

[model-final.json](model-final.json)中的完整代码与 [交付 after](../../../business/after/taskboard.py)字节一致，SHA-256 为 `6ff48b87ddf11e44bd62a980c1b9c12f128f30b3c7299d3f2c20a7d1358772ac`；实际应用差异见 [application.diff](application.diff)。规格、测试和 fixture 没有修改。

同轮固定 before/after 对照见 [派生测试回执](redacted-evidence/tests/RECEIPT.redacted.json)：同一组 9 项，before 3 项目标失败、6 项回归通过，after 9 项通过。原始回执内日志 hash 标识历史原件；交付派生副本 hash 见 [MANIFEST.json](redacted-evidence/MANIFEST.json)。本地测试没有替代官方评分，完整干净环境数据库整链仍未完成。

本目录没有凭据、原始响应或私有 reasoning；这句话描述所选材料范围，模式扫描结果不构成不存在任何敏感内容的证明或公开发布授权。
