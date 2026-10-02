"""中身（スケジューラーを持つプロセス）を利用者ごとに1つにする錠（lib/navi_instance.py）。

ブラウザ版とデスクトップ版を同じPCで両方起こしても、自動実行が二重に走らないことを確かめる。
本物の別プロセスで錠を取り合う。実行: python -m unittest tests.test_instance -v
"""
import json,os,subprocess,sys,tempfile,time,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'lib'))
import navi_instance

HOLD=r'''
import sys,time;sys.path.insert(0,sys.argv[1])
import navi_instance
lock=navi_instance.acquire(sys.argv[2],sys.argv[3])
print('locked',flush=True)
if sys.argv[4]=='crash':
 import os;os._exit(3)        # 後始末をせずに落ちる
time.sleep(60)
'''

class InstanceLockTest(unittest.TestCase):
 def hold(self,d,mode,how='keep'):
  p=subprocess.Popen([sys.executable,'-c',HOLD,str(ROOT/'lib'),str(d),mode,how],stdout=subprocess.PIPE,text=True)
  self.assertEqual(p.stdout.readline().strip(),'locked')
  return p

 def test_second_is_refused_with_who_holds_it(self):
  with tempfile.TemporaryDirectory() as d:
   p=self.hold(d,'browser')
   try:
    with self.assertRaises(navi_instance.InstanceBusy) as cm:navi_instance.acquire(d,'desktop')
    self.assertEqual(cm.exception.holder.get('mode'),'browser')
    self.assertEqual(cm.exception.holder.get('pid'),p.pid)
    self.assertIn('ブラウザ版がすでに動いています',str(cm.exception))
   finally:
    p.kill();p.wait();p.stdout.close()

 def test_released_when_holder_exits(self):
  with tempfile.TemporaryDirectory() as d:
   p=self.hold(d,'desktop');p.kill();p.wait();p.stdout.close()
   lock=navi_instance.acquire(d,'browser');lock.release()

 def test_released_when_holder_crashes(self):
  """後始末をせずに落ちても（DLLの異常終了と同じ）、錠は OS が外す。二度と起動できない、にはならない。"""
  with tempfile.TemporaryDirectory() as d:
   p=self.hold(d,'desktop','crash');p.wait();p.stdout.close()
   self.assertEqual(p.returncode,3)
   lock=navi_instance.acquire(d,'browser');lock.release()

 def test_separate_users_do_not_block_each_other(self):
  """錠は利用者ごとの置き場（LOCALAPPDATA\\DataRelay\\runtime）にある。別の置き場なら取り合わない。"""
  with tempfile.TemporaryDirectory() as a,tempfile.TemporaryDirectory() as b:
   la=navi_instance.acquire(a,'browser');lb=navi_instance.acquire(b,'desktop')
   la.release();lb.release()
