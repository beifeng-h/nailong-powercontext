# TEST_ONLY API-state probe — Temp proposal, not executed

`state-probe.mjs` is a runnable Node standard-library driver for the existing local service at `http://127.0.0.1:34021`. The contract was read from fixed Git commit `c4f99a1a9c94da7111291f16cafc5eb30ff7c657`. No HTTP, database, browser, model, product/ref change, installation, secret read or resource startup was performed in preparing it.

## Scope: protocol state, not model evidence

The driver deliberately generates unit-normalized 384-dimensional one-hot vectors in Node at request time. IDs select synthetic coordinates; B01 shares H05's coordinate to make the same query/vector probe KB separation. These are **not embeddings from any model**, not browser inference and not FP32/INT8/FP16 quality data. q8 and the declared model object are the existing API's required schema/profile declaration only. Every created KB label starts `TEST_ONLY_PROTOCOL_SYNTHETIC_<run-uuid>_...`; every document has `testOnly:true`, runId and an explicit synthetic vectorOrigin. Never select these KBs as a normal browser-embedding or quality experiment.

The receipt explicitly keeps browserEmbeddingVerifiedByThisProbe=false and qualityOrModelPrecisionEvidence=false. Server health's `embedding:browser-only` is merely a server configuration declaration; it does not override this probe's actual Node-generated vector origin. No Recall, nDCG, model accuracy, precision or inference speed metric is calculated.

This probe checks successful API writes/upsert replacement, the import/refresh completion contract, KB registry revision, current text/metadata visibility and URL-scoped KB isolation. It does not independently prove full-text index correctness, UI dropdown/cached-result behavior, browser reload, service/DB restart, disk/volume durability or crash recovery. Use the separately provided real-browser checklist for those application-level operations that it covers.

## Minimal commands

Use an already installed modern Node runtime with fetch/AbortSignal.timeout. No npm install or additional service/resource is needed. Wait for the benchmark and other writes to finish first.

```text
node state-probe.mjs
node state-probe.mjs run --execute
```

The default is plan-only: it reads only the two frozen local fixture JSON files and sends no request. The second command is for **root after reviewing this proposal**, not a command executed here. It creates two brand-new test KBs; it never accepts arbitrary existing UUIDs as write targets. Root may capture that new test's actual stdout JSON through the normal test runner. This is new protocol evidence, not a replacement/export of the cancelled browser-log download.

To test a physical new client process, exit the first command/process, preserve its genuine successful JSON by root's normal test-recording workflow, then invoke separately:

```text
node state-probe.mjs reopen --receipt <actual-successful-api-state-receipt.json> --execute
```

No example successful receipt or UUID is supplied. The reopen branch rejects plan/failure receipts, wrong synthetic-origin/fixture hashes and the same process ID. It only reads health/registry and sends read-only search requests. It does not stop/restart the existing service or create/import/delete anything. Different Node PID is a client-process check, not service-restart evidence.

## Exact state sequence

| Stage | Actual import response required | Visibility/isolation check |
| --- | --- | --- |
| Fresh Harbor/Beacon | New canonical UUID, exact unique run label, q8 profile, ready, rev0; neither UUID existed in pre-run registry | No existing user/benchmark KB is a write target |
| Harbor baseline H01-H20 | count20, KB revision1 | H21 absent before import; no cross-KB IDs |
| Add H21 | count21, KB revision2 | cobaltmesa418 query returns current H21/east-lobby text |
| Replace same H05 ID with frozen r2 | count still21, KB revision3 | ledgermint604 query returns exact r2/eleven-days body and metadata revision2, never old body |
| Beacon B01+B02 in one batch | count2, KB revision1 | Same expense text/vector returns B01/twenty-three-days body, only B IDs |
| Harbor→Beacon→Harbor API selection | No writes during switching | Same expense query yields current H05/B01/H05 under selected UUID; H21 remains visible |
| New process reopen | Existing registry UUID/label/profile/ready and revisions Harbor3/Beacon1 | Only read-only queries; same new bodies and isolation persist while the service remains running |

Import responses are only considered completed after the fixed API has awaited real upsert, index refresh and count/revision update. No fixed sleep is used. Search uses topK50 to make this a structural visibility probe; its returned length is never called a database count. The current API has no independent GET-count endpoint: after reopen, `freshCountAfterReopen` is null, and prior actual import counts are named as historical observations. Registry revision and known documents are freshly checked. Do not claim a new count measurement or complete storage enumeration from topK results.

All returned IDs must be unique and belong to that KB's exact allowed set; all returned text/metadata must match its current frozen revision. H05 document metadata revision2 is different from the Harbor KB's third import revision3. The API passes original text intact; this driver does not use the UI's trim/typed-text metadata path.

## Isolation and failure rules

A readonly registry snapshot is taken before creation. A create response is accepted only if UUID is canonical/new, exact label/profile match, ready and rev0. Only those successful current-run entries receive write ownership. The route guard allows only fixed health/list, new KB creation, owned import and owned search. There is no delete, direct SQL, arbitrary host, cloud, resource launch, credential or model runtime code.

Requests are sequential. A lost/invalid response, timeout, HTTP error or assertion failure stops the run; no create/import is retried. The actual report retains planned unique labels and known new UUIDs so root can reconcile uncertain outcomes before doing anything else. Failed/partial new KBs remain for inspection. Existing KBs are not modified or removed.

Reopen independently validates exact registry identity before allowing search, marks every entry createdThisRun=false and sets allowWrites=false. Thus even a later mistaken create/import call is blocked before HTTP. It never interprets an arbitrary external receipt as permission to write an existing KB.

A genuine browser-produced-vector variant is unnecessary for this protocol test and is not implemented. If root later supplies vectors generated by a real browser run, those are external storage-test inputs with their original provenance; replaying them through this driver must not be presented as fresh browser inference or sent to the frontend as precomputed app results.

Only syntax, default-plan/no-network and minimal synthetic-vector/fixture consistency checks may be run by the proposing agent. Real API/DB assertions, browser state and official requirements remain unexecuted here. Independent review is static only.
