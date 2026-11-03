(function (global) {
  "use strict";

  var data = global.STUDYSEEK_DATA;
  var embed = global.StudySeekEmbed;
  var search = global.StudySeekSearch;
  var answer = global.StudySeekAnswer;

  if (!data || !data.documents || !embed || !search || !answer) {
    document.body.textContent = "StudySeek 初始化失败：缺少数据或检索模块。";
    return;
  }

  var DEFAULT_QUERY = "混合检索";
  var RESULT_SIZE = 10;
  var BROWSE_SIZE = 12;
  var AI_SIZE = 5;
  var MAX_FILE_BYTES = 8 * 1024 * 1024;
  var ACCEPTED_EXTENSIONS = [".pdf", ".md", ".markdown", ".txt"];
  var STOP_TERMS = ["什么", "怎么", "如何", "为什么", "哪些", "是否", "可以", "一下", "以及", "这个", "那个"];

  var state = {
    documents: data.documents.map(function (doc) {
      return {
        id: doc.id,
        fileName: doc.fileName,
        category: doc.category,
        source: doc.source || "seed",
        chunks: doc.chunks.slice(),
      };
    }),
    index: null,
    query: DEFAULT_QUERY,
    category: "",
    aiBusy: false,
    ingesting: false,
    pdfPromise: null,
  };

  state.index = search.createIndex(state.documents);

  function byId(id) {
    return document.getElementById(id);
  }

  var ui = {
    categoryList: byId("category-list"),
    chunkTotal: byId("chunk-total"),
    docCount: byId("doc-count"),
    chunkCount: byId("chunk-count"),
    footerChunks: byId("footer-chunks"),
    searchForm: byId("search-form"),
    searchInput: byId("search-input"),
    clearQuery: byId("clear-query"),
    themeToggle: byId("theme-toggle"),
    resultsList: byId("results-list"),
    resultsSummary: byId("results-summary"),
    resultsEmpty: byId("results-empty"),
    resultsEmptyTitle: byId("results-empty-title"),
    categoryBadge: byId("category-badge"),
    aiForm: byId("ai-form"),
    aiQuestion: byId("ai-question"),
    aiSubmit: byId("ai-submit"),
    aiOutput: byId("ai-output"),
    aiScope: byId("ai-scope"),
    dropzone: byId("dropzone"),
    fileInput: byId("file-input"),
    uploadCategory: byId("upload-category"),
    uploadStatus: byId("upload-status"),
  };

  function create(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function clear(node) {
    node.textContent = "";
  }

  function formatScore(value) {
    return value === null || value === undefined || !Number.isFinite(Number(value)) ? "—" : Number(value).toFixed(4);
  }

  function categoryStats() {
    var counts = Object.create(null);
    state.documents.forEach(function (doc) {
      doc.chunks.forEach(function () {
        counts[doc.category] = (counts[doc.category] || 0) + 1;
      });
    });

    var names = (data.meta.categories || []).slice();
    state.documents.forEach(function (doc) {
      if (names.indexOf(doc.category) === -1) names.push(doc.category);
    });

    return names.map(function (name) {
      return { name: name, count: counts[name] || 0 };
    });
  }

  function totalChunks() {
    return state.index.chunks.length;
  }

  function scopedChunkCount() {
    if (!state.category) return state.index.chunks.length;
    return state.index.chunks.filter(function (chunk) {
      return chunk.category === state.category;
    }).length;
  }

  function updateAiScope() {
    ui.aiScope.textContent = state.category ? "范围：" + state.category : "范围：全部分类";
  }

  function makeCategoryButton(category, label, count) {
    var item = create("li");
    var button = create("button", "category-button");
    button.type = "button";
    button.dataset.category = category;
    button.setAttribute("aria-pressed", String(state.category === category));
    button.setAttribute("aria-label", (category ? "筛选分类：" + label : label) + "，共 " + count + " 个片段");

    var text = create("span", null, label);
    var badge = create("span", "category-count", String(count));
    button.append(text, badge);
    item.append(button);
    return item;
  }

  function renderCategories(stats) {
    if (state.category && !stats.some(function (item) { return item.name === state.category; })) {
      state.category = "";
    }

    var signature = stats.map(function (item) { return item.name; }).join("\u0001");
    var total = totalChunks();

    if (ui.categoryList.dataset.signature !== signature) {
      clear(ui.categoryList);
      var fragment = document.createDocumentFragment();
      fragment.append(makeCategoryButton("", "全部分类", total));
      stats.forEach(function (item) {
        fragment.append(makeCategoryButton(item.name, item.name, item.count));
      });
      ui.categoryList.append(fragment);
      ui.categoryList.dataset.signature = signature;
    }

    var buttons = ui.categoryList.querySelectorAll("[data-category]");
    buttons.forEach(function (button) {
      var name = button.dataset.category;
      var count = name ? 0 : total;
      if (name) {
        stats.forEach(function (item) {
          if (item.name === name) count = item.count;
        });
      }
      var badge = button.querySelector(".category-count");
      if (badge) badge.textContent = String(count);
      button.setAttribute("aria-pressed", String(state.category === name));
    });
  }

  function renderUploadCategories(stats) {
    var signature = stats.map(function (item) { return item.name + ":" + item.count; }).join("\u0001");
    if (ui.uploadCategory.dataset.signature === signature) return;

    var previous = ui.uploadCategory.value;
    clear(ui.uploadCategory);
    stats.forEach(function (item) {
      var option = document.createElement("option");
      option.value = item.name;
      option.textContent = item.name + "（" + item.count + "）";
      ui.uploadCategory.append(option);
    });

    var names = stats.map(function (item) { return item.name; });
    if (previous && names.indexOf(previous) !== -1) {
      ui.uploadCategory.value = previous;
    } else if (names.indexOf("课程资料") !== -1) {
      ui.uploadCategory.value = "课程资料";
    } else if (names.length > 0) {
      ui.uploadCategory.value = names[0];
    }
    ui.uploadCategory.dataset.signature = signature;
  }

  function renderStats() {
    var stats = categoryStats();
    var chunks = totalChunks();
    var docs = state.documents.length;

    ui.docCount.textContent = String(docs);
    ui.chunkCount.textContent = String(chunks);
    ui.chunkTotal.textContent = chunks + " 个片段";
    ui.footerChunks.textContent = String(chunks);

    renderCategories(stats);
    renderUploadCategories(stats);

    ui.categoryBadge.hidden = !state.category;
    ui.categoryBadge.textContent = state.category ? "分类 " + state.category : "";
    updateAiScope();
  }

  function escapeRegExp(value) {
    return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function buildHighlightTerms(query) {
    var raw = String(query || "").trim();
    if (!raw) return [];

    var parts = [raw];
    parts.push.apply(parts, raw.split(/[\s,，。、；;:：!?？()（）\[\]{}]+/));

    var runs = raw.match(/[\u4e00-\u9fff]{2,}/g) || [];
    runs.forEach(function (run) {
      parts.push(run);
      for (var i = 0; i + 1 < run.length; i += 1) parts.push(run.slice(i, i + 2));
    });

    embed.tokenizeForSearch(raw).forEach(function (token) {
      if (token.length >= 2) parts.push(token);
    });

    var unique = [];
    parts.forEach(function (part) {
      var value = part.trim();
      if (value.length < 2 || STOP_TERMS.indexOf(value) !== -1) return;
      if (unique.indexOf(value) === -1) unique.push(value);
    });

    return unique.sort(function (a, b) { return b.length - a.length; }).slice(0, 24);
  }

  function appendHighlighted(node, text, terms) {
    if (!terms || terms.length === 0) {
      node.textContent = text;
      return;
    }

    var pattern = new RegExp("(" + terms.map(escapeRegExp).join("|") + ")", "gi");
    var segments = String(text).split(pattern);
    segments.forEach(function (segment, index) {
      if (!segment) return;
      if (index % 2 === 1) node.append(create("mark", null, segment));
      else node.append(document.createTextNode(segment));
    });
  }

  function excerpt(content, terms, radius) {
    var limit = radius || 260;
    if (content.length <= limit * 2) return content;

    var lower = content.toLowerCase();
    var firstHit = -1;
    (terms || []).forEach(function (term) {
      var index = lower.indexOf(term.toLowerCase());
      if (index !== -1 && (firstHit === -1 || index < firstHit)) firstHit = index;
    });

    if (firstHit === -1) return content.slice(0, limit * 2) + "…";

    var start = Math.max(0, firstHit - Math.floor(limit / 2));
    var end = Math.min(content.length, start + limit * 2);
    return (start > 0 ? "…" : "") + content.slice(start, end) + (end < content.length ? "…" : "");
  }

  function renderResultCard(hit, rank, terms, hasScores) {
    var item = create("li");
    var article = create("article", "result-card");
    var head = create("div", "result-head");

    head.append(
      create("span", "rank", hasScores ? "#" + rank : "片段"),
      create("h2", "file-name", hit.fileName),
      create("span", "badge badge-accent", hit.category),
      create("span", "badge badge-outline", hit.source === "upload" ? "本地上传" : "示例资料")
    );

    var snippet = create("p", "result-snippet");
    appendHighlighted(snippet, excerpt(hit.content, terms), terms);

    var foot = create("footer", "result-foot");
    if (hasScores) {
      var fused = create("span", null, "综合 " + formatScore(hit.score));
      fused.title = "0.6 × 向量归一化 + 0.4 × BM25 归一化";
      var vector = create("span", null, "向量 " + formatScore(hit.vectorNorm));
      vector.title = "归一化向量得分；原始余弦 " + formatScore(hit.vectorScore);
      var bm25 = create("span", null, "BM25 " + formatScore(hit.bm25Norm));
      bm25.title = "归一化 BM25 得分；原始分 " + formatScore(hit.bm25Score);
      foot.append(fused, vector, bm25);
    }
    foot.append(create("span", null, "片段 " + (hit.chunkIndex + 1) + "/" + hit.chunkCount));

    article.append(head, snippet, foot);
    item.append(article);
    return item;
  }

  function renderResults() {
    var query = state.query.trim();
    var hasScores = query.length > 0;
    var hits = hasScores
      ? search.hybridSearch(state.index, query, { size: RESULT_SIZE, category: state.category })
      : search.browse(state.index, state.category, BROWSE_SIZE);
    var terms = hasScores ? buildHighlightTerms(query) : [];
    var scoped = scopedChunkCount();

    if (hasScores) {
      ui.resultsSummary.textContent =
        "「" + query + "」返回 " + hits.length + " 个片段 · 按综合得分排序";
    } else {
      ui.resultsSummary.textContent =
        "共 " + scoped + " 个片段，显示前 " + hits.length + " 个 · 输入关键词开始混合检索";
    }

    clear(ui.resultsList);
    var fragment = document.createDocumentFragment();
    hits.forEach(function (hit, index) {
      fragment.append(renderResultCard(hit, index + 1, terms, hasScores));
    });
    ui.resultsList.append(fragment);

    ui.resultsEmpty.hidden = hits.length > 0;
    if (hits.length === 0) {
      if (hasScores) {
        ui.resultsEmptyTitle.textContent = "没有匹配「" + query + "」的片段";
      } else if (state.category) {
        ui.resultsEmptyTitle.textContent = "「" + state.category + "」分类暂无片段";
      } else {
        ui.resultsEmptyTitle.textContent = "资料库为空";
      }
    }

    updateAiScope();
  }

  function toggleClearButton() {
    ui.clearQuery.hidden = ui.searchInput.value.length === 0;
  }

  function commitQuery(value, focusInput) {
    state.query = String(value || "").trim();
    ui.searchInput.value = state.query;
    toggleClearButton();
    renderResults();
    if (focusInput) ui.searchInput.focus();
  }

  function setupSearch() {
    ui.searchForm.addEventListener("submit", function (event) {
      event.preventDefault();
      commitQuery(ui.searchInput.value, false);
    });

    ui.searchInput.addEventListener("input", toggleClearButton);

    ui.clearQuery.addEventListener("click", function () {
      commitQuery("", true);
    });

    document.querySelector(".suggestions").addEventListener("click", function (event) {
      var button = event.target.closest("[data-suggestion]");
      if (!button) return;
      commitQuery(button.dataset.suggestion, true);
    });
  }

  function setupCategories() {
    ui.categoryList.addEventListener("click", function (event) {
      var button = event.target.closest("[data-category]");
      if (!button) return;
      state.category = button.dataset.category || "";
      renderStats();
      renderResults();
    });
  }

  function setAiBusy(label) {
    ui.aiOutput.setAttribute("aria-busy", "true");
    clear(ui.aiOutput);
    ui.aiOutput.append(create("p", "tiny", label));
  }

  function renderAiError(message) {
    clear(ui.aiOutput);
    var box = create("p", "upload-status error", message);
    ui.aiOutput.append(box);
    ui.aiOutput.setAttribute("aria-busy", "false");
  }

  function renderAnswer(question, result) {
    var terms = buildHighlightTerms(question);
    clear(ui.aiOutput);

    var wrapper = create("div", "answer");

    var meta = create("div", "answer-meta");
    meta.append(
      create("span", "badge badge-outline", "本地抽取式回答"),
      create("span", null, "未调用大模型"),
      create("span", null, "检索 " + result.sources.length + " 个片段")
    );
    wrapper.append(meta);

    wrapper.append(create("p", "answer-lead", result.lead));

    if (result.points.length > 0) {
      var points = create("ol", "answer-points");
      result.points.forEach(function (point) {
        var item = create("li");
        item.append(document.createTextNode(point.text + " "));
        item.append(create("span", "cite", "[" + point.citation + "]"));
        points.append(item);
      });
      wrapper.append(points);
    }

    if (result.note) wrapper.append(create("p", "answer-note", result.note));

    if (result.sources.length > 0) {
      var sources = create("div", "answer-sources");
      sources.append(create("h3", null, "引用片段（按检索排序）"));

      var list = create("ol", "source-list");
      list.setAttribute("role", "list");

      result.sources.forEach(function (source) {
        var item = create("li", "source-item");
        var head = create("div", "source-head");
        head.append(
          create("span", "badge badge-accent", "[" + source.index + "]"),
          create("p", "source-file", source.fileName),
          create("span", "badge", source.category),
          create("span", "source-score", "综合 " + formatScore(source.score))
        );

        var snippet = create("p", "source-snippet");
        appendHighlighted(snippet, excerpt(source.content, terms, 130), terms);

        item.append(head, snippet);
        list.append(item);
      });

      sources.append(list);
      wrapper.append(sources);
    }

    ui.aiOutput.append(wrapper);
    ui.aiOutput.setAttribute("aria-busy", "false");
  }

  function askQuestion(question) {
    if (state.aiBusy) return;
    var text = String(question || "").trim();
    if (text.length < 2) {
      renderAiError("请输入至少 2 个字符的问题。");
      return;
    }

    state.aiBusy = true;
    ui.aiSubmit.disabled = true;
    ui.aiSubmit.textContent = "生成中…";
    setAiBusy("正在混合检索 top5 片段…");

    setTimeout(function () {
      try {
        var hits = search.hybridSearch(state.index, text, { size: AI_SIZE, category: state.category });
        var result = answer.compose(text, hits);
        renderAnswer(text, result);
      } catch (error) {
        renderAiError("生成回答失败：" + (error instanceof Error ? error.message : String(error)));
      } finally {
        state.aiBusy = false;
        ui.aiSubmit.disabled = false;
        ui.aiSubmit.textContent = "生成回答";
      }
    }, 30);
  }

  function setupAi() {
    ui.aiForm.addEventListener("submit", function (event) {
      event.preventDefault();
      askQuestion(ui.aiQuestion.value);
    });

    ui.aiOutput.addEventListener("click", function (event) {
      var button = event.target.closest("[data-question]");
      if (!button) return;
      ui.aiQuestion.value = button.dataset.question;
      askQuestion(ui.aiQuestion.value);
    });
  }

  function setUploadStatus(kind, message) {
    ui.uploadStatus.className = "upload-status" + (kind ? " " + kind : "");
    ui.uploadStatus.textContent = message;
  }

  function fileExtension(name) {
    var lower = String(name || "").toLowerCase();
    var dot = lower.lastIndexOf(".");
    return dot === -1 ? "" : lower.slice(dot);
  }

  function validateFile(file) {
    if (!file || file.size === 0) throw new Error("文件为空");
    if (file.size > MAX_FILE_BYTES) throw new Error("文件超过 8 MB");
    if (ACCEPTED_EXTENSIONS.indexOf(fileExtension(file.name)) === -1) {
      throw new Error("仅支持 PDF / MD / TXT");
    }
  }

  function loadPdfJs() {
    if (state.pdfPromise) return state.pdfPromise;

    state.pdfPromise = new Promise(function (resolve, reject) {
      var script = document.createElement("script");
      script.src = "assets/vendor/pdfjs/pdf.js";
      script.async = true;
      script.onload = function () {
        if (!global.pdfjsLib) {
          state.pdfPromise = null;
          reject(new Error("PDF 解析库未正确初始化"));
          return;
        }
        global.pdfjsLib.GlobalWorkerOptions.workerSrc = "assets/vendor/pdfjs/pdf.worker.js";
        resolve(global.pdfjsLib);
      };
      script.onerror = function () {
        state.pdfPromise = null;
        reject(new Error("PDF 解析库加载失败，请检查 assets/vendor/pdfjs 是否完整"));
      };
      document.head.append(script);
    });

    return state.pdfPromise;
  }

  async function extractPdf(file) {
    var pdfjs = await loadPdfJs();
    var bytes = new Uint8Array(await file.arrayBuffer());
    var pdf = await pdfjs.getDocument({ data: bytes, isEvalSupported: false, disableFontFace: true }).promise;
    var pages = [];

    for (var pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
      var page = await pdf.getPage(pageNumber);
      var content = await page.getTextContent();
      var pieces = [];
      content.items.forEach(function (item) {
        if (typeof item.str !== "string") return;
        pieces.push(item.str);
        if (item.hasEOL) pieces.push("\n");
      });
      pages.push(pieces.join("").replace(/[ \t]*\n[ \t]*/g, "\n"));
      if (typeof page.cleanup === "function") page.cleanup();
    }

    if (typeof pdf.destroy === "function") await pdf.destroy();
    return pages.join("\n\n");
  }

  async function extractText(file) {
    var ext = fileExtension(file.name);
    if (ext === ".pdf") return extractPdf(file);
    if (ext === ".md" || ext === ".markdown" || ext === ".txt") return file.text();
    throw new Error("不支持的文件格式");
  }

  function yieldToBrowser() {
    return new Promise(function (resolve) {
      setTimeout(resolve, 0);
    });
  }

  async function handleFiles(fileList) {
    var files = Array.from(fileList || []);
    if (files.length === 0 || state.ingesting) return;

    state.ingesting = true;
    var category = ui.uploadCategory.value || data.meta.categories[0] || "笔记";
    var added = [];
    var failures = [];
    var addedChunks = 0;
    var addedCharacters = 0;

    for (var index = 0; index < files.length; index += 1) {
      var file = files[index];
      setUploadStatus("busy", "正在处理 " + file.name + "（" + (index + 1) + "/" + files.length + "）…");
      await yieldToBrowser();

      try {
        validateFile(file);
        var text = await extractText(file);
        var chunks = embed.chunkText(text, 500, 50);

        if (chunks.length === 0) {
          throw new Error("未提取到文本，扫描版 PDF 需要先做 OCR");
        }

        var docId = "upload-" + Date.now() + "-" + index;
        var doc = {
          id: docId,
          fileName: file.name,
          category: category,
          source: "upload",
          chunks: chunks.map(function (content, chunkIndex) {
            return {
              id: docId + "-c" + (chunkIndex + 1),
              chunkIndex: chunkIndex,
              chunkCount: chunks.length,
              content: content,
              embedding: embed.localEmbed(content),
            };
          }),
        };

        added.push(doc);
        addedChunks += chunks.length;
        addedCharacters += embed.normalizeText(text).length;
      } catch (error) {
        failures.push({
          name: file.name,
          reason: error instanceof Error ? error.message : String(error),
        });
      }
    }

    if (added.length > 0) {
      state.documents = added.concat(state.documents);
      state.index = search.createIndex(state.documents);
    }

    renderStats();
    renderResults();

    var message = "";
    if (added.length > 0) {
      message =
        "已加入索引：" +
        added.length +
        " 个文件 · " +
        addedChunks +
        " 个片段 · " +
        addedCharacters +
        " 字（分类：" +
        category +
        "）。";
    }

    if (failures.length > 0) {
      var reasons = failures.map(function (item) {
        return item.name + "（" + item.reason + "）";
      });
      message += (message ? " 未能入库：" : "未能入库：") + reasons.join("；");
    }

    setUploadStatus(added.length > 0 ? "success" : "error", message);
    state.ingesting = false;
    ui.fileInput.value = "";
  }

  function setupUpload() {
    ui.dropzone.addEventListener("click", function () {
      if (!state.ingesting) ui.fileInput.click();
    });

    ui.dropzone.addEventListener("keydown", function (event) {
      if (event.key !== "Enter" && event.key !== " " && event.key !== "Spacebar") return;
      event.preventDefault();
      if (!state.ingesting) ui.fileInput.click();
    });

    ["dragenter", "dragover"].forEach(function (type) {
      ui.dropzone.addEventListener(type, function (event) {
        event.preventDefault();
        event.stopPropagation();
        ui.dropzone.classList.add("dragging");
      });
    });

    ["dragleave", "drop"].forEach(function (type) {
      ui.dropzone.addEventListener(type, function (event) {
        event.preventDefault();
        event.stopPropagation();
        ui.dropzone.classList.remove("dragging");
      });
    });

    ui.dropzone.addEventListener("drop", function (event) {
      if (event.dataTransfer) handleFiles(event.dataTransfer.files);
    });

    ui.fileInput.addEventListener("change", function () {
      handleFiles(ui.fileInput.files);
    });

    document.addEventListener("dragover", function (event) {
      event.preventDefault();
    });
    document.addEventListener("drop", function (event) {
      if (!ui.dropzone.contains(event.target)) event.preventDefault();
    });
  }

  function updateThemeLabel(theme) {
    var dark = theme === "dark";
    ui.themeToggle.setAttribute("aria-label", dark ? "切换到浅色模式" : "切换到深色模式");
    ui.themeToggle.title = dark ? "切换到浅色模式" : "切换到深色模式";
  }

  function setupTheme() {
    updateThemeLabel(document.documentElement.dataset.theme);
    ui.themeToggle.addEventListener("click", function () {
      var next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      try {
        localStorage.setItem("studyseek-theme", next);
      } catch (error) {
        /* Local storage can be unavailable in private contexts. */
      }
      updateThemeLabel(next);
    });
  }

  function init() {
    ui.searchInput.value = state.query;
    toggleClearButton();
    renderStats();
    renderResults();
    setupSearch();
    setupCategories();
    setupAi();
    setupUpload();
    setupTheme();
  }

  init();
})(window);
