# Minimal actual acceptance plan

Official source read completely: project `artifacts/project-continuation-20261031/stepfun-official-readonly/FULL_TEXT_NORMALIZED.md`, title through 4.3 last paragraph; source https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/hc3pio/kw9wfx4bu9pyvat9 . This plan/data is Temp-only, not implemented application behavior or measured evidence.

## Quality comparison

1. Root reviews all 22 initial texts, ten queries and full 200 judgments, then freezes their hashes. Quality runs import Harbor H01-H20 revision 1 only. Beacon and mutation files must not enter those collections. Start fresh or verify exact IDs/content hashes to exclude stale rows.
2. Select one publicly available open-source English MiniLM-family embedding model and pin its actual repository/revision, tokenizer, pooling, normalization and truncation settings. Record the actual runtime/version. No model has been selected/downloaded/executed by this data preparation; do not assume output dimensions or existing quantized artifact compatibility.
3. Compare FP32 with the selected INT8 or FP16 variant of the same model under identical device, browser version, backend, batch size, corpus/query bytes, pooling/normalization, seekdb/seekdb-js versions, schema/index/full-text and hybrid parameters. Keep document/query preprocessing identical. Use isolated collections with the same fixture IDs and content.
4. Prefer same-backend pairs for precision-only comparison. If FP32 or a quantized mode is unsupported on a backend, report that limitation and choose a supported same-backend pair; do not attribute a backend change solely to quantization. Run the WebGPU-versus-WASM fallback check separately. Record selected provider from actual runtime, not just a UI label.
5. Wait for genuine writes/index refresh completion; generate every document/query embedding in the browser locally. Fetch ranked hybrid results from seekdb using seekdb-js, retain raw returned IDs/order and calculate the fixed metrics in LABEL_GUIDE. No cloud inference, precomputed server vectors/results, other database or client fusion replaces this path.
6. Report FP32 and quantized metrics and their signed differences on all ten queries. The official text supplies no numerical quality-loss cutoff; do not invent an official pass threshold or infer broad model quality from this small custom set.

## State/refresh checks

Use STATE_SCENARIOS.json as a separate ordered test, beginning with Harbor H01-H20 and Beacon B01-B02. Add H21, await the real refresh completion signal, then retrieve its unique text marker; replace H05 under the same ID with revision 2 and verify current body/hash without increasing Harbor's count; switch to Beacon and back, verifying no cross-KB IDs and retention of the new/updated Harbor data. The JSON operations are abstract inputs/expectations, not guessed seekdb-js API names. Map them to actual application commands and record receipts/results. A fixed delay alone is not refresh evidence.

## Minimum run observations

Record device/OS/browser, model repository/revision, precision, actual backend, batch size, runtime, actual embedding dimension, tokenizer/pooling/normalization, corpus/query/label hashes, seekdb settings and index readiness. Preserve actual query rankings and per-query metrics. For a single-optimization experiment keep all other conditions fixed.

Measure model files using the same total-file definition for FP32 and quantized artifacts, then compute FP32 bytes / quantized bytes from actual totals. Time download, model load, document embedding, write/index refresh, query embedding, database search and query-to-display end to end separately. Separate first/cold request from warmed requests. Predeclare a repeated-run count and report raw samples and medians; do not select the fastest sample. OBSERVATIONS_NOT_RUN.json contains no fabricated observations.

Run once with actual WebGPU availability and once in an environment where WebGPU is genuinely unavailable, checking automatic WASM selection, visible backend indication and the complete text-import/search flow. A forced label or a cached result is not fallback evidence. These browser/runtime checks are not performed here.

## Official requirement map and remaining evidence

| Official sections | What this package supports | Actual evidence still required |
| --- | --- | --- |
| 2.1 / 3.1 complete flow | Importable text/metadata and fixed queries | Actual Web app import, local document/query vectors, seekdb write, ranked results and original text display |
| 2.2 / 3.1 local inference | English text suitable for a planned English model | Pinned public model, actual browser-local computation for documents and queries, no cloud inference calls |
| 2.2(3) / 3.2(2-3) quantization | Frozen same-data FP32/quantized quality labels and method | Actual INT8/FP16 processing/artifacts, file totals/compression and measured quality change |
| 2.2(4) / 3.2(6) backend/fallback | Minimal two-environment check description | Actual WebGPU preference, unsupported-environment WASM fallback, UI indication and working flow |
| 2.3 / 3.1 seekdb data layer | IDs, texts, KB metadata and deterministic expectations | Real seekdb-js storage and DB-side vector+full-text hybrid queries; no client fusion or replacement DB |
| 2.3(3-4) / 3.1 state/refresh | Add/replace/switch test inputs and expected IDs/body/revisions | Real writes, completed index refresh, collection/session isolation and matching results |
| 2.4 / 3.2 / 4.3 optimization | Fixed-condition timing/quality plan | Actual before/after raw measurements, first/warm separation, medians and honest limitations |
| 4.1-4.3 deliverables | Reproducible data and source/label hashes | App/full source/dependencies/startup/model+quantization steps/schema/index/config and one-page technical explanation |

All execution rows remain unverified. This package does not assign contest points or transplant another challenge's all-or-nothing scoring rule. Product assets ultimately belong in the ecosystem-baseline `stepfun/` directory, applied by root; no product, UI, DB, model, vector or Git operation occurs here.
