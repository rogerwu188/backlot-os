#!/usr/bin/env python3
import argparse,json,os,tempfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--shared-root');a=p.parse_args();root=Path(a.shared_root or os.environ.get('QINGSHAN_FACTORY_SHARED_ROOT',Path.home()/'.openclaw/shared/ai-drama-factory')).expanduser().resolve();root.mkdir(parents=True,exist_ok=True);fd,t=tempfile.mkstemp(prefix='.probe-',dir=root);os.write(fd,b'probe');os.fsync(fd);os.close(fd);dst=Path(t+'.renamed');os.replace(t,dst);ok=dst.read_bytes()==b'probe';dst.unlink();print(json.dumps({'resolved_shared_root':str(root),'read_write':ok,'same_directory_atomic_rename':ok},sort_keys=True))
