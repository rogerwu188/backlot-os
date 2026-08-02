#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from worker_core import tick
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--once',action='store_true',required=True);a=p.parse_args();tick(a.root,'pipeline')
