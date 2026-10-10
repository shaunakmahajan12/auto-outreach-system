import os
"""OAuth and read-only MCP adapter reusing the live-verified diagnostic transport."""
import asyncio
import base64
import hashlib
import secrets
import time
import urllib.error
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode, urlsplit
from scripts.inspect_tsenta import ORIGIN, RESOURCE, request, validate_read
from scripts.tsenta_baseline import validate_snapshot
from backend.security import Retryable, Unavailable


def retry_delay(headers):
    value=headers.get('Retry-After','0')
    try:
        return max(0,float(value))
    except ValueError:
        try:
            return max(0,parsedate_to_datetime(value).timestamp()-time.time())
        except (ValueError,TypeError):
            return 0


class Tsenta:
    def __init__(self,secrets_store):
        self.secrets=secrets_store
        self.pending={}
        self.lock=asyncio.Lock()
        self.session_headers=None
        self.sequence=10

    async def http(self,url,data=None,headers=None,form=False):
        try:
            return await asyncio.to_thread(request,url,data,headers,form)
        except urllib.error.HTTPError as error:
            if error.code in (401,403):
                raise Unavailable('Tsenta authorization expired or was denied. Reconnect in Settings.') from None
            if error.code==429:
                raise Retryable('Tsenta rate limited this read. Retry scheduled; recurring polling remains separately controlled.',retry_delay(error.headers)) from None
            if error.code>=500:
                raise Retryable('Tsenta is temporarily unavailable.') from None
            raise Unavailable('Tsenta rejected the read or OAuth request. Reconnect, or check the documented integration.') from None
        except (OSError,TimeoutError):
            raise Retryable('Cannot reach Tsenta. Check your connection and retry.') from None

    async def connect(self):
        protected,_=await self.http(ORIGIN+'/.well-known/oauth-protected-resource/api/v1/mcp')
        metadata,_=await self.http(ORIGIN+'/.well-known/oauth-authorization-server')
        if protected.get('resource')!=RESOURCE or ORIGIN not in protected.get('authorization_servers',[]):
            raise Unavailable('Unexpected Tsenta resource metadata.')
        if metadata.get('issuer')!=ORIGIN or 'S256' not in metadata.get('code_challenge_methods_supported',[]):
            raise Unavailable('Unsupported Tsenta OAuth configuration.')
        for key in ('registration_endpoint','authorization_endpoint','token_endpoint'):
            u=urlsplit(metadata.get(key,''))
            if u.scheme!='https' or u.netloc!='api.autojobs.me' or u.query or u.fragment:
                raise Unavailable('Unexpected OAuth endpoint; connection stopped.')
        redirect=os.getenv('TSENTA_OAUTH_CALLBACK','http://127.0.0.1:8765/api/tsenta/callback')
        if os.getenv('OUTREACH_REMOTE')=='true' and os.getenv('TSENTA_CALLBACK_VERIFIED')!='true':
            raise Unavailable('Remote Tsenta callbacks require provider verification. Set TSENTA_OAUTH_CALLBACK and record verification before enabling sign-in.')
        registration,_=await self.http(metadata['registration_endpoint'],{
            'client_name':'Application Outreach Assistant (local)', 'redirect_uris':[redirect],
            'token_endpoint_auth_method':'none','grant_types':['authorization_code','refresh_token'],'response_types':['code']})
        verifier=secrets.token_urlsafe(64)
        state=secrets.token_urlsafe(32)
        self.pending={state:{'verifier':verifier,'client_id':registration['client_id'],'redirect':redirect,
                             'token_endpoint':metadata['token_endpoint'],'expires':time.time()+600}}
        challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        return metadata['authorization_endpoint']+'?'+urlencode({'response_type':'code','client_id':registration['client_id'],
            'redirect_uri':redirect,'state':state,'code_challenge':challenge,'code_challenge_method':'S256','resource':RESOURCE})

    async def callback(self,state,code):
        pending=self.pending.pop(state,None)
        if not pending or pending['expires']<time.time() or not code:
            raise Unavailable('Sign-in expired or was declined. Start Connect Tsenta again.')
        token,_=await self.http(pending['token_endpoint'],{'grant_type':'authorization_code','code':code,
            'client_id':pending['client_id'],'redirect_uri':pending['redirect'],'code_verifier':pending['verifier'],'resource':RESOURCE},form=True)
        if not token.get('access_token'):
            raise Unavailable('Tsenta did not return an access token.')
        token.update(client_id=pending['client_id'],token_endpoint=pending['token_endpoint'],expires_at=time.time()+float(token.get('expires_in',3600)))
        await asyncio.to_thread(self.secrets.put,'tsenta',token)
        self.session_headers=None

    async def headers(self):
        token=await asyncio.to_thread(self.secrets.get,'tsenta')
        if not token:
            raise Unavailable('Connect Tsenta in Settings to synchronize your account.')
        if token.get('expires_at',0)<time.time()+60:
            if not token.get('refresh_token'):
                raise Unavailable('Tsenta sign-in expired. Reconnect in Settings.')
            fresh,_=await self.http(token['token_endpoint'],{'grant_type':'refresh_token','refresh_token':token['refresh_token'],
                'client_id':token['client_id'],'resource':RESOURCE},form=True)
            token.update(fresh)
            token['expires_at']=time.time()+float(fresh.get('expires_in',3600))
            await asyncio.to_thread(self.secrets.put,'tsenta',token)
            self.session_headers=None
        return {'Authorization':'Bearer '+token['access_token'],'Accept':'application/json, text/event-stream'}

    async def read(self,name,args):
        if name=='get-job-details':
            if set(args)!={'jobId'} or not isinstance(args['jobId'],str) or not args['jobId']:
                raise ValueError('A verified job ID is required')
        else:validate_read(name,args)
        async with self.lock:
            headers=await self.headers()
            if self.session_headers is None:
                initialized,response_headers=await self.http(RESOURCE,{'jsonrpc':'2.0','id':1,'method':'initialize',
                    'params':{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'application-outreach-assistant','version':'1.0'}}},headers)
                if initialized.get('error') or 'result' not in initialized:
                    raise Unavailable('Tsenta MCP initialization failed.')
                self.session_headers={'MCP-Protocol-Version':initialized['result']['protocolVersion']}
                for key,value in response_headers.items():
                    if key.lower()=='mcp-session-id':self.session_headers['Mcp-Session-Id']=value
                headers.update(self.session_headers)
                await self.http(RESOURCE,{'jsonrpc':'2.0','method':'notifications/initialized'},headers)
            headers.update(self.session_headers)
            self.sequence+=1
            response,_=await self.http(RESOURCE,{'jsonrpc':'2.0','id':self.sequence,'method':'tools/call',
                'params':{'name':name,'arguments':args}},headers)
            if response.get('error') or response.get('result',{}).get('isError'):
                raise Unavailable('Tsenta read tool returned an error. No application changes were imported.')
            envelope=response.get('result',{}).get('structuredContent',{})
            if envelope.get('tool')!=name or not isinstance(envelope.get('result'),dict):
                raise Unavailable('Tsenta response shape changed. Sync stopped safely; verify the tool contract.')
            return envelope['result']

    async def snapshot(self):
        captures=[]
        for page in range(1,1001):
            args={'filter':'all','page':page,'limit':100,'includeCounts':page==1}
            result=await self.read('list-applications',args)
            captures.append({'tool':'list-applications','arguments':args,'response':{'result':{'structuredContent':{'tool':'list-applications','result':result}}}})
            try:
                if page>=result['pagination']['totalPages']:break
            except (KeyError,TypeError):
                raise Unavailable('Invalid Tsenta pagination response.') from None
        else:
            raise Unavailable('History exceeds the safety page limit; baseline remains unchanged.')
        try:
            return validate_snapshot(captures)
        except (ValueError,KeyError,TypeError):
            raise Retryable('History changed while reading pages or was incomplete. No partial sync was committed; retry will reread all pages.') from None
