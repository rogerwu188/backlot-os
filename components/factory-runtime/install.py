#!/usr/bin/env python3
"""Idempotent candidate installer. Never mutates live cron/tasks; activation remains audit-forbidden."""
import argparse,json,os,shutil,tempfile
from pathlib import Path
from file_worker import init,atomic,canon,ROLES,OFFSETS
from scheduler_detect import detect
p=argparse.ArgumentParser();p.add_argument('--factory-root',required=True);p.add_argument('--runtime-root',required=True);p.add_argument('--mode',choices=['candidate'],required=True);a=p.parse_args()
root=Path(a.runtime_root);init(root);receipt=root/'queue_v2.0.17'/'install_receipt.json'
o={'schema':'qingshan.file_native.install.v1','version':'2.0.17-file-native-workers','mode':'candidate','roles':list(ROLES),'offsets':OFFSETS,'scheduler':detect(),'five_independent_processes':True,'cron_modified':False,'live_modified':False,'activation_forbidden':True,'idempotent':True,'diagnostic':'ROLE_TOOL_CHANNEL_BLOCKED is isolated per role; retry resumes disk checkpoint'}
atomic(receipt,canon(o)+'\n');print(canon(o))
