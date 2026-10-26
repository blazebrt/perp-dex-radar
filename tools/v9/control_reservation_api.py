"""Narrow authenticated GitHub transport for A6 reservation orchestration.

Constructing the client makes no request. No CLI, workflow trigger or credential
lookup is provided. Callers supply a runner token; errors never include response
bodies, request headers or transport exception text. Mutations are never retried.
"""
import json
import re
import urllib.error
import urllib.request
from tools.v9.control_reservation import MissingRef,REPO,REF,REF_PATH

LIMIT=1024*1024


class ReservationAPIError(RuntimeError):pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        raise ReservationAPIError('GitHub reservation redirect refused')


class GitHubReservationAPI:
    def __init__(self,token):
        if not isinstance(token,str) or not token or any(c.isspace() for c in token):
            raise ValueError('nonempty runner token required')
        self._token=token
        self._opener=urllib.request.build_opener(NoRedirect())

    def __call__(self,method,path,body):
        get_ok=path==REF_PATH or re.fullmatch(re.escape(REPO)+r'/git/(commits|trees|blobs)/[0-9a-f]{40}',path)
        post_ok=path in [REPO+'/git/'+kind for kind in ('trees','commits','refs')]
        if method=='GET' and get_ok and body is None:data=None
        elif method=='POST' and post_ok and isinstance(body,dict):
            if path.endswith('/refs') and (set(body)!={'ref','sha'} or body['ref']!=REF or
                not isinstance(body['sha'],str) or not re.fullmatch('[0-9a-f]{40}',body['sha'])):
                raise ValueError('only the fixed reservation ref may be created')
            if path.endswith('/commits') and body.get('parents')!=[]:
                raise ValueError('only orphan reservation commits may be created')
            if path.endswith('/trees'):
                entries=body.get('tree')
                if set(body)!={'tree'} or not isinstance(entries,list) or len(entries)!=1 or not isinstance(entries[0],dict) or any(
                    entries[0].get(k)!=v for k,v in dict(path='reservation.json',mode='100644',type='blob').items()) or set(entries[0])!={'path','mode','type','content'} or not isinstance(entries[0]['content'],str):
                    raise ValueError('only a reservation-only tree may be created')
            data=json.dumps(body,allow_nan=False,separators=(',',':')).encode()
            if len(data)>LIMIT:raise ValueError('reservation request too large')
        else:raise ValueError('unsupported reservation API operation')
        request=urllib.request.Request('https://api.github.com'+path,data=data,method=method,headers={
            'Authorization':'Bearer '+self._token,'Accept':'application/vnd.github+json',
            'X-GitHub-Api-Version':'2022-11-28','Content-Type':'application/json','User-Agent':'perp-dex-radar-a6-reservation'})
        try:
            with self._opener.open(request,timeout=30) as response:
                expected=200 if method=='GET' else 201
                if response.status!=expected:raise ReservationAPIError('unexpected GitHub reservation response status')
                raw=response.read(LIMIT+1)
        except urllib.error.HTTPError as error:
            code=error.code;error.close()
            if code==404 and method=='GET' and path==REF_PATH:
                raise MissingRef('reservation ref GET returned 404') from None
            raise ReservationAPIError('GitHub reservation HTTP '+str(code)) from None
        except (urllib.error.URLError,OSError,TimeoutError):
            raise ReservationAPIError('GitHub reservation transport failed; inspect before retrying') from None
        if len(raw)>LIMIT:raise ReservationAPIError('GitHub reservation response too large')
        def unique(items):
            result={}
            for key,value in items:
                if key in result:raise ValueError('duplicate key')
                result[key]=value
            return result
        def invalid(value):raise ValueError('nonfinite JSON')
        try:
            result=json.loads(raw,object_pairs_hook=unique,parse_constant=invalid)
            if not isinstance(result,dict):raise ValueError('object required')
        except (ValueError,UnicodeError):raise ReservationAPIError('invalid GitHub reservation JSON') from None
        return result
