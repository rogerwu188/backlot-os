#!/usr/bin/env python3
import hashlib,importlib.util,json,os,subprocess,sys,tempfile,time,unittest
from pathlib import Path
PKG=Path(__file__).resolve().parents[1]
def mod(n,f):s=importlib.util.spec_from_file_location(n,PKG/f);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
W=mod('sem17_worker','file_worker.py');D=mod('sem17_disp','dispatcher.py');C=mod('sem17_commit','commit_step.py');P=mod('portable_wakeup','portable_wakeup.py');ROLES=W.ROLES;KEYS=C.KEYS
def canon(o):return json.dumps(o,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def task(role='producer',tid='t',**extra):
 o={'schema':'qingshan.task.v1','task_id':tid,'dispatch_id':'d','accepted_run_id':'r','recovery_fence':'f','role':role,'phase':'RUN','cursor':22 if role=='writer' else 0,'payload':{'evidence':['MARKER']}};o.update(extra);o['task_sha']=W.sha(W.canon({k:v for k,v in o.items() if k!='task_sha'}).encode());return o
def enqueue(root,o):p=Path(root)/'queue_v2.0.17'/o['role']/'inbox'/(o['task_id']+'.json');p.parent.mkdir(parents=True,exist_ok=True);p.write_text(canon(o));return p
def result(root,role,tid):
 rr=Path(root)/'queue_v2.0.17'/role;i=json.loads((rr/'semantic_requests'/(tid+'.json')).read_text());o={'work_item_sha':i['work_item_sha'],'tool_result_status':'complete','semantic_result':{'marker':'MARKER'},'evidence_links':[{'source':'MARKER'}]};p=rr/'semantic_results'/(tid+'.json');p.write_text(canon(o))
class FileNative(unittest.TestCase):
 def setUp(self):self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name)
 def tearDown(self):self.t.cleanup()
 def test_01_five_role_isolation(self):
  W.init(self.root)
  self.assertEqual(set(ROLES),{'producer','writer','pipeline','editor','audit'});self.assertEqual(len({(self.root/'queue_v2.0.17'/r/'locks/worker.lock').parent for r in ROLES}),5)
 def test_02_offsets(self):self.assertEqual(W.OFFSETS,{'producer':0,'writer':12,'pipeline':24,'editor':36,'audit':48})
 def test_03_independent_pid_heartbeat_lock_channels(self):
  W.init(self.root)
  for r in ROLES:
   rr=self.root/'queue_v2.0.17'/r
   self.assertTrue(all((rr/x).is_dir() for x in ('pids','heartbeat','locks','inbox','outbox','receipts','deadletter')))
 def test_04_producer_not_spof(self):
  enqueue(self.root,task('producer','p',payload={'draft':{}}));enqueue(self.root,task('editor','e'));self.assertEqual(W.tick(self.root,'producer')['status'],'FAILED');self.assertEqual(W.tick(self.root,'editor')['status'],'WAITING_AGENT_RESULT')
 def test_05_tool_result_empty_blocked(self):
  enqueue(self.root,task('audit','a'));W.tick(self.root,'audit');rr=self.root/'queue_v2.0.17/audit';(rr/'semantic_results/a.json').write_text('');self.assertEqual(W.tick(self.root,'audit')['status'],'ROLE_TOOL_CHANNEL_BLOCKED');self.assertTrue((rr/'running/a.json').exists())
 def test_06_missing_result_timeout_recovery(self):
  enqueue(self.root,task('pipeline','p'));W.tick(self.root,'pipeline');rr=self.root/'queue_v2.0.17/pipeline';os.utime(rr/'semantic_requests/p.json',(0,0));self.assertEqual(W.tick(self.root,'pipeline',timeout=1)['status'],'ROLE_TOOL_CHANNEL_BLOCKED');self.assertTrue((rr/'checkpoints/p.json').exists())
 def test_07_restart_resume_same_task(self):
  enqueue(self.root,task('editor','x'));W.tick(self.root,'editor');h1=json.loads((self.root/'queue_v2.0.17/editor/semantic_requests/x.json').read_text())['work_item_sha'];W.tick(self.root,'editor');h2=json.loads((self.root/'queue_v2.0.17/editor/semantic_requests/x.json').read_text())['work_item_sha'];self.assertEqual(h1,h2)
 def test_08_duplicate_tick_idempotent(self):
  enqueue(self.root,task('audit','x'));W.tick(self.root,'audit');result(self.root,'audit','x');self.assertEqual(W.tick(self.root,'audit')['status'],'DONE');self.assertEqual(W.tick(self.root,'audit')['status'],'NOOP');self.assertEqual(len(list((self.root/'queue_v2.0.17/audit/receipts').glob('x.done.json'))),1)
 def test_09_same_identity_resume(self):
  o=task('writer','ch482');enqueue(self.root,o);W.tick(self.root,'writer');cp=json.loads((self.root/'queue_v2.0.17/writer/checkpoints/ch482.json').read_text());self.assertEqual([cp[k] for k in ('task_id','dispatch_id','accepted_run_id','recovery_fence','cursor')],['ch482','d','r','f',22])
 def test_10_no_payload_draft(self):enqueue(self.root,task('pipeline','d',payload={'draft':1}));self.assertEqual(W.tick(self.root,'pipeline')['status'],'FAILED')
 def test_11_local_probe_before_role(self):enqueue(self.root,task('editor','e'));W.tick(self.root,'editor');self.assertEqual(json.loads((self.root/'queue_v2.0.17/editor/receipts/local_tool_probe.json').read_text())['status'],'PASS')
 def test_12_valid_commit_advances_cursor(self):enqueue(self.root,task('producer','p'));W.tick(self.root,'producer');result(self.root,'producer','p');W.tick(self.root,'producer');self.assertEqual(json.loads((self.root/'queue_v2.0.17/producer/checkpoints/p.json').read_text())['cursor'],1)
 def test_13_invalid_result_no_cursor(self):enqueue(self.root,task('producer','p'));W.tick(self.root,'producer');rr=self.root/'queue_v2.0.17/producer';(rr/'semantic_results/p.json').write_text('{}');W.tick(self.root,'producer');self.assertEqual(json.loads((rr/'checkpoints/p.json').read_text())['cursor'],0)
 def test_14_shared_disk_only(self):s=(PKG/'PRODUCER_TOOL_RESULT_RECOVERY.md').read_text()+(PKG/'file_worker.py').read_text();self.assertIn('sessions_list',s);self.assertNotIn('sessions_send(',s);self.assertNotIn('sessions_list(',s)
 def test_15_supervisor_five_processes(self):s=(PKG/'worker_supervisor.py').read_text();self.assertIn('for r in ROLES',s);self.assertIn('Popen',s)
 def test_16_scheduler_fallback(self):s=(PKG/'scheduler_detect.py').read_text();self.assertIn('openclaw_local_scheduler',s);self.assertIn('package_worker_supervisor',s)
 def test_17_install_idempotent(self):
  cmd=[sys.executable,str(PKG/'install.py'),'--factory-root',str(self.root),'--runtime-root',str(self.root/'rt'),'--mode','candidate'];subprocess.check_call(cmd,stdout=subprocess.DEVNULL);subprocess.check_call(cmd,stdout=subprocess.DEVNULL);self.assertTrue((self.root/'rt/queue_v2.0.17/install_receipt.json').exists())
 def test_18_upgrade_preserves_writer_copy_and_source(self):
  src=self.root/'src';p=src/'queue_v2.0.16/writer/running/ch482.json';p.parent.mkdir(parents=True);o=task('writer','ch482');p.write_text(canon(o));before=p.read_bytes();base=self.root/'i';subprocess.check_call([sys.executable,str(PKG/'upgrade.py'),'--candidate',str(PKG),'--install-root',str(base),'--writer-source-root',str(src)]);self.assertEqual(p.read_bytes(),before);q=base/'runtime/queue_v2.0.17/writer/running/ch482.json';self.assertEqual(json.loads(q.read_text())['cursor'],22)
 def test_19_rollback_preserves_inflight(self):
  b=self.root/'i';subprocess.check_call([sys.executable,str(PKG/'upgrade.py'),'--candidate',str(PKG),'--install-root',str(b)]);q=b/'runtime/queue_v2.0.17/writer/running';q.mkdir(parents=True);(q/'x').write_text('x');subprocess.check_call([sys.executable,str(PKG/'rollback.py'),'--install-root',str(b)]);self.assertTrue((q/'x').exists())
 def writer_dispatch(self):
  o={'schema':'qingshan.writer.task.v1','task_id':'w','role':'writer','phase':'DRAFT_FULL_FACT','payload':{'evidence':['MARKER evidence']}};o['task_sha']=hashlib.sha256(canon(o).encode()).hexdigest();p=self.root/'queue_v2.0.17/writer/inbox/w.json';p.parent.mkdir(parents=True);p.write_text(canon(o));r=D.dispatch(self.root);return r,json.loads(Path(r['path']).read_text())
 def good11(self,i):
  link={'source_index':i['evidence'][0]['source_index'],'source_hash':i['evidence'][0]['source_hash'],'evidence_excerpt':'MARKER'};o={'n':1,'title':'MARKER','summary':'MARKER','characters':['MARKER'],'locations':['MARKER'],'key_events':['MARKER'],'new_setups':['MARKER'],'payoffs':['MARKER'],'powers_items':['MARKER'],'time_weather':'MARKER','cliffhanger':'MARKER'};o['evidence_links']={k:[link] for k in KEYS};o['model_output_provenance']='current_writer_agent';return o
 def test_20_writer_work_item_max2(self):
  r,i=self.writer_dispatch();self.assertLessEqual(len(i['evidence']),2)
 def test_21_writer_11key_evidence(self):
  r,i=self.writer_dispatch();o=self.good11(i);del o['evidence_links']['title'];p=self.root/'o';p.write_text(canon(o));self.assertRaises(ValueError,C.commit,self.root,r['path'],p)
 def test_22_writer_cursor_valid_only(self):
  r,i=self.writer_dispatch();cp=self.root/'queue_v2.0.17/writer/checkpoints/w.json';p=self.root/'o';p.write_text('{}');self.assertRaises(ValueError,C.commit,self.root,r['path'],p);self.assertEqual(json.loads(cp.read_text())['resume_cursor'],0);p.write_text(canon(self.good11(i)));C.commit(self.root,r['path'],p);self.assertEqual(json.loads(cp.read_text())['resume_cursor'],1)
 def test_23_writer_marker_propagates(self):
  r,i=self.writer_dispatch();p=self.root/'o';p.write_text(canon(self.good11(i)));C.commit(self.root,r['path'],p);self.assertIn('MARKER',(self.root/'queue_v2.0.17/writer/artifacts/w.partial_facts.json').read_text())
 def test_24_activation_forbidden_templates(self):
  for r in ROLES:self.assertTrue(json.loads((PKG/'roles'/r/'cron-template.json').read_text())['activation_forbidden'])
 def test_25_no_live_or_cron_mutation_code(self):
  s=''.join((PKG/f).read_text() for f in ('install.py','upgrade.py','rollback.py'));self.assertNotIn('cron update',s);self.assertNotIn('openclaw cron',s);self.assertIn("'cron_modified':False",s)
 def test_26_diagnostic_packaged(self):self.assertIn('ROLE_TOOL_CHANNEL_BLOCKED',(PKG/'PRODUCER_TOOL_RESULT_RECOVERY.md').read_text())
 def test_27_five_agent_templates(self):self.assertTrue(all((PKG/'roles'/r/'ISOLATED_AGENT_TICK.md').exists() for r in ROLES))
 def test_28_producer_only_file_scheduler(self):self.assertIn('Producer only schedules files',(PKG/'PRODUCER_TOOL_RESULT_RECOVERY.md').read_text())
 def test_29_artifact_before_receipt(self):enqueue(self.root,task('audit','a'));W.tick(self.root,'audit');result(self.root,'audit','a');W.tick(self.root,'audit');rr=self.root/'queue_v2.0.17/audit';x=json.loads((rr/'receipts/a.done.json').read_text());self.assertEqual(W.sha(Path(x['artifact']).read_bytes()),x['artifact_sha'])
 def test_30_activation_manifest_forbidden(self):self.assertTrue(json.loads((PKG/'INSTALL_ACTIVATION.json').read_text())['activation_forbidden'])
 def wake_config(self,command=None):
  cfg={'schema':'backlotos.portable_wakeup.config.v1','agent_id':'test-line','interval_seconds':600,'state_dir':'wake-state','wake_command':command or [sys.executable,'-c','import os; print(os.environ["BACKLOTOS_WAKE_RUN_KEY"])'],'safety_policy':{'paid_submission_forbidden':True,'browser_and_platform_actions_forbidden':True}}
  p=self.root/'wake.json';p.write_text(canon(cfg));return p
 def test_31_portable_wakeup_same_slot_is_idempotent(self):
  p=self.wake_config();a=P.run_once(p,now=1200);b=P.run_once(p,now=1201);self.assertEqual(a['status'],'PASS');self.assertEqual(b['status'],'NOOP_ALREADY_WOKEN');self.assertEqual(a['run_key'],b['run_key'])
 def test_32_portable_wakeup_persists_intent_and_fence(self):
  p=self.wake_config();a=P.run_once(p,now=1200);b=P.run_once(p,now=1800);state=json.loads((self.root/'wake-state/state.json').read_text());self.assertEqual((a['fencing_token'],b['fencing_token'],state['fencing_token']),(1,2,2));self.assertEqual(len(list((self.root/'wake-state/receipts').glob('*.json'))),2)
 def test_33_portable_wakeup_failure_not_replayed_same_slot(self):
  p=self.wake_config([sys.executable,'-c','raise SystemExit(7)']);a=P.run_once(p,now=1200);b=P.run_once(p,now=1202);self.assertEqual(a['status'],'FAIL');self.assertEqual(b['status'],'NOOP_ALREADY_WOKEN')
 def test_34_portable_wakeup_requires_safety_policy(self):
  p=self.wake_config();o=json.loads(p.read_text());o['safety_policy']['paid_submission_forbidden']=False;p.write_text(canon(o));self.assertRaises(ValueError,P.run_once,p,1200)
if __name__=='__main__':unittest.main(verbosity=2)
