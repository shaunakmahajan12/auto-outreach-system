"""Small private deployment authentication; signed secure sessions and role checks."""
import hashlib
import hmac
import json
import os
import secrets
import time
from urllib.parse import parse_qs, urlsplit
from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware


def hash_password(password,salt=None):
    salt=salt or secrets.token_hex(16)
    digest=hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()
    return salt+':'+digest

def verify(password,encoded):
    try:return hmac.compare_digest(hash_password(password,encoded.split(':')[0]),encoded)
    except (ValueError,TypeError):return False

def configuration():
    if os.getenv('OUTREACH_REMOTE','false')!='true':return None
    base=os.getenv('EXTERNAL_BASE_URL','')
    secret=os.getenv('SESSION_SECRET','')
    try:users=json.loads(os.environ['OUTREACH_USERS'])
    except (ValueError,KeyError):raise RuntimeError('Remote mode requires OUTREACH_USERS with password hashes and roles.') from None
    if urlsplit(base).scheme!='https' or len(secret)<32 or not users or not os.getenv('ALLOWED_HOSTS') or not os.getenv('ALLOWED_ORIGINS'):
        raise RuntimeError('Remote mode requires HTTPS external base URL, 32+ character session secret, allowed hosts/origins and configured users.')
    for value in users.values():
        if value.get('role') not in ('operator','reader') or ':' not in value.get('password_hash',''):raise RuntimeError('Invalid remote user role or password hash')
    return {'users':users,'secret':secret,'base':base,'hosts':os.environ['ALLOWED_HOSTS'].split(','),'origins':os.environ['ALLOWED_ORIGINS'].split(',')}

def routes(app,config):
    attempts={}
    @app.get('/login',response_class=HTMLResponse)
    def login_page(request:Request):
        request.session.clear();nonce=secrets.token_urlsafe(32);request.session['login_csrf']=nonce
        return HTMLResponse('<!doctype html><title>Outreach sign in</title><h1>Sign in</h1><form method="post" action="/login">'
            f'<input type="hidden" name="csrf" value="{nonce}"><label>Username<input name="username" autocomplete="username" required></label>'
            '<label>Password<input name="password" type="password" autocomplete="current-password" required></label><button>Sign in</button></form>')
    @app.post('/login')
    async def login(request:Request):
        if len(await request.body())>4096:return JSONResponse({'detail':'Request too large'},413)
        form=parse_qs((await request.body()).decode(errors='replace'))
        value=lambda k:form.get(k,[''])[0]
        if not hmac.compare_digest(value('csrf'),request.session.get('login_csrf','')) or not value('csrf'):
            return JSONResponse({'detail':'Invalid login session'},403)
        key=(request.client.host if request.client else 'unknown',value('username')[:100])
        recent=[t for t in attempts.get(key,[]) if t>time.monotonic()-300]
        if len(recent)>=5:return JSONResponse({'detail':'Too many attempts. Try again in five minutes.'},429)
        user=config['users'].get(value('username'))
        if not user or not verify(value('password'),user['password_hash']):
            if len(attempts)>1000:attempts.clear()
            attempts[key]=recent+[time.monotonic()]
            return JSONResponse({'detail':'Invalid credentials'},401)
        request.session.clear();request.session.update({'user':value('username'),'csrf':secrets.token_urlsafe(32),'expires':time.time()+28800})
        return RedirectResponse('/',status_code=303)
    @app.post('/api/logout')
    def logout(request:Request):
        request.session.clear();return {'signed_out':True}
    # Added last to wrap the API middleware, making request.session available there.
    app.add_middleware(SessionMiddleware,secret_key=config['secret'],session_cookie='__Host-outreach',https_only=True,same_site='lax',max_age=28800)
