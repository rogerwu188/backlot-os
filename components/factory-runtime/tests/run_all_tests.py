#!/usr/bin/env python3
import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
loader=unittest.TestLoader();suite=unittest.TestSuite()
for name in ('file_native_tests','activation_bridge_tests'):suite.addTests(loader.loadTestsFromName(name))
r=unittest.TextTestRunner(verbosity=2).run(suite);raise SystemExit(0 if r.wasSuccessful() else 1)
