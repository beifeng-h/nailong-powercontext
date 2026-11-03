-- 与 src/lib/db/schema.ts 中 createTableSql() 保持一致的参考副本。
-- 表会由程序自动创建；切换全文分词器请用 npm run db:rebuild -- --yes（全文索引的 parser 无法 ALTER，只能重建）。
--
-- ORGANIZATION = HEAP 是必须的：seekdb 只在堆表上支持混合搜索。
-- WITH PARSER ik 是中文全文检索的关键：默认 space 分词会把整句中文当成一个词。

CREATE DATABASE IF NOT EXISTS studyseek CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;

USE studyseek;

CREATE TABLE IF NOT EXISTS documents (
    id INT PRIMARY KEY AUTO_INCREMENT,
    content VARCHAR(4096),
    file_name VARCHAR(255),
    category VARCHAR(64),
    embedding VECTOR(1024),
    VECTOR INDEX idx_vec(embedding) WITH (distance=l2, type=hnsw, lib=vsag),
    FULLTEXT INDEX idx_ft(content) WITH PARSER ik
) ORGANIZATION = HEAP;

-- 快速验证分词是否真的生效（有 ik 时这条应该能命中）：
--   SELECT id, file_name FROM documents
--    WHERE MATCH(content) AGAINST('过拟合') LIMIT 5;
