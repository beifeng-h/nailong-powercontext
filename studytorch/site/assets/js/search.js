/* In-browser hybrid retrieval: cosine kNN + BM25, fused with 0.6 / 0.4 weights. */
(function (global) {
  "use strict";

  var embed = global.StudySeekEmbed;
  var VECTOR_WEIGHT = 0.6;
  var BM25_WEIGHT = 0.4;
  var K1 = 1.5;
  var B = 0.75;
  var MAX_CANDIDATES = 50;

  function clamp(value, min, max) {
    var parsed = Math.trunc(Number(value));
    if (!Number.isFinite(parsed)) return min;
    return Math.min(Math.max(parsed, min), max);
  }

  function flattenDocuments(documents) {
    var chunks = [];

    (documents || []).forEach(function (doc) {
      (doc.chunks || []).forEach(function (chunk) {
        chunks.push({
          id: chunk.id,
          docId: doc.id,
          fileName: doc.fileName,
          category: doc.category,
          source: doc.source || "seed",
          content: chunk.content,
          embedding: chunk.embedding,
          chunkIndex: chunk.chunkIndex,
          chunkCount: chunk.chunkCount,
        });
      });
    });

    return chunks;
  }

  /** Build the inverted term statistics used by BM25. Runs in the browser, including for uploads. */
  function createIndex(documents) {
    var chunks = flattenDocuments(documents);
    var termFreqs = new Array(chunks.length);
    var lengths = new Array(chunks.length);
    var docFreq = Object.create(null);
    var totalLength = 0;

    chunks.forEach(function (chunk, index) {
      var tokens = embed.tokenizeForSearch(chunk.content);
      var tf = Object.create(null);

      for (var i = 0; i < tokens.length; i += 1) {
        var token = tokens[i];
        tf[token] = (tf[token] || 0) + 1;
      }

      termFreqs[index] = tf;
      lengths[index] = tokens.length;
      totalLength += tokens.length;

      Object.keys(tf).forEach(function (term) {
        docFreq[term] = (docFreq[term] || 0) + 1;
      });
    });

    return {
      chunks: chunks,
      termFreqs: termFreqs,
      lengths: lengths,
      docFreq: docFreq,
      avgdl: chunks.length > 0 ? totalLength / chunks.length : 0,
    };
  }

  function bm25Scores(index, query) {
    var scores = new Array(index.chunks.length).fill(0);
    var queryTerms = Array.from(new Set(embed.tokenizeForSearch(query))).filter(function (term) {
      return term.length > 0;
    });

    if (queryTerms.length === 0 || index.chunks.length === 0) return scores;

    var idf = queryTerms.map(function (term) {
      var df = index.docFreq[term] || 0;
      return Math.log(1 + (index.chunks.length - df + 0.5) / (df + 0.5));
    });

    for (var docIndex = 0; docIndex < index.chunks.length; docIndex += 1) {
      var tf = index.termFreqs[docIndex];
      var length = index.lengths[docIndex];
      var norm = K1 * (1 - B + (B * length) / (index.avgdl || 1));
      var score = 0;

      for (var termIndex = 0; termIndex < queryTerms.length; termIndex += 1) {
        var frequency = tf[queryTerms[termIndex]] || 0;
        if (frequency === 0) continue;
        score += (idf[termIndex] * (frequency * (K1 + 1))) / (frequency + norm);
      }

      scores[docIndex] = score;
    }

    return scores;
  }

  function cosineSimilarity(a, b) {
    var length = Math.min(a.length, b.length);
    var dot = 0;
    var normA = 0;
    var normB = 0;

    for (var i = 0; i < length; i += 1) {
      dot += a[i] * b[i];
      normA += a[i] * a[i];
      normB += b[i] * b[i];
    }

    if (normA === 0 || normB === 0) return 0;
    return dot / (Math.sqrt(normA) * Math.sqrt(normB));
  }

  /** Cosine kNN over every candidate chunk; the small local corpus makes an exact scan affordable. */
  function knnVectorScores(index, queryVector) {
    var scores = new Array(index.chunks.length).fill(0);

    for (var i = 0; i < index.chunks.length; i += 1) {
      var similarity = cosineSimilarity(queryVector, index.chunks[i].embedding);
      scores[i] = Math.max(0, similarity);
    }

    return scores;
  }

  function ranked(scores, candidates, limit) {
    return candidates
      .map(function (index) {
        return { index: index, score: scores[index] };
      })
      .filter(function (item) {
        return item.score > 0;
      })
      .sort(function (a, b) {
        return b.score - a.score;
      })
      .slice(0, limit);
  }

  function toHit(index, entry) {
    var chunk = index.chunks[entry.index];
    return {
      id: chunk.id,
      docId: chunk.docId,
      fileName: chunk.fileName,
      category: chunk.category,
      source: chunk.source,
      content: chunk.content,
      chunkIndex: chunk.chunkIndex,
      chunkCount: chunk.chunkCount,
      score: entry.fused,
      vectorScore: entry.vectorScore,
      bm25Score: entry.bm25Score,
      vectorNorm: entry.vectorNorm,
      bm25Norm: entry.bm25Norm,
    };
  }

  function hybridSearch(index, query, options) {
    var opts = options || {};
    var size = clamp(opts.size || 10, 1, 50);
    var category = opts.category || "";
    var text = String(query || "").trim();

    var candidates = [];
    for (var i = 0; i < index.chunks.length; i += 1) {
      if (!category || index.chunks[i].category === category) candidates.push(i);
    }

    if (candidates.length === 0) return [];
    if (text.length === 0) return browse(index, category, size);

    var keywordScores = bm25Scores(index, text);
    var vectorScores = knnVectorScores(index, embed.localEmbed(text));
    var candidateK = Math.min(MAX_CANDIDATES, Math.max(30, size * 3));

    var keywordTop = ranked(keywordScores, candidates, candidateK);
    var vectorTop = candidates
      .map(function (indexOfChunk) {
        return { index: indexOfChunk, score: vectorScores[indexOfChunk] };
      })
      .filter(function (item) {
        return item.score > 0;
      })
      .sort(function (a, b) {
        return b.score - a.score;
      })
      .slice(0, candidateK);

    var maxKeyword = keywordTop.length > 0 ? keywordTop[0].score : 0;
    var maxVector = vectorTop.length > 0 ? vectorTop[0].score : 0;
    var merged = new Map();

    function absorb(items, channel) {
      items.forEach(function (item) {
        var entry = merged.get(item.index) || {
          index: item.index,
          bm25Score: 0,
          vectorScore: 0,
          bm25Norm: 0,
          vectorNorm: 0,
          fused: 0,
        };
        if (channel === "bm25") entry.bm25Score = item.score;
        else entry.vectorScore = item.score;
        merged.set(item.index, entry);
      });
    }

    absorb(keywordTop, "bm25");
    absorb(vectorTop, "vector");

    var hits = Array.from(merged.values()).map(function (entry) {
      entry.bm25Norm = maxKeyword > 0 ? entry.bm25Score / maxKeyword : 0;
      entry.vectorNorm = maxVector > 0 ? entry.vectorScore / maxVector : 0;
      entry.fused = VECTOR_WEIGHT * entry.vectorNorm + BM25_WEIGHT * entry.bm25Norm;
      return toHit(index, entry);
    });

    return hits
      .filter(function (hit) {
        return hit.score > 0;
      })
      .sort(function (a, b) {
        return b.score - a.score || b.vectorScore - a.vectorScore || String(a.id).localeCompare(String(b.id));
      })
      .slice(0, size);
  }

  function browse(index, category, size) {
    var limit = clamp(size || 12, 1, 50);
    var hits = [];

    for (var i = 0; i < index.chunks.length && hits.length < limit; i += 1) {
      var chunk = index.chunks[i];
      if (category && chunk.category !== category) continue;
      hits.push({
        id: chunk.id,
        docId: chunk.docId,
        fileName: chunk.fileName,
        category: chunk.category,
        source: chunk.source,
        content: chunk.content,
        chunkIndex: chunk.chunkIndex,
        chunkCount: chunk.chunkCount,
        score: null,
        vectorScore: null,
        bm25Score: null,
        vectorNorm: null,
        bm25Norm: null,
      });
    }

    return hits;
  }

  global.StudySeekSearch = {
    VECTOR_WEIGHT: VECTOR_WEIGHT,
    BM25_WEIGHT: BM25_WEIGHT,
    K1: K1,
    B: B,
    createIndex: createIndex,
    bm25Scores: bm25Scores,
    cosineSimilarity: cosineSimilarity,
    knnVectorScores: knnVectorScores,
    hybridSearch: hybridSearch,
    browse: browse,
  };
})(window);
