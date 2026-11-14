import io
import json
import unittest
import urllib.error
from unittest.mock import patch
from tools.v9 import control_reservation_api as A
from tests import test_v9_control_reservation as fixture


class Response(io.BytesIO):
    def __init__(self,raw,status=200):super().__init__(raw);self.status=status


class Transport(unittest.TestCase):
    def setUp(self):
        self.open=patch.object(A.urllib.request,'build_opener');self.factory=self.open.start();self.addCleanup(self.open.stop)
        self.client=A.GitHubReservationAPI('synthetic-secret');self.opener=self.factory.return_value

    def test_fixed_host_headers_timeout_and_no_redirect(self):
        self.opener.open.return_value=Response(b'{"ok":true}')
        self.assertEqual(self.client('GET',A.REF_PATH,None),{'ok':True})
        request=self.opener.open.call_args.args[0]
        self.assertEqual(request.full_url,'https://api.github.com'+A.REF_PATH)
        self.assertEqual(request.get_header('Authorization'),'Bearer synthetic-secret')
        self.assertEqual(self.opener.open.call_args.kwargs,{'timeout':30})
        self.assertIsInstance(self.factory.call_args.args[0],A.NoRedirect)
        with self.assertRaises(A.ReservationAPIError):A.NoRedirect().redirect_request(None,None,302,'',{},'https://elsewhere.invalid')

    def test_ref_404_only_is_absence(self):
        for code,path,error in [(404,A.REF_PATH,A.MissingRef),(403,A.REF_PATH,A.ReservationAPIError),
                                (404,A.REPO+'/git/trees/'+'a'*40,A.ReservationAPIError),(422,A.REF_PATH,A.ReservationAPIError)]:
            self.opener.open.side_effect=urllib.error.HTTPError('url',code,'synthetic-secret',{},io.BytesIO(b'synthetic-secret'))
            with self.subTest(code=code,path=path),self.assertRaises(error) as caught:self.client('GET',path,None)
            self.assertNotIn('synthetic-secret',str(caught.exception))

    def test_mutation_timeout_is_not_retried_or_leaked(self):
        self.opener.open.side_effect=urllib.error.URLError('synthetic-secret')
        with self.assertRaises(A.ReservationAPIError) as caught:self.client('POST',A.REPO+'/git/refs',dict(ref=A.REF,sha='a'*40))
        self.assertEqual(self.opener.open.call_count,1);self.assertNotIn('synthetic-secret',str(caught.exception))

    def test_other_destinations_methods_and_payloads_refused_before_network(self):
        bad=[('PATCH',A.REF_PATH,{}),('GET','https://elsewhere.invalid',None),
             ('POST',A.REPO+'/git/refs',dict(ref='refs/heads/main',sha='a'*40)),
             ('POST',A.REPO+'/git/commits',dict(parents=['a'*40])),
             ('POST',A.REPO+'/git/trees',dict(base_tree='a'*40,tree=[]))]
        for method,path,body in bad:
            with self.subTest(path=path),self.assertRaises(ValueError):self.client(method,path,body)
        self.opener.open.assert_not_called()

    def test_malformed_oversized_or_wrong_status_response_refused(self):
        for raw,status in [(b'{"a":1,"a":2}',200),(b'{"a":NaN}',200),(b'[]',200),(b'bad',200),
                           (b'x'*(A.LIMIT+1),200),(b'{}',302)]:
            self.opener.open.return_value=Response(raw,status)
            with self.subTest(size=len(raw),status=status),self.assertRaises(A.ReservationAPIError):self.client('GET',A.REF_PATH,None)

    def test_orchestrator_integrates_without_real_network(self):
        f=fixture.Reservation();f.setUp()
        def wire(request,timeout):
            path=request.full_url.removeprefix('https://api.github.com')
            try:result=f.api(request.method,path,json.loads(request.data) if request.data else None)
            except A.MissingRef:raise urllib.error.HTTPError(request.full_url,404,'missing',{},io.BytesIO())
            return Response(json.dumps(result).encode(),200 if request.method=='GET' else 201)
        self.opener.open.side_effect=wire
        result=f.reserve(api=self.client)
        self.assertEqual(result['status'],'RESERVATION_CREATED_AND_READ_BACK')
        self.assertEqual(result['reservation_bytes'],f.raw)
