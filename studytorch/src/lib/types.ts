export interface DocumentChunk {
  content: string;
  fileName: string;
  category: string;
}

export interface StoredChunk extends DocumentChunk {
  id: number;
}

export interface SearchHit extends DocumentChunk {
  id: number;
  score: number;
  keywordScore: number | null;
  semanticScore: number | null;
}

export interface CategoryCount {
  category: string;
  chunkCount: number;
  fileCount: number;
}

export interface AnswerSource extends SearchHit {
  index: number;
}

export interface AskResult {
  question: string;
  answer: string;
  sources: AnswerSource[];
}
