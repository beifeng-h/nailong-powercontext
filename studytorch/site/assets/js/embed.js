/* Browser copy of the deterministic fallback embedder in src/lib/ai/embeddings.ts. */
(function (global) {
  "use strict";

  var DIMENSIONS = 1024;
  var CJK_RUN = /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]+/u;
  var TOKEN_RUN =
    /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]+|[\p{Letter}\p{Number}_]+/gu;
  var HARD_LIMIT = 4000;

  function tokenize(text) {
    var normalized = String(text).normalize("NFKC").toLowerCase();
    var tokens = [];

    for (var segment of normalized.match(TOKEN_RUN) || []) {
      if (CJK_RUN.test(segment)) {
        var chars = Array.from(segment);
        chars.forEach(function (char, index) {
          tokens.push(char);
          var next = chars[index + 1];
          if (next) tokens.push(char + next);
        });
      } else {
        tokens.push(segment);
        if (segment.length >= 5) {
          for (var i = 0; i + 3 <= segment.length; i += 1) tokens.push(segment.slice(i, i + 3));
        }
      }
    }

    return tokens;
  }

  /** BM25 uses CJK bigrams and western words; the dense embedder keeps the full token set. */
  function tokenizeForSearch(text) {
    var normalized = String(text).normalize("NFKC").toLowerCase();
    var tokens = [];

    for (var segment of normalized.match(TOKEN_RUN) || []) {
      if (CJK_RUN.test(segment)) {
        var chars = Array.from(segment);
        if (chars.length === 1) {
          tokens.push(chars[0]);
        } else {
          for (var i = 0; i + 1 < chars.length; i += 1) tokens.push(chars[i] + chars[i + 1]);
        }
      } else {
        tokens.push(segment);
      }
    }

    return tokens;
  }

  function fnv1a(input, seed) {
    var hash = (seed === undefined ? 0x811c9dc5 : seed) >>> 0;
    for (var i = 0; i < input.length; i += 1) {
      hash ^= input.charCodeAt(i);
      hash = Math.imul(hash, 0x01000193) >>> 0;
    }
    return hash >>> 0;
  }

  function localEmbed(text) {
    var dimensions = DIMENSIONS;
    var vector = new Array(dimensions).fill(0);

    for (var token of tokenize(text)) {
      var index = fnv1a(token) % dimensions;
      var sign = (fnv1a(token, 0x9e3779b9) & 1) === 0 ? 1 : -1;
      var weight = Array.from(token).length > 1 ? 1 : 0.5;
      vector[index] += sign * weight;
    }

    var norm = 0;
    for (var i = 0; i < dimensions; i += 1) {
      var value = vector[i];
      if (value === 0) continue;
      var compressed = Math.sign(value) * Math.log1p(Math.abs(value));
      vector[i] = compressed;
      norm += compressed * compressed;
    }

    if (norm === 0) return vector;

    var scale = 1 / Math.sqrt(norm);
    return vector.map(function (value) {
      return value * scale;
    });
  }

  function normalizeText(raw) {
    return String(raw)
      .replace(/\r\n?/g, "\n")
      .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, " ")
      .replace(/[ \t]+\n/g, "\n")
      .trim();
  }

  function chunkText(raw, size, overlap) {
    var chunkSize = size || 500;
    var chunkOverlap = overlap === undefined ? 50 : overlap;
    var text = normalizeText(raw);
    if (text.length === 0) return [];

    var step = Math.max(1, chunkSize - chunkOverlap);
    var chunks = [];

    for (var start = 0; start < text.length; start += step) {
      var piece = text.slice(start, Math.min(start + chunkSize, text.length)).trim();
      if (piece.length > 0) chunks.push(piece.slice(0, HARD_LIMIT));
      if (start + chunkSize >= text.length) break;
    }

    return chunks;
  }

  global.StudySeekEmbed = {
    DIMENSIONS: DIMENSIONS,
    tokenize: tokenize,
    tokenizeForSearch: tokenizeForSearch,
    fnv1a: fnv1a,
    localEmbed: localEmbed,
    normalizeText: normalizeText,
    chunkText: chunkText,
  };
})(window);
