-- 向量动物园 · seekdb schema
-- 一个库同时承担：向量检索（基因组近邻/亲缘）、全文检索（图鉴检索）、
-- JSON 半结构化（栖息地/食性/稀有度过滤）、以及关系型统计（生态仪表盘）。

CREATE DATABASE IF NOT EXISTS vector_zoo DEFAULT CHARACTER SET utf8mb4;

USE vector_zoo;

CREATE TABLE IF NOT EXISTS creatures (
  id          BIGINT AUTO_INCREMENT PRIMARY KEY,
  code        VARCHAR(16)  NOT NULL,          -- 图鉴编号 ZK-0001
  name        VARCHAR(64)  NOT NULL,
  latin       VARCHAR(128) NOT NULL DEFAULT '',
  tagline     VARCHAR(255) NOT NULL DEFAULT '',
  seeds       JSON         NOT NULL,          -- ["西瓜","章鱼"]
  genome      VECTOR(512)  NOT NULL,          -- 基因组 = 两个母本词向量的混合
  axes        JSON         NOT NULL,          -- 8 条基因轴（由基因组投影得到）
  traits      JSON         NOT NULL,          -- {"habitat":..,"diet":..,"rarity":..}
  lore        TEXT         NOT NULL,
  rarity      VARCHAR(16)  NOT NULL DEFAULT '普通',
  novelty     FLOAT        NOT NULL DEFAULT 0,-- 与已有种群的最近余弦距离
  parents     JSON         NOT NULL,          -- 杂交父母 id
  generation  INT          NOT NULL DEFAULT 0,
  created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_code (code),
  -- 向量索引：亲缘检索 / 新颖度 / 重复物种检测
  VECTOR INDEX idx_genome (genome) WITH (distance=cosine, type=hnsw, m=16, ef_construction=200),
  -- 全文索引：图鉴关键词检索（中文用 ngram）
  FULLTEXT INDEX idx_text (name, latin, tagline, lore) WITH PARSER ngram
) DEFAULT CHARSET = utf8mb4;

-- seekdb 的 hybrid search：一条 SQL 里同时算余弦距离与全文得分
-- SELECT id, name,
--        COSINE_DISTANCE(genome, :vec) AS dist,
--        MATCH(name, latin, tagline, lore) AGAINST(:q) AS text_score
-- FROM creatures
-- WHERE traits->>'$.habitat' = :habitat
-- ORDER BY 0.62 * (1 - dist) + 0.38 * LEAST(IFNULL(text_score, 0), 1) DESC
-- LIMIT 12;
