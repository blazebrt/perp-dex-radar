import base64
import json
import unittest
from tools.v9 import control_reservation as R
from tests.test_v9_control_resource_gate import report,capacity


class Reservation(unittest.TestCase):
    def setUp(self):
        self.calls=[];self.exists=False;self.raw=None;self.race=False;self.bad_blob=False
        self.source='a'*40;self.commit='b'*40;self.tree='c'*40
        self.qualification=json.dumps(report(self.source,R.P.INPUT_HASH,R.sha((R.P.ROOT/R.P.PROTOCOL).read_bytes()))).encode()

    def api(self,method,path,body):
        self.calls.append((method,path,body))
        if path==R.REF_PATH:
            if not self.exists:raise R.MissingRef()
            return dict(ref=R.REF,object=dict(sha=self.commit))
        if method=='POST' and path.endswith('/trees'):
            self.raw=body['tree'][0]['content'].encode();return dict(sha=self.tree)
        if method=='POST' and path.endswith('/commits'):
            self.assertEqual(body['parents'],[]);return dict(sha=self.commit)
        if method=='POST' and path.endswith('/refs'):
            if self.race:self.exists=True;raise RuntimeError('422 ref exists')
            self.exists=True;return {}
        if '/commits/' in path:return dict(parents=[],tree=dict(sha=self.tree))
        if '/trees/' in path:return dict(truncated=False,tree=[dict(path='reservation.json',mode='100644',type='blob',sha='d'*40)])
        if '/blobs/' in path:return dict(encoding='base64',content=base64.b64encode(b'changed' if self.bad_blob else self.raw).decode())
        raise AssertionError(path)

    def reserve(self,api=None,attempt='1',cap=None):
        def source_read(source,path):
            self.assertEqual(source,self.source);return (R.P.ROOT/path).read_bytes()
        return R.reserve(api or self.api,source_read,self.source,'123',attempt,self.qualification,
                         R.sha(self.qualification),capacity() if cap is None else cap)

    def test_create_readback_and_repeat_refusal(self):
        result=self.reserve();self.assertEqual(result['reservation_bytes'],self.raw)
        self.assertFalse(result['promotion_authority'])
        saved=json.loads(self.raw);self.assertEqual(saved['resource_qualification_sha256'],R.sha(self.qualification))
        count=len(self.calls)
        with self.assertRaisesRegex(ValueError,'existing reservation'):self.reserve()
        self.assertEqual([m for m,p,b in self.calls[count:]],['GET'])
        self.assertFalse(any(m=='PATCH' for m,p,b in self.calls))

    def test_bad_capacity_and_rerun_make_no_api_calls(self):
        cap=capacity();cap['free_disk_bytes']=1
        with self.assertRaises(ValueError):self.reserve(cap=cap)
        with self.assertRaises(ValueError):self.reserve(attempt='2')
        self.assertEqual(self.calls,[])

    def test_auth_or_network_error_is_not_absence(self):
        def denied(*args):raise PermissionError('403')
        with self.assertRaises(PermissionError):self.reserve(api=denied)
        self.assertIsNone(self.raw)

    def test_concurrent_create_failure_is_not_retried(self):
        self.race=True
        with self.assertRaisesRegex(RuntimeError,'422'):self.reserve()
        self.assertEqual(sum(m=='POST' and p.endswith('/refs') for m,p,b in self.calls),1)
        self.assertTrue(self.exists)

    def test_readback_failure_keeps_reservation_blocking_retry(self):
        self.bad_blob=True
        with self.assertRaisesRegex(ValueError,'bytes mismatch'):self.reserve()
        self.assertTrue(self.exists)
        with self.assertRaisesRegex(ValueError,'existing reservation'):self.reserve()

    def test_unexpected_tip_parents_and_tree_fail_readback(self):
        for target in ('tip','parents','tree'):
            self.setUp()
            def altered(method,path,body):
                result=self.api(method,path,body)
                if method=='GET':
                    if target=='tip' and path==R.REF_PATH:result['object']['sha']='e'*40
                    if target=='parents' and '/commits/' in path:result['parents']=[dict(sha='e'*40)]
                    if target=='tree' and '/trees/' in path:result['truncated']=True
                return result
            with self.subTest(target=target),self.assertRaises(ValueError):self.reserve(api=altered)
            self.assertTrue(self.exists)
