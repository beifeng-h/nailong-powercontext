from __future__ import annotations
from pathlib import Path
import collections
from datetime import datetime, timezone
import hashlib
import json
import math
import os
import re
import subprocess

REPO = Path(__file__).resolve().parents[3]
SOURCE = REPO / "stepfun"
OUT = Path(__file__).resolve().parent
COMMIT = "c4f99a1a9c94da7111291f16cafc5eb30ff7c657"
EVENT_FILE = SOURCE / "runtime/bridge-api-events-1793494763413.jsonl"
MODES = {
 "fp32-gpu": "84564b7d-dcbc-4f11-8395-3a48c35a4d9f",
 "fp16-gpu": "60f59a02-65dc-482a-9cce-410fa47fac41",
 "fp32-wasm": "49241595-e41f-4b38-9f5f-703edfc50bfb",
 "q8-wasm": "47758c27-2fde-4350-ab3c-bbf7dda03f1b",
}

def digest(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 return h.hexdigest()
def git(*args):
 env=dict(os.environ,GIT_NO_LAZY_FETCH='1',GIT_OPTIONAL_LOCKS='0')
 return subprocess.check_output(['git','--no-lazy-fetch',*args],cwd=REPO,env=env)
def load(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def line_of(name,needle):
 return [i for i,s in enumerate((SOURCE/name).read_text(encoding='utf-8').splitlines(),1) if needle in s]

head_before=git('rev-parse','HEAD').decode().strip()
assert head_before==COMMIT
assert git('rev-parse','--show-object-format').decode().strip()=='sha1'
tracked=[]
for item in git('ls-tree','-r','-z',COMMIT,'--','stepfun/').split(b'\0'):
 if not item:continue
 left,name=item.split(b'\t',1);mode,kind,oid=left.decode().split()
 assert kind=='blob'
 relative=name.decode();p=REPO/relative;data=p.read_bytes()
 actual_oid=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
 lf=data.replace(b'\r\n',b'\n');lf_oid=hashlib.sha1(b'blob '+str(len(lf)).encode()+b'\0'+lf).hexdigest()
 tracked.append({'path':relative,'git_blob':oid,'disk_blob':actual_oid,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'exact_raw_match':actual_oid==oid,'lf_normalized_sha256':hashlib.sha256(lf).hexdigest(),'lf_normalized_blob':lf_oid,'lf_normalized_matches':lf_oid==oid,'crlf_count':data.count(b'\r\n')})
assert tracked and all(v['exact_raw_match'] or v['lf_normalized_matches'] for v in tracked)

raw=EVENT_FILE.read_bytes();raw_sha=hashlib.sha256(raw).hexdigest()
events=[json.loads(line) for line in raw.decode('utf-8').splitlines() if line.strip()]
assert len(events)==240 and all(v['evidenceLevel']=='public-sdk-api' for v in events)
starts=[v for v in events if v['kind']=='hybrid-api-start'];completed=[v for v in events if v['kind']=='hybrid-api-complete']
assert len(starts)==len(completed)==120
assert {v['kbId'] for v in events}==set(MODES.values())
assert all(events[i]['kind']=='hybrid-api-start' and events[i+1]['kind']=='hybrid-api-complete' and (events[i]['kbId'],events[i]['revision'])==(events[i+1]['kbId'],events[i+1]['revision']) for i in range(0,240,2))
assert all(v['revision']==1 and v['count']==5 and v['transport']=='embedded' and math.isfinite(v['queryMs']) and v['queryMs']>=0 for v in completed)
assert all(all(isinstance(v.get(k),str) and re.fullmatch('[0-9a-f]{64}',v[k]) for k in ['statementSha256','parameterSha256']) for v in completed)
assert all(datetime.fromisoformat(events[i]['at'].replace('Z','+00:00'))<=datetime.fromisoformat(events[i+1]['at'].replace('Z','+00:00')) for i in range(239))
by_mode={}
for name,kb in MODES.items():
 rows=[v for v in completed if v['kbId']==kb]
 ps=collections.Counter(v['parameterSha256'] for v in rows);ss=collections.Counter(v['statementSha256'] for v in rows)
 assert len(rows)==30 and len(ps)==10 and set(ps.values())=={3} and len(ss)==1
 by_mode[name]={'kbId':kb,'complete':len(rows),'starts':sum(v['kbId']==kb for v in starts),'statementSha256':next(iter(ss)),'parameter_hash_unique':len(ps),'each_parameter_hash_count':3,'parameter_hash_counts':dict(ps),'first':rows[0]['at'],'last':rows[-1]['at']}
assert len({v['statementSha256'] for v in completed})==4
assert events[-1]['at']=='2026-11-01T01:04:52.861Z'
(OUT/'bridge-api-events-snapshot.jsonl').write_bytes(raw)

receipt=load(SOURCE/'evidence/resource-acquisition/receipt.json')
measured=load(SOURCE/'evidence/resource-acquisition/MODEL_FILES_MEASURED.json')
assert receipt['status']=='acquisition_complete_not_runtime_tested'
assert receipt['plan']['model']=='Xenova/all-MiniLM-L6-v2'
assert receipt['plan']['revision']=='751bff37182d3f1213fa05d7196b954e230abad9'
assert receipt['plan']['runtime_version']=='3.8.1'
assert receipt['plan']['onnxruntime_web']=='1.22.0-dev.20250409-89f8206ba4'
resources=[]
for item in receipt['results']:
 p=(SOURCE/item['relative']).resolve();assert p.is_relative_to((SOURCE/'public').resolve())
 got=digest(p);size=p.stat().st_size
 assert item['status']=='published' and size==item['expected_bytes']==item['actual_bytes'] and got==item['expected_sha256']==item['actual_sha256']
 resources.append({'relative':item['relative'],'kind':item['kind'],'bytes':size,'sha256':got,'receipt_match':True})
assert len(resources)==12
assert all(v.get('verified') is True for v in receipt['downloads'])
common=sum(v['bytes'] for v in resources if v['kind']=='model' and not v['relative'].endswith('.onnx'))
profiles={}
for profile,filename in [('fp32','model.onnx'),('fp16','model_fp16.onnx'),('q8','model_quantized.onnx')]:
 row=next(v for v in resources if v['relative'].endswith('/'+filename));old=measured['profiles'][profile]
 assert old['weight_bytes']==row['bytes'] and old['weight_sha256']==row['sha256'] and old['common_bytes']==common and old['total_model_package_bytes']==common+row['bytes']
 profiles[profile]={'weight_bytes':row['bytes'],'common_bytes':common,'total_bytes':common+row['bytes'],'sha256':row['sha256']}
assert measured['runtime_asset_bytes']==sum(v['bytes'] for v in resources if v['kind']=='runtime')

lock=load(SOURCE/'package-lock.json');package=load(SOURCE/'package.json');dependencies={}
for name in ['seekdb','@seekdb/js-bindings']:
 expected=lock['packages']['node_modules/'+name];installed=load(SOURCE/'node_modules'/name/'package.json')
 assert package['dependencies'][name]==expected['version']==installed['version']=='1.4.0'
 dependencies[name]={'version':installed['version'],'locked_resolved':expected['resolved'],'locked_integrity':expected['integrity'],'installed_metadata_matches':True}

frozen=load(SOURCE/'fixtures/ROOT_REVIEW.json');datasets={}
for filename,expected in frozen['public_files'].items():
 p=SOURCE/'public/fixtures'/filename;got=digest(p);assert got==expected
 datasets[filename]={'sha256':got,'matches_frozen_review':True,'bytes':p.stat().st_size}
queries=load(SOURCE/'public/fixtures/queries.json')['queries'];ids=['H'+str(i).zfill(2) for i in range(1,21)]
qrels={q['id']:{id:1 if id in q['relevant_ids'] else 0 for id in ids} for q in queries}
qrels_sha=hashlib.sha256(json.dumps(qrels,ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest()

unit=load(SOURCE/'evidence/prepared-rrf-tests/RECEIPT.json')
assert unit['exitCode']==0 and unit['counts']=={'pass':19,'fail':0,'skip':0}
assert all(digest(SOURCE/name)==value for name,value in unit['files'].items())
tap=(SOURCE/'evidence/prepared-rrf-tests/node-test.tap').read_text(encoding='utf-8')
assert re.search(r'^# pass 19$',tap,re.M) and re.search(r'^# fail 0$',tap,re.M) and re.search(r'^# skipped 0$',tap,re.M)
source_anchors={
 'main_real_sdk_no_injected_double':{'file':'main.mjs','lines':line_of('main.mjs','createBridge({ connection, onSqlEvent })')},
 'api_log_emitter':{'file':'main.mjs','lines':line_of('main.mjs',"evidenceLevel: 'public-sdk-api'")},
 'native_runtime_pinned_base':{'file':'main.mjs','lines':line_of('main.mjs','469a55dc84ea7a9e077161a8b454871a9adaff35')},
 'embedding_function_null':{'file':'bridge.mjs','lines':line_of('bridge.mjs','embeddingFunction: null')},
 'prepared_execute':{'file':'bridge.mjs','lines':line_of('bridge.mjs','await execute(sql, params)')},
 'parameter_pack_hash':{'file':'bridge.mjs','lines':line_of('bridge.mjs','parameterSha256: fingerprint(params)')},
 'query_text_not_rewritten':{'file':'public/benchmark.mjs','lines':line_of('public/benchmark.mjs','text: query.query, embedding: embedded.value.embeddings[0]')},
 'worker_real_encoder':{'file':'public/embedding-worker.js','lines':line_of('public/embedding-worker.js',"await encoder(batch, { pooling: 'mean', normalize: true })")},
}
assert all(v['lines'] for v in source_anchors.values())
prepared=(SOURCE/'prepared-rrf.mjs').read_text(encoding='utf-8')
query_sql=prepared.split('const sql = `',1)[1].split('`.trim();',1)[0]
assert query_sql.count('?')==7 and query_sql.count('RANK() OVER')==2
assert 'FULL JOIN' in query_sql and 'APPROXIMATE LIMIT ?' in query_sql
assert 'ON f.\\`__pk_increment\\` = v.\\`__pk_increment\\`' in query_sql
assert query_sql.count('IFNULL(1 / (')==2 and query_sql.count(' + 60)')==2
assert 'ROUND(1 - cosine_distance' in query_sql and ' / 2, 8)' in query_sql
assert 'params: [text, text, FTS_LIMIT, vector, vector, WINDOW_SIZE, topK]' in prepared
assert 'const WINDOW_SIZE = 50' in prepared and 'const FTS_LIMIT = WINDOW_SIZE * 20' in prepared
assert 'rank' not in prepared.split('export function preparedRrfResults',1)[1].lower().replace('database order','')
run_start=datetime.fromisoformat('2026-11-01T01:00:30.141+00:00')
run_end=datetime.fromisoformat('2026-11-01T01:04:54.859+00:00')
assert all(run_start<=datetime.fromisoformat(v['at'].replace('Z','+00:00'))<=run_end for v in events)

assert digest(EVENT_FILE)==raw_sha
report={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'scope':'Read-only saved API/source/resource audit; no UI/browser/DB/model invocation; writes confined to this Temp directory','commit':COMMIT,'head_before':head_before,'head_after':git('rev-parse','HEAD').decode().strip(),'git_status':git('status','--porcelain=v1').decode(),'tracked_stepfun_blob_count':len(tracked),'all_tracked_files_exact_raw_git_blob_match':all(v['exact_raw_match'] for v in tracked),'all_tracked_files_match_blob_raw_or_crlf_normalized':True,'raw_crlf_only_differences':[v['path'] for v in tracked if not v['exact_raw_match']],'tracked_files':tracked,'events':{'path':str(EVENT_FILE),'sha256':raw_sha,'bytes':len(raw),'first':events[0]['at'],'last':events[-1]['at'],'total':240,'start':120,'complete':120,'all_start_complete_paired':True,'all_completed_revision':1,'all_completed_count':5,'all_complete_hashes_present_64hex':True,'all_transport':'embedded','evidenceLevel':'public-sdk-api','by_mode':by_mode,'mode_mapping_provenance':'Parent relay of normal read-only DOM run77153f14-da1b-4e20-b6b9-d5d033b1c4f5, not independently read by this agent'},'dependencies':dependencies,'resource_receipt':{'sha256':digest(SOURCE/'evidence/resource-acquisition/receipt.json'),'fixed_model':receipt['plan']['model'],'fixed_revision':receipt['plan']['revision'],'transformers':'3.8.1','onnxruntime_web':receipt['plan']['onnxruntime_web'],'all12_live_resource_hashes_match':True,'resources':resources,'profiles':profiles,'runtime_bytes':measured['runtime_asset_bytes'],'scope':'File/receipt provenance, not actual GPU internal precision or new inference observation'},'dataset':{'files':datasets,'qrelsSha256':qrels_sha,'scope':'Matches pre-run synthetic AI-reviewed frozen files; not official/human gold. Parent must compare normal-DOM manifest values if not already done.'},'db_side_rrf_static_checks':{'question_placeholders':7,'SQL_rank_windows':2,'full_join_hidden_pk':True,'fts_limit':1000,'ann_limit':50,'rank_constant':60,'topK_bound':True,'client_sort_or_fusion':False,'scope':'Source inspection and checked construction signatures; no DB invocation'},'parent_run_binding':{'runId':'77153f14-da1b-4e20-b6b9-d5d033b1c4f5','parent_read_window':['2026-11-01T01:00:30.141Z','2026-11-01T01:04:54.859Z'],'all240_events_within_window':True,'DOM_independently_read_by_this_agent':False},'existing_pure_test_receipt':{'counts':unit['counts'],'source_hashes_match_current':True,'raw_tap_count_lines_match':True,'tests_rerun_by_this_audit':False},'source_anchors':source_anchors,'limits':['API completion events are emitted after public SDK execute returns and parser succeeds; not network wire trace or engine plan instrumentation.','Raw query text, query ID and vectors are not in this API log. Parameter pack hashes are present but were not independently recomputed from browser input.','Collection IDs are not logged, so per-KB statement hashes cannot be independently regenerated here from the concrete table identifier.','Current tracked content normalized CRLF-to-LF matches c4; two recorded raw byte differences are line endings only. Event emitter schema and timestamps are consistent, but the log has no cryptographic process/module-at-launch attestation.','Events do not contain inference backend/dtype or GPU kernel precision; mode labels come only from the parent-relayed DOM mapping.','Errors before hybrid-api-start are outside this event inventory; matched starts/completes do not establish complete HTTP failure coverage.','Installed dependency package metadata matches lock versions; this round did not independently re-download npm archives or audit every node_modules/native DLL byte.','No browser/profile/storage/DOM/report reading, model execution, DB reads/queries, UI control, or product writes occurred.']}
(OUT/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'out':str(OUT),'source_commit':COMMIT,'tracked_files':len(tracked),'tracked_raw_matches':sum(v['exact_raw_match'] for v in tracked),'tracked_match_raw_or_crlf_normalized':len(tracked),'API_complete':120,'four_KBs_complete':[v['complete'] for v in by_mode.values()],'resources':len(resources),'event_sha256':raw_sha,'dataset':datasets,'qrelsSha256':qrels_sha},ensure_ascii=False,indent=2))
