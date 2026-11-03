---
id: SPEC-001
title: 上下文解析契约
status: active
scope: [resolver, models]
tags: [context, resolve, sdd]
supersedes: []
superseded_by:
requirements:
  - id: REQ-CTX-1
    key: context.resolve.effective_only
    text: 只有 status=active 的规格可以进入开发上下文；草稿只能作为候选提示，失效规格必须单列
    verified_by:
      - tests/test_resolver.py::ResolverTests::test_resolve_excludes_superseded_spec
  - id: REQ-CTX-2
    key: context.resolve.includes_code_and_tests
    text: 上下文包必须同时给出相关代码位置与改动后需要重跑的测试
    verified_by:
      - tests/test_resolver.py::ResolverTests::test_resolve_returns_code_and_tests
  - id: REQ-CTX-3
    key: context.resolve.excluded_decisions_are_reported
    text: 被取代的决策不得进入有效决策列表，但必须在上下文中以已失效的形式出现并指出取代者
    verified_by:
      - tests/test_resolver.py::ResolverTests::test_resolve_excludes_superseded_decision
code_refs:
  - file: sddctx/resolver.py
    symbol: ContextResolver.resolve
    note: 上下文解析入口
  - file: sddctx/models.py
    symbol: ContextBundle.to_markdown
    note: 上下文包渲染
test_refs:
  - file: tests/test_resolver.py
    test_id: tests/test_resolver.py::ResolverTests::test_resolve_excludes_superseded_spec
    covers:
      - REQ-CTX-1
  - file: tests/test_resolver.py
    test_id: tests/test_resolver.py::ResolverTests::test_resolve_returns_code_and_tests
    covers:
      - REQ-CTX-2
  - file: tests/test_resolver.py
    test_id: tests/test_resolver.py::ResolverTests::test_resolve_excludes_superseded_decision
    covers:
      - REQ-CTX-3
---

# SPEC-001 上下文解析契约

## 背景

软件持续演进过程中，仓库里同时存在：正在生效的规格、还没定稿的草稿、
被新版本取代的旧规格、以及互相矛盾的残留决策。AI 开发助手如果把这些
一视同仁地读进上下文，就会按已经作废的口径写代码。

## 契约

1. **生效面**：只有 `status: active` 的规格进入"当前有效的规格"一节。
   - `draft` 进入"待评审"一节，只作参考，不作为实现依据；
   - `superseded` / `deprecated` 进入"已失效"列表，不再指导实现。
2. **相关性**：按任务文本与规格标题、标签、范围、需求文本、引用文件做词元打分，
   分数相同则按规格 id 排序，保证同样输入得到同样输出。
3. **完整性**：上下文包必须包含"相关代码"与"相关测试"两部分，
   助手据此知道去哪儿改、改完跑什么。
4. **决策分离**：有效决策与已失效决策分列，已失效决策必须写明取代它的决策 id。

## 不在本契约范围内

- 相关性打分算法本身的调优（见 `docs/architecture.md` 的取舍表）。
- 规格与代码是否已经脱节的判断（见 SPEC-002）。

