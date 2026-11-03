function optional(name: string, fallback: string): string {
  const raw = process.env[name];
  return raw === undefined || raw === "" ? fallback : raw;
}

function integer(name: string, fallback: number): number {
  const parsed = Number.parseInt(optional(name, String(fallback)), 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export const seekdb = {
  host: optional("SEEKDB_HOST", "127.0.0.1"),
  port: integer("SEEKDB_PORT", 2881),
  user: optional("SEEKDB_USER", "root"),
  password: optional("SEEKDB_PASSWORD", ""),
  database: optional("DATABASE_NAME", "studyseek"),
  table: "documents",
  /** 全文索引分词器。默认 ik，因为 space 会把整句中文当成一个词。 */
  fulltextParser: optional("FULLTEXT_PARSER", "ik"),
};

/** seekdb 支持的分词器白名单，同时防止 FULLTEXT_PARSER 被拼进 DDL 时注入。 */
export const FULLTEXT_PARSERS = ["ik", "space", "ngram", "ngram2", "beng", "jieba"] as const;

export const dashscope = {
  baseUrl: optional("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
  embeddingModel: optional("EMBEDDING_MODEL", "text-embedding-v3"),
  dimensions: integer("EMBEDDING_DIMENSIONS", 1024),
  chatModel: optional("CHAT_MODEL", "qwen-turbo"),
  apiKeyConfigured(): boolean {
    return (process.env.DASHSCOPE_API_KEY ?? "").trim().length > 0;
  },
  apiKey(): string {
    const key = process.env.DASHSCOPE_API_KEY;
    if (!key) {
      throw new Error("DASHSCOPE_API_KEY 未配置，请在 .env.local 中填写阿里云 DashScope API Key。");
    }
    return key;
  },
};

/** 每个向量切块的字符数。 */
export const CHUNK_SIZE = 500;
/** 相邻切块之间保留的字符数，避免语义在边界被切断。 */
export const CHUNK_OVERLAP = 50;
/** text-embedding-v3 单次请求最多 10 条文本。 */
export const EMBEDDING_BATCH_SIZE = 10;
/** 单文件最大字节数。 */
export const MAX_UPLOAD_BYTES = 8 * 1024 * 1024;

export const DEFAULT_CATEGORIES = ["课程资料", "项目文档", "笔记"] as const;

export const ACCEPTED_EXTENSIONS = [".pdf", ".md", ".markdown", ".txt"] as const;
