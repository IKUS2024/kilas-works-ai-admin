import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ.pop('DATABASE_URL',None)
import db
from kilas_whatsapp_runtime_cases import RuntimeCases

class RuntimeSQLiteTests(RuntimeCases,unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        stub=patch.object(db,'SQLITE_PATH',str(Path(temp.name)/'runtime.db'));stub.start();self.addCleanup(stub.stop)
        self.setup_runtime()

if __name__=='__main__': unittest.main()
