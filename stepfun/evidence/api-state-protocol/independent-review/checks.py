from pathlib import Path
import json,hashlib,collections,re,math
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
read=lambda rel:json.loads((ROOT/rel).read_text(encoding='utf-8'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
run=read('evidence/api-state-protocol/RUN.json');reopen=read('evidence/api-state-protocol/REOPEN.json');binding=read('evidence/api-state-protocol/BINDING.json')
summary=read('evidence/browser-run-77153f14/OBSERVED_SUMMARY.json')
origin='synthetic-one-hot-384-api-state-only-not-model-embeddings'
assert run['status']=='passed-api-state-protocol-only' and reopen['status']=='passed-new-process-read-only-visibility'
assert run['runId']==reopen['runId']=='c30b0a88-d617-4190-ab83-3d2ae3cfd1e1'
assert run['processId']==288788 and reopen['previousProcessId']==run['processId'] and reopen['processId']==288188
assert run['processId']!=reopen['processId']
assert binding['serverRestarted'] is False and binding['servicePidObservedBeforeRun']==291436
for report in (run,reopen):
 assert report['vectorOrigin']==origin and report['browserEmbeddingVerifiedByThisProbe'] is False and report['qualityOrModelPrecisionEvidence'] is False
 assert all(r['outcome']=='response-received' and 200<=r['httpStatus']<300 for r in report['requests'])
 assert report['actualServerCommit']=='not exposed by API; root binds actual running source separately'
 assert report['basedOnApiContract']=='c4f99a1a9c94da7111291f16cafc5eb30ff7c657'
assert sha(ROOT/'evidence/api-state-protocol/reproducer/state-probe.mjs')==binding['driverSha256']
for name,digest in run['fixtures'].items():
 assert reopen['fixtures'][name]==digest
 assert sha(ROOT/f'evidence/api-state-protocol/reproducer/fixtures/{name}.json')==digest
created=run['created'];assert len(created)==2 and all(v['createdThisRun'] for v in created)
owned={v['id']:v for v in created};assert len(owned)==2
assert all(v['label'].startswith('TEST_ONLY_PROTOCOL_SYNTHETIC_'+run['runId']) for v in created)
benchmark_ids={v['kbId'] for v in summary['modes']};assert not set(owned)&benchmark_ids

def classify(req):
 if req['method']=='GET' and req['path']=='/api/health':return 'health'
 if req['method']=='GET' and req['path']=='/api/kbs':return 'registry'
 if req['method']=='POST' and req['path']=='/api/kbs':return 'create'
 match=re.fullmatch(r'/api/kbs/([0-9a-f-]{36})/(import|search)',req['path'])
 assert req['method']=='POST' and match and match[1] in owned
 return match[2]
counts=collections.Counter(classify(v) for v in run['requests'])
assert len(run['requests'])==15 and counts=={'health':1,'registry':1,'create':2,'import':4,'search':7}
assert len(run['importResponses'])==4 and len(run['searchResponses'])==7
state={id:{'revision':0,'ids':set(),'count':0} for id in owned}
imports=iter(run['importResponses']);searches=iter(run['searchResponses'])
for req in run['requests']:
 kind=classify(req)
 assert req['writeIntent']==(kind in {'create','import'})
 if kind=='import':
  row=next(imports);kb=row['kbId'];assert kb in req['path'] and row['ids']==req['documentIds']
  state[kb]['ids'].update(row['ids']);state[kb]['revision']+=1;state[kb]['count']=row['response']['count']
  assert row['response']['revision']==state[kb]['revision'] and row['response']['count']==len(state[kb]['ids'])
 if kind=='search':
  row=next(searches);kb=row['kbId'];assert kb in req['path'] and row['queryText']==req['queryText']
  assert row['revision']==state[kb]['revision'] and len(row['resultIds'])<=50 and len(set(row['resultIds']))==len(row['resultIds'])
  assert set(row['resultIds'])<=state[kb]['ids']
  assert row['countMeaning']=='returned top-K count, NOT database row count'
for id,v in state.items():assert owned[id]['confirmedRevision']==v['revision'] and owned[id]['lastImportObservedCount']==v['count']
assert sorted((v['count'],v['revision']) for v in state.values())==[(2,1),(21,3)]
assert [(v['response']['count'],v['response']['revision']) for v in run['importResponses']]==[(20,1),(21,2),(21,3),(2,1)]
assert 'H21' not in run['searchResponses'][0]['resultIds'] and 'H21' in run['searchResponses'][1]['resultIds']
corpus=read('evidence/api-state-protocol/reproducer/fixtures/corpus.json');mutation=read('evidence/api-state-protocol/reproducer/fixtures/mutations.json')
docs={d['id']:d for d in corpus['documents']};docs.update({d['id']:d for d in mutation['documents']})
for report in (run,reopen):
 for search in report['searchResponses']:
  for id,text in search['requiredBodies'].items():assert text==docs[id]['text'] and id in search['resultIds']
assert not reopen['created'] and not reopen['plannedLabels'] and not reopen['importResponses']
rcount=collections.Counter(classify(v) for v in reopen['requests'])
assert len(reopen['requests'])==6 and rcount=={'health':1,'registry':1,'search':4} and len(reopen['searchResponses'])==4
assert all(v['writeIntent'] is False for v in reopen['requests'])
assert reopen['freshCountAfterReopen'] is None
assert {v['id']:v['count'] for v in reopen['importCountsFromPreviousActualRunNotRecounted']}=={id:v['count'] for id,v in state.items()}
for row in reopen['searchResponses']:
 assert row['revision']==state[row['kbId']]['revision'] and set(row['resultIds'])<=state[row['kbId']]['ids']
 assert len(set(row['resultIds']))==len(row['resultIds']) and len(row['resultIds'])<=50
assert datetime.fromisoformat(run['finishedUtc'].replace('Z','+00:00'))<datetime.fromisoformat(reopen['startedUtc'].replace('Z','+00:00'))

readme=(ROOT/'README.md').read_text(encoding='utf-8');technical=(ROOT/'docs/technical-note.md').read_text(encoding='utf-8')
assert summary['runId']=='77153f14-da1b-4e20-b6b9-d5d033b1c4f5'
assert sum(v['querySamples'] for v in summary['modes'])==120
labels={'fp32-gpu':'FP32 GPU','fp16-gpu':'FP16 GPU','fp32-wasm':'FP32 WASM','q8-wasm':'q8 WASM'}
rows={line.split('|')[1].strip():[v.strip() for v in line.split('|')[2:-1]] for line in readme.splitlines() if line.startswith('| ') and len(line.split('|'))==6}
for v in summary['modes']:
 assert v['querySamples']==30 and v['macroRecallAt5']==v['macroNdcgAt5']==1
 cells=rows[labels[v['id']]]
 assert cells[0]==v['backendReported']+' / '+v['dtypeReported']
 assert cells[1]==f"{v['subsequentReadyMedianMs']:.2f} ms" and cells[2]==f"{v['batch4WallTimeSpeedup']:.3f}×"
 assert f"{v['subsequentReadyMedianMs']:.2f}" in technical
assert 'T_batch1/T_batch4' in readme and 'T_batch1/T_batch4' in technical
for v in summary['comparisons']:
 baseline=next(m for m in summary['modes'] if m['id']==v['baselineId']);candidate=next(m for m in summary['modes'] if m['id']==v['candidateId'])
 assert math.isclose(baseline['subsequentReadyMedianMs']/candidate['subsequentReadyMedianMs'],v['subsequentReadyMedianSpeedup'],rel_tol=1e-12)
 assert f"{v['subsequentReadyMedianSpeedup']:.3f}" in technical
assert summary['fullBrowserRawReportArchived'] is False and summary['gpuKernelPrecisionTrace'] is False and summary['formalPlatformScore'] is None
assert '不是浏览器embedding、UI切库、服务重启或崩溃恢复验证' in readme
assert '服务重启' in technical and '正式得分仍未验收' in technical
paths=['evidence/api-state-protocol/RUN.json','evidence/api-state-protocol/REOPEN.json','evidence/api-state-protocol/BINDING.json','evidence/api-state-protocol/reproducer/state-probe.mjs','evidence/browser-run-77153f14/OBSERVED_SUMMARY.json','README.md','docs/technical-note.md','public/benchmark.mjs']
result={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'scope':'Read-only file/receipt/summary audit only; no probe/test/browser/DB/model rerun','checks_passed':True,'run_request_counts':dict(counts),'run_total_requests':15,'imports_observed_count_revision':[[v['response']['count'],v['response']['revision']] for v in run['importResponses']],'owned_kbs':created,'all_recorded_mutations_only_new_run_kbs':True,'disjoint_from_four_quality_run_kbs':True,'reopen_request_counts':dict(rcount),'reopen_total_requests':6,'run_client_pid':run['processId'],'reopen_client_pid':reopen['processId'],'server_pid_observed_before_run':binding['servicePidObservedBeforeRun'],'server_restart_claimed':False,'reopen_fresh_count':None,'document_bodies_match_frozen_protocol_fixtures':True,'recorded_requests_all_successful':True,'driver_sha_matches_binding':True,'docs_metric_roundings_match_root_transcribed_summary':True,'docs_batch_ratio_direction_corrected':'T_batch1/T_batch4','ready_speedup_ratios':[v['subsequentReadyMedianSpeedup'] for v in summary['comparisons']],'source_files_sha256':{p:sha(ROOT/p) for p in paths},'limits':['Receipt self-consistency and reviewed ownership guards support the recorded action scope, not a network/global-process audit.','The two PIDs are client probe PIDs, not proof of service/database reopen; BINDING explicitly says serverRestarted=false.','Import counts20/21/21/2 were returned during original import; reopen freshCount is null. Top-K lengths are not row counts.','Synthesized one-hot vectors and q8 declaration are API schema/state tests only, not browser inference/quantization/relevance-quality/independent FTS correctness.','Registry identity/revision and all returned metadata were asserted by the bound driver; complete raw registry and metadata payloads are not serialized for independent replay in these receipts.','Documentation values were checked against the compact root DOM transcription and benchmark formulas. No independent DOM/raw-sample median or GPU kernel-precision verification occurred.','Complete browser raw report remains unarchived per supplied summary; docs acknowledge this.']}
(OUT/'audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'actual_checks':'passed','RUN':dict(counts),'REOPEN':dict(rcount),'out':str(OUT),'ratio_direction':'corrected T_batch1/T_batch4','db_browser_probe_tests_rerun':False},ensure_ascii=False,indent=2))
