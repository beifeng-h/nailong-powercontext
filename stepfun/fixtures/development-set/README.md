# StepFun synthetic development set — not official gold

AI-assisted synthetic English documents and explicit relevance labels, authored for this project. Root will independently review every text/query/label. No real-person annotation, user experiment or general retrieval-quality claim is made. No model/browser/DB run, vectors or measured results exist here.

Minimal reading order:

1. `documents.initial.jsonl`: all 20 Harbor quality texts and 2 Beacon switch-test texts, each also present as a UTF-8 .txt file.
2. `queries.jsonl` and `LABEL_GUIDE.md`: ten fixed queries, complete positive sets and annotation notes; then inspect `qrels.complete.tsv`/`.json` for all 200 binary judgments.
3. `STATE_SCENARIOS.json` with `documents.mutations.jsonl`: H21 addition, H05 revision-2 replacement, refresh completion and KB switching. Total stays 24 text versions/23 distinct IDs; do not add mutations to the frozen quality collection.
4. `TEST_PLAN.md`: minimal same-condition FP32/INT8-or-FP16 comparison and official requirement boundaries. `OBSERVATIONS_NOT_RUN.json` is all-null measurement scaffolding.
5. `DATA_MANIFEST.json` and `READY.json`: exact IDs/files/hashes/counts and review handoff.

Quality relevance is document-level: each query has two relevant initial Harbor documents. Recall uses the entire labelled relevant set, not any-hit. Binary nDCG uses the actual DB result order. This one small self-authored set cannot establish official or general retrieval quality. No numerical official quality-loss cutoff is invented.

All content is fictional; it is not a real organization's security, privacy, finance or employment policy. IDs are test metadata, not hardcoded search answers. If the application generates internal IDs, retain a reproducible fixture-ID mapping. Source documents/labels are identical across precision comparisons; root may revise ambiguities before freeze, never to chase measured results.

Temp-only delivery. Root alone applies selected data to the product; existing seekdb, MiniMax, AMD, Gaode, PDF and Git refs are untouched.
