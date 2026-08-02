#!/usr/bin/env python3
import hashlib,importlib.util,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
PKG=Path(__file__).resolve().parents[1]
def mod(name,file):
 s=importlib.util.spec_from_file_location(name,PKG/file);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
D=mod('sem16_dispatcher','dispatcher.py');C=mod('sem16_commit','commit_step.py');G=mod('sem16_generic_dispatch','semantic_dispatcher.py');GC=mod('sem16_generic_commit','semantic_commit.py')
ROLES=('producer','writer','pipeline','editor','audit');KEYS=C.KEYS
def canon(o):return json.dumps(o,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def writer_task(tid='t1',evidence=None,**payload):
 p={'evidence':['SEM16_UNIQUE_MARKER evidence text'] if evidence is None else evidence};p.update(payload);o={'schema':'qingshan.writer.task.v1','task_id':tid,'role':'writer','phase':'DRAFT_FULL_FACT','payload':p};o['task_sha']=hashlib.sha256(canon(o).encode()).hexdigest();return o
def enqueue(root,o,role='writer'):
 p=Path(root)/'queue_v2.0.17'/role/'inbox'/(o['task_id']+'.json');p.parent.mkdir(parents=True,exist_ok=True);p.write_text(canon(o)+'\n');return p
def output(item,marker='SEM16_UNIQUE_MARKER'):
 link={'source_index':item['evidence'][0]['source_index'],'source_hash':item['evidence'][0]['source_hash'],'evidence_excerpt':marker}
 vals={'n':1,'title':marker+' title','summary':marker+' summary','characters':[marker+' character'],'locations':[marker+' location'],'key_events':[marker+' event'],'new_setups':[marker+' setup'],'payoffs':[marker+' payoff'],'powers_items':[marker+' item'],'time_weather':marker+' day','cliffhanger':marker+' cliff'}
 vals['evidence_links']={k:[dict(link)] for k in KEYS};vals['model_output_provenance']='current_writer_agent';return vals
class SemanticStage3(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
 def tearDown(self):self.tmp.cleanup()
 def dispatch(self,o=None):enqueue(self.root,o or writer_task());r=D.dispatch(self.root);return r,json.loads(Path(r['path']).read_text())
 def test_01_cron_is_agent_instruction_not_pure_exec(self):
  for role in ROLES:
   x=json.loads((PKG/'roles'/role/'cron-template.json').read_text());self.assertEqual(x['payload']['kind'],'agentTurn');self.assertIn('semantic Agent tick',x['payload']['message']);self.assertNotIn('python ',x['payload']['message'])
 def test_02_writer_work_item_max2(self):
  r,i=self.dispatch(writer_task(evidence=['a','b','c']));self.assertLessEqual(len(i['evidence']),2);self.assertEqual(i['next_cursor'],2)
 def test_03_payload_draft_forbidden(self):
  enqueue(self.root,writer_task(draft={'n':1}));self.assertRaisesRegex(ValueError,'draft is forbidden',D.dispatch,self.root)
 def test_04_model_output_required(self):
  r,i=self.dispatch();p=self.root/'empty.json';p.write_text('');self.assertRaisesRegex(ValueError,'non-empty model output required',C.commit,self.root,r['path'],p);self.assertEqual(json.loads((self.root/'queue_v2.0.17/writer/checkpoints/t1.json').read_text())['resume_cursor'],0)
 def test_05_unique_evidence_marker_propagates(self):
  r,i=self.dispatch();p=self.root/'out.json';p.write_text(canon(output(i)));C.commit(self.root,r['path'],p);f=json.loads((self.root/'queue_v2.0.17/writer/artifacts/t1.partial_facts.json').read_text())[0];self.assertIn('SEM16_UNIQUE_MARKER',canon(f));self.assertIn('SEM16_UNIQUE_MARKER',canon(f['evidence_links']))
 def test_06_no_evidence_no_commit(self):
  enqueue(self.root,writer_task(evidence=[]));r=D.dispatch(self.root);self.assertEqual(r['status'],'NO_EVIDENCE');self.assertFalse((self.root/'queue_v2.0.17/writer/artifacts/t1.partial_facts.json').exists())
 def test_07_placeholder_rejected(self):
  r,i=self.dispatch();o=output(i);o['summary']='PENDING';p=self.root/'out.json';p.write_text(canon(o));self.assertRaisesRegex(ValueError,'placeholder',C.commit,self.root,r['path'],p)
 def test_08_11keys_each_have_evidence_links(self):
  r,i=self.dispatch();o=output(i);del o['evidence_links']['title'];p=self.root/'out.json';p.write_text(canon(o));self.assertRaisesRegex(ValueError,'each of 11 keys',C.commit,self.root,r['path'],p)
 def test_09_cursor_advances_only_after_valid_model_output(self):
  r,i=self.dispatch();cp=self.root/'queue_v2.0.17/writer/checkpoints/t1.json';self.assertEqual(json.loads(cp.read_text())['resume_cursor'],0);p=self.root/'bad.json';p.write_text('{}');self.assertRaises(ValueError,C.commit,self.root,r['path'],p);self.assertEqual(json.loads(cp.read_text())['resume_cursor'],0);p.write_text(canon(output(i)));C.commit(self.root,r['path'],p);self.assertEqual(json.loads(cp.read_text())['resume_cursor'],1)
 def test_10_dead_turn_resume(self):
  r,i=self.dispatch(writer_task(evidence=['a','b']));r2=D.dispatch(self.root);i2=json.loads(Path(r2['path']).read_text());self.assertEqual(i2['cursor'],0);self.assertEqual(i2['work_item_sha'],i['work_item_sha'])
 def test_11_CAS_conflict_rejected(self):
  r,i=self.dispatch();cp=self.root/'queue_v2.0.17/writer/checkpoints/t1.json';x=json.loads(cp.read_text());x['updated_at']=0;cp.write_text(canon(x));p=self.root/'out.json';p.write_text(canon(output(i)));self.assertRaisesRegex(ValueError,'CAS rejected',C.commit,self.root,r['path'],p)
 def test_12_artifact_before_done(self):
  role='editor';rr=self.root/'queue_v2.0.17'/role;o={'task_id':'g1','dispatch_id':'d','accepted_run_id':'a','role':role,'phase':'EDIT','payload':{'evidence':'x'}};o['task_sha']=G.sha(G.canon({k:v for k,v in o.items() if k!='task_sha'}).encode());enqueue(self.root,o,role);r=G.dispatch(self.root,role);i=json.loads(Path(r['path']).read_text());mp=self.root/'m.json';mp.write_text(canon({'work_item_sha':i['work_item_sha'],'semantic_result':{'marker':'SEM16_UNIQUE_MARKER'},'evidence_links':[{'marker':'SEM16_UNIQUE_MARKER'}],'model_output_provenance':'current_role_agent','cursor':1}));x=GC.main(self.root,r['path'],mp);self.assertTrue(Path(x['artifact']).exists());self.assertFalse((rr/'running/g1.json').exists())
 def test_13_six_phases_unchanged(self):self.assertEqual(('READ_EVIDENCE','MERGE_EVIDENCE','DRAFT_FULL_FACT','VALIDATE','APPEND_ATOMIC','NEXT_CHAPTER'),tuple(mod('sem16_worker','worker_core.py').OFFICIAL_WRITER_PHASES))
 def test_14_legacy_conflict_migration_plan(self):
  s=(PKG/'MIGRATION_PLAN.md').read_text();self.assertIn('Never create a duplicate cron',s);self.assertIn('in place',s);self.assertIn('Activation is forbidden',s)
 def test_15_five_role_agent_ticks(self):
  self.assertTrue(all((PKG/'roles'/r/'ISOLATED_AGENT_TICK.md').is_file() for r in ROLES));self.assertEqual(G.ROLES,('producer','pipeline','editor','audit'))
 def test_16_public_installer(self):
  self.assertIn("choices=['candidate']",(PKG/'install.py').read_text());self.assertFalse(json.loads((PKG/'PUBLIC_INSTALL_MANIFEST.json').read_text())['activation_allowed'])
 def test_17_upgrade_preserves_live(self):
  b=self.root/'install';(b/'live').mkdir(parents=True);(b/'live/sentinel').write_text('KEEP');subprocess.check_call([sys.executable,str(PKG/'upgrade.py'),'--candidate',str(PKG),'--install-root',str(b)],stdout=subprocess.DEVNULL);self.assertEqual((b/'live/sentinel').read_text(),'KEEP')
 def test_18_rollback(self):
  b=self.root/'install';subprocess.check_call([sys.executable,str(PKG/'upgrade.py'),'--candidate',str(PKG),'--install-root',str(b)],stdout=subprocess.DEVNULL);subprocess.check_call([sys.executable,str(PKG/'rollback.py'),'--install-root',str(b)],stdout=subprocess.DEVNULL);self.assertFalse((b/'candidate-current').exists());self.assertTrue(json.loads((b/'rollback_receipt.json').read_text())['tasks_preserved'])
 def test_19_v2015_failure_isolation_regression(self):
  old=PKG.parent/'2.0.15-minimal-file-workers';self.assertTrue(old.is_dir());w=mod('sem16_worker_reg','worker_core.py');rt=self.root/'legacy';actual=w.init_runtime(rt);bad={'schema':'qingshan.audit.task.v1','task_id':'bad','role':'audit','phase':'RUN','payload':{}};bad['task_sha']='0'*64;p=Path(actual)/'queue_v2.0.17/audit/inbox/bad.json';p.write_text(w.canon(bad));self.assertEqual(w.tick(rt,'audit')['status'],'FAILED');self.assertFalse(any((Path(actual)/'queue_v2.0.17/editor/done').glob('*')))
if __name__=='__main__':unittest.main(verbosity=2)
