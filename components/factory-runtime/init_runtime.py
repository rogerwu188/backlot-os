#!/usr/bin/env python3
import argparse
from worker_core import init_runtime
p=argparse.ArgumentParser();p.add_argument('--root',required=True);a=p.parse_args();init_runtime(a.root)
