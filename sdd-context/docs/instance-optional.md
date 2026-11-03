# 接入外部数据库实例（可选）

**默认不需要。** 本项目的默认存储是嵌入式 SQLite（标准库自带），
`.sddctx/context.db` 一个文件就是全部数据，`python -m sddctx refresh` 即可，
不需要数据库、不需要网络、不需要容器。

只有在下面这些情况下才值得接实例：

- 多人或多台机器共享同一份上下文；
- 需要在 CI 之外长期保留上下文历史；
- 公司已有统一数据库（OceanBase / MySQL）并要求数据合规落在实例里。

## 怎么换

存储层是一个协议（`sddctx/store.py` 里的 `ContextStore`），
`sddctx/sqlstore.py` 提供了基于 PEP 249（DB-API 2.0）的适配器：

```python
import pymysql
from sddctx.sqlstore import SqlStore
from sddctx.assistant import AssistantRuntime

conn = pymysql.connect(
    host="127.0.0.1",
    port=2881,          # OceanBase
    user="root@demo",
    password="***",
    database="sddctx",
    charset="utf8mb4",
)

store = SqlStore(conn)
store.create_schema()

runtime = AssistantRuntime(store, root=".")
runtime.refresh()
```

`SqlStore` 会自动适配 `qmark` / `format` / `pyformat` 三种占位符风格，
所以 `sqlite3`、`pymysql`、`mysql-connector` 都能直接用。

表名统一加 `sdd_` 前缀（`sdd_specs` / `sdd_requirements` / `sdd_code_refs` /
`sdd_test_refs` / `sdd_decisions` / `sdd_symbols` / `sdd_files` / `sdd_tests` /
`sdd_reviews`），字段与嵌入式版本一一对应。

## 注意事项

- **建表**：OceanBase 的 MySQL 模式支持 `CREATE TABLE IF NOT EXISTS`；
  `store.create_schema()` 幂等，可重复执行。
- **TEXT 默认值**：MySQL 与 OceanBase 不允许 TEXT 列带默认值，所以适配器的建表语句
  用 `VARCHAR` 加 `MEDIUMTEXT`，不要照抄 SQLite 那份 schema。
- **事务**：`SqlStore` 每次写入后 commit，语义与 SQLite 版本一致；
  高并发写入场景建议在外部再包一层连接池。
- **迁移**：嵌入式库升级后想搬到实例，直接读出 `Spec` / `Decision` 再逐条
  `upsert_spec()` / `upsert_decision()`，不需要写导出脚本。

## 验证适配器本身不需要实例

`tests/test_sqlstore.py` 用 SQLite 的 `qmark` 风格跑通了适配器的
建表、写入、读取、评审记录与幂等性——所以接实例的风险主要在连接与方言，
不在适配器逻辑。

