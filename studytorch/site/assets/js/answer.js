/* Extractive, citation-bearing answer composition over the top hybrid-search hits. */
(function (global) {
  "use strict";

  var embed = global.StudySeekEmbed;
  var SENTENCE_ENDS = "。！？；!?;";
  var MAX_POINTS = 3;

  function splitSentences(text) {
    var normalized = String(text || "").replace(/\s+/g, " ").trim();
    var sentences = [];
    var buffer = "";

    for (var char of normalized) {
      buffer += char;
      if (SENTENCE_ENDS.indexOf(char) !== -1) {
        var sentence = buffer.trim();
        if (Array.from(sentence).length >= 12) sentences.push(sentence);
        buffer = "";
      }
    }

    /* 片段边界常把一句话截断，未闭合的尾巴不当作可引用要点。 */
    return sentences;
  }

  function queryTerms(question) {
    var terms = embed.tokenizeForSearch(question).filter(function (term) {
      /* 单个数字/字母会在 1024、0.6 这类写法里误命中，不作为要点匹配依据。 */
      return term.length >= 2;
    });
    return Array.from(new Set(terms));
  }

  function countOccurrences(haystack, needle) {
    if (!needle) return 0;
    var count = 0;
    var index = haystack.indexOf(needle);
    while (index !== -1) {
      count += 1;
      index = haystack.indexOf(needle, index + needle.length);
    }
    return count;
  }

  function lexicalMatch(sentence, terms) {
    var lower = sentence.toLowerCase();
    var score = 0;
    var matched = 0;

    terms.forEach(function (term) {
      var count = countOccurrences(lower, term.toLowerCase());
      if (count > 0) {
        matched += 1;
        score += count * Math.min(Array.from(term).length, 6);
      }
    });

    return { score: score / Math.sqrt(Math.max(1, Array.from(sentence).length)), matched: matched };
  }

  function clipSentence(sentence, terms, limit) {
    var maxLength = limit || 220;
    if (sentence.length <= maxLength) return sentence;

    var lower = sentence.toLowerCase();
    var firstHit = -1;
    terms.forEach(function (term) {
      var index = lower.indexOf(term.toLowerCase());
      if (index !== -1 && (firstHit === -1 || index < firstHit)) firstHit = index;
    });

    var start = Math.max(0, (firstHit === -1 ? 0 : firstHit) - Math.floor(maxLength / 3));
    var end = Math.min(sentence.length, start + maxLength);
    return (start > 0 ? "…" : "") + sentence.slice(start, end) + (end < sentence.length ? "…" : "");
  }

  function cosine(a, b) {
    var dot = 0;
    for (var i = 0; i < a.length; i += 1) dot += a[i] * b[i];
    return dot;
  }

  function compose(question, hits) {
    var text = String(question || "").trim();
    var top = (hits || []).slice(0, 5);

    if (top.length === 0) {
      return {
        lead: "没有在资料库中检索到与「" + text + "」相关的内容。可以换一个关键词，或在右侧上传新的资料后再试。",
        points: [],
        note: "",
        sources: [],
      };
    }

    var terms = queryTerms(text);
    var queryVector = embed.localEmbed(text);
    var candidates = [];

    top.forEach(function (hit, hitIndex) {
      splitSentences(hit.content).forEach(function (sentence, position) {
        var match = lexicalMatch(sentence, terms);
        candidates.push({
          text: clipSentence(sentence, terms),
          citation: hitIndex + 1,
          sourceIndex: hitIndex,
          position: position,
          matched: match.matched,
          score:
            (hit.score || 0) * 2 +
            cosine(queryVector, embed.localEmbed(sentence)) * 0.6 +
            match.score * 0.5 +
            (position === 0 ? 0.1 : 0),
        });
      });
    });

    candidates.sort(function (a, b) {
      return b.score - a.score;
    });

    var chosen = [];
    var perSource = Object.create(null);
    var seen = [];

    candidates.forEach(function (candidate) {
      if (chosen.length >= MAX_POINTS) return;
      if (candidate.matched === 0) return;
      if ((perSource[candidate.sourceIndex] || 0) >= 2) return;
      var prefix = candidate.text.slice(0, 18);
      if (seen.indexOf(prefix) !== -1) return;
      seen.push(prefix);
      perSource[candidate.sourceIndex] = (perSource[candidate.sourceIndex] || 0) + 1;
      chosen.push(candidate);
    });

    if (chosen.length === 0) {
      top.slice(0, 3).forEach(function (hit, index) {
        var sentence = splitSentences(hit.content)[0] || clipSentence(hit.content, terms, 180);
        if (sentence) {
          chosen.push({
            text: sentence,
            citation: index + 1,
            sourceIndex: index,
            position: 0,
          });
        }
      });
    }

    /* 选中后再按来源顺序阅读，引用编号与下方来源列表一致。 */
    chosen.sort(function (a, b) {
      return a.sourceIndex - b.sourceIndex || a.position - b.position;
    });

    return {
      lead: "根据检索到的资料，可以围绕「" + text + "」整理出以下要点：",
      points: chosen.map(function (point) {
        return { text: point.text, citation: point.citation };
      }),
      note: "以上为本地抽取式摘要：句子直接来自下方引用片段，未经过大模型改写；请以原文为准。",
      sources: top.map(function (hit, index) {
        return {
          index: index + 1,
          id: hit.id,
          fileName: hit.fileName,
          category: hit.category,
          content: hit.content,
          score: hit.score,
          vectorScore: hit.vectorScore,
          bm25Score: hit.bm25Score,
          chunkIndex: hit.chunkIndex,
          chunkCount: hit.chunkCount,
          source: hit.source,
        };
      }),
    };
  }

  global.StudySeekAnswer = {
    compose: compose,
    splitSentences: splitSentences,
  };
})(window);
