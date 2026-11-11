import os, unittest
from unittest.mock import patch
import sqlserver_connector as m
class ConnectorTests(unittest.TestCase):
 def test_identifier(self):
  for x in ("dbo;DROP TABLE x","x.y","x]","a b",""):
   with self.assertRaises(ValueError):m.safe_identifier(x)
 def test_domain_guard(self):
  with self.assertRaises(ValueError):m.fetch("users")
 def test_pagination_guard(self):
  with self.assertRaises(ValueError):m.fetch("assets",501)
 def test_missing_credentials(self):
  with patch.dict(os.environ,{},clear=True):
   with self.assertRaises(RuntimeError):m.engine()
if __name__=='__main__':unittest.main()
