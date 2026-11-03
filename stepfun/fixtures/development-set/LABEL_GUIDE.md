# Labels and metric scope

The corpus and labels are AI-assisted, self-authored development material. An agent wrote the fictional English policies and explicitly assigned relevance from their stated facts. Root's separate item-by-item review is pending. Do not call this real-person annotation, independent human gold, user experiments, official evaluation data or proof of general retrieval quality.

The frozen quality collection is **harbor H01-H20 revision 1 only**. There are ten fixed queries. Each query has exactly two directly relevant documents. `qrels.complete.json` and `.tsv` enumerate every query/document pair, including all nonrelevant documents: 200 binary judgments. `queries.jsonl` includes the positive IDs and a short explicit factual annotation note. The two Beacon documents are a separate KB-switch fixture, outside this candidate pool; the mutation versions are also outside frozen quality testing.

A document is relevant if it directly supplies at least one fact explicitly requested by that query, within the selected KB. A shared word, related department or different precondition is insufficient. Relevance is binary, with no unjudged initial Harbor document. Root may correct ambiguities before freezing the dataset; do not revise labels after looking at FP32/quantized rankings to improve a model's score.

Primary comparison: macro Recall@5 and binary nDCG@5 over all ten queries. Recall@3/10 may be added if declared before running. These K values are local development choices, not official thresholds. For query q and unique top-K document IDs R, Recall@K = |R intersect relevant(q)| / |relevant(q)|. Use the entire labelled relevant set as the denominator. An any-hit success rate is a different metric and must not be labelled Recall.

For binary nDCG, DCG@K = sum over returned rank r of rel(doc_r)/log2(r+1), up to K; IDCG@K uses the same formula for the first min(K, number of relevant documents) ideal positions. nDCG is DCG/IDCG. Macro-average each per-query metric across the fixed ten queries. Do not omit inconvenient queries or count one relevant document repeatedly.

Preserve actual seekdb result order; do not produce a client-side reranking/merge for this experiment. Duplicate result IDs, unknown/unmapped IDs, or IDs outside the active frozen collection require an integrity error and separate report. If a valid result list has fewer than K entries, score its actual entries without fabricated padding. A query execution error invalidates the full like-for-like run; report the error instead of silently averaging a successful subset. Empty valid results use the formula, not an artificial hit.

Use one vectorized record per short document for this set. If an implementation chunks sources, it must declare and consistently apply parent-document evaluation without counting multiple chunks as multiple relevant documents. Record source/ID mapping and chunking before comparison; never change it between precisions.

No ranked retrieval output, vectors, measured metric, latency or compression ratio is supplied. All runtime results remain not run. This small, simple sample only supports a controlled local comparison on these documents and queries.
