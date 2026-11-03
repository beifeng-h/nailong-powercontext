# 实跑证据

全部命令在 **Windows / Python 3.12.14 / 无任何外部数据库实例** 的环境下执行，
输出为真实运行结果（未做任何删改）。

## 1. 测试

```bash
python -m unittest discover -s tests -t .
```

```
Ran 62 tests in 2.932s
OK
```

## 2. 索引 + 导入 + 体检（本仓库自己）

```bash
python -m sddctx refresh
```

```
索引 30 文件 / 288 符号 / 62 测试；导入 5 规格 / 3 决策
[信息] ADR-003  DECISION_SUPERSEDED
        决策已失效（被 ADR-002 取代），不会进入上下文
```

没有 error，也没有 warning——本仓库自己的上下文是有效的。
唯一一条 info 是"ADR-003 已被 ADR-002 取代"，属于**预期状态**：
失效决策必须被记录下来，而不是悄悄消失。

```bash
python -m sddctx doctor ; echo "exit=$?"
```

```
[信息] ADR-003  DECISION_SUPERSEDED
        决策已失效（被 ADR-002 取代），不会进入上下文
exit=0
```

## 3. 取上下文包

```bash
python -m sddctx context --task "给上下文解析加上按改动文件加权排序" --changed sddctx/resolver.py
```

```markdown
# 开发任务上下文：给上下文解析加上按改动文件加权排序

## 当前有效的规格
### SPEC-001 上下文解析契约  (status=active)
必须满足：
- [REQ-CTX-1] 只有 status=active 的规格可以进入开发上下文；草稿只能作为候选提示，失效规格必须单列  <- 验证：tests/test_resolver.py::ResolverTests::test_resolve_excludes_superseded_spec
- [REQ-CTX-2] 上下文包必须同时给出相关代码位置与改动后需要重跑的测试  <- 验证：tests/test_resolver.py::ResolverTests::test_resolve_returns_code_and_tests
- [REQ-CTX-3] 被取代的决策不得进入有效决策列表，但必须在上下文中以已失效的形式出现并指出取代者  <- 验证：tests/test_resolver.py::ResolverTests::test_resolve_excludes_superseded_decision
相关代码：
- `sddctx/resolver.py:ContextResolver.resolve` — 上下文解析入口
- `sddctx/models.py:ContextBundle.to_markdown` — 上下文包渲染

### SPEC-002 上下文有效性体检契约  (status=active)
...
相关代码：
- `sddctx/drift.py:DriftChecker.check` — 体检入口
- `sddctx/drift.py:DriftChecker._check_spec` — 单份规格的漂移检查
```

规格按相关性排序返回（`SPEC-001` → `SPEC-002` → `SPEC-004` → `SPEC-003` → `SPEC-005`），
而不是按 id 顺序——相关性高的先给。

## 4. 助手拿到的执行清单

```bash
python -m sddctx assistant --task "给上下文解析加上按改动文件加权排序"
```

```text
- [ ] 阅读并遵守 SPEC-001 上下文解析契约
- [ ] 阅读并遵守 SPEC-002 上下文有效性体检契约
- [ ] 遵守决策 ADR-001 上下文默认存在嵌入式 SQLite，而不是外部数据库实例
- [ ] 不要依赖已失效决策 ADR-003 仅靠 status 字段判断规格有效性（已被 ADR-002 取代）
- [ ] 改动后运行 `tests/test_resolver.py::ResolverTests::test_resolve_excludes_superseded_spec`
- [ ] 改动后运行 `tests/test_drift.py::DriftTests::test_detect_missing_symbol`
...
- [ ] 改动完成后运行 `sddctx doctor`，确认上下文仍然有效
```

## 5. 真实改代码 -> 检出漂移 -> 改回来 -> 恢复有效

```bash
python scripts/demo_drift.py
```

脚本把仓库复制到临时目录再动手（不污染工作区），依次演示：

**阶段 0 · 基线**

```text
-> 没有阻塞项
-> error 数量：0
```

**阶段 1 · 把 `DriftChecker._check_spec` 改名成 `_check_one_spec`（规格没跟着改）**

```text
[error] SPEC-002  SPEC_CODE_SYMBOL_MISSING
        `sddctx/drift.py` 中的符号 `DriftChecker._check_spec` 不存在，代码已被删除或改名
-> error 数量：1
```

**阶段 2 · 删掉 `tests/test_drift.py`（先前的验证不再适用）**

```text
[error] SPEC-002  SPEC_TEST_MISSING
        验证用例 `tests/test_drift.py::DriftTests::test_detect_missing_symbol` 不存在，先前的验证结论不再适用
[error] SPEC-002  SPEC_REQ_VERIFY_MISSING
        需求 REQ-DRIFT-1 的验证用例已消失：tests/test_drift.py::DriftTests::test_detect_missing_symbol
-> error 数量：9
```

**阶段 3 · AI 助手准备开工时的判断**

```text
ready = False
[阻塞] SPEC_CODE_SYMBOL_MISSING：`sddctx/drift.py` 中的符号 `DriftChecker._check_spec` 不存在，代码已被删除或改名
```

**阶段 4 · 规格同步到新符号名**（测试仍缺失，还剩 1 个 error）

**阶段 5 · 补回测试用例**

```text
-> 没有阻塞项
-> error 数量：0
```

```text
结论：代码改动 -> 规格漂移被检出 -> 规格与测试跟上 -> 上下文恢复有效。
```

## 6. HTTP 接口实测

```bash
python -m sddctx serve --port 8787
```

```text
health: {'status': 'ok', 'stats': {'specs': 5, 'decisions': 3, 'symbols': 288, 'files': 30, 'tests': 62, 'reviews': 5}}
specs: ['SPEC-001', 'SPEC-002', 'SPEC-004', 'SPEC-003', 'SPEC-005']
invalidated_decisions: ['ADR-003']
blocking: 0
doctor.ok: True findings: 1
```

`/api/context` 返回的上下文包与命令行 `context` 一致：
当前有效规格 5 份、已失效决策 1 条（ADR-003）、阻塞项 0 个。

## 7. 评审基线随仓库走

```bash
python -m sddctx review SPEC-001 --note "验收通过：实现与用例齐备"
```

```text
已记录评审：SPEC-001 @ 2852a7e5fe7798cd
评审基线已写入 spec/reviews.json（可提交到仓库，跟着代码一起走）
```

`spec/reviews.json` 是可提交文件，因此重新 clone 之后 `refresh` 仍能判断
"这份规格上次验到哪个版本了"——这正是"先前的验证是否仍适用于当前代码"的依据。

