#!/usr/bin/env python3
import argparse,json,os
from pathlib import Path
from file_worker import atomic,canon
p=argparse.ArgumentParser();p.add_argument('--install-root',required=True);a=p.parse_args();b=Path(a.install_root);r=json.loads((b/'upgrade_receipt.json').read_text());c=b/'candidate-current'
if r.get('previous'):t=b/'.candidate-current.rollback';t.unlink(missing_ok=True);t.symlink_to(r['previous']);os.replace(t,c)
else:c.unlink(missing_ok=True)
atomic(b/'rollback_receipt.json',canon({'rolled_back':True,'inflight_queues_preserved':True,'writer_ch482_preserved':True,'cron_modified':False,'live_modified':False})+'\n')
