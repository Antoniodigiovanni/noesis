from __future__ import annotations
import hmac
import asyncio
import json
import logging
import os
import time
from collections import defaultdict, deque
from pathlib import Path
from uuid import uuid4
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles
from asyncio import to_thread as run_in_threadpool
from noesis.application.web import WebService, AppError, required
from noesis.domain.errors import Conflict
from noesis.web.provider import Provider
from noesis.web.access import AccessIdentity

ASSETS = Path(__file__).parent / 'static'
MAX_REQUEST_BYTES = 100000
logger = logging.getLogger('noesis.web')
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.INFO)
logger.propagate = False


def create_app(database=None, *, secure_cookies=True, initialize=True):
    access = AccessIdentity()
    service = WebService(database, initialize=initialize)
    provider = Provider()
    attempts = defaultdict(deque)
    origin = os.environ.get('NOESIS_ORIGIN', '')

    def throttle(bucket, limit):
        now = time.monotonic()
        # Bound memory for unauthenticated addresses too.
        if len(attempts) > 4096:
            for k in list(attempts):
                if not attempts[k] or attempts[k][-1] < now-60: del attempts[k]
            if len(attempts) > 4096: raise AppError('Try again later', 429)
        q = attempts[bucket]
        while q and q[0] < now-60: q.popleft()
        if len(q) >= limit: raise AppError('Too many requests; retry in a minute', 429)
        q.append(now)

    async def api(request: Request):
        resource = request.path_params['resource']
        correlation = request.scope.get('noesis_correlation', str(uuid4()))
        try:
            if request.method == 'POST':
                expected_origin = origin or str(request.base_url).rstrip('/')
                if request.headers.get('origin') != expected_origin:
                    raise AppError('Invalid request origin', 403)
                if request.headers.get('content-type', '').split(';')[0] != 'application/json':
                    raise AppError('JSON required', 415)
                body = bytearray()
                async for chunk in request.stream():
                    if len(body) + len(chunk) > MAX_REQUEST_BYTES:
                        raise AppError('Request too large', 413)
                    body.extend(chunk)
                try: data = json.loads(body)
                except (ValueError, UnicodeDecodeError): raise AppError('Invalid JSON')
                if not isinstance(data, dict): raise AppError('Object required')
            access_digest = None
            access_tokens = request.headers.getlist('cf-access-jwt-assertion')
            if access.enabled and access_tokens:
                try:
                    access_digest = await asyncio.wait_for(run_in_threadpool(access.verify, access_tokens), timeout=2)
                except TimeoutError:
                    raise AppError('Access verifier unavailable', 503) from None
            if resource == 'login' and request.method == 'POST':
                throttle(('login', request.client.host), 8)
                token, csrf = await run_in_threadpool(service.login, data.get('username'), data.get('password'))
                response = JSONResponse({'csrf': csrf})
                response.set_cookie('noesis_session', token, httponly=True, secure=secure_cookies, samesite='strict', max_age=43200, path='/')
                return response
            if access_digest is not None:
                uid = await run_in_threadpool(service.access_owner, access.owner)
                csrf = access.csrf(uid, access_digest)
            else:
                uid, csrf = await run_in_threadpool(service.authenticate, request.cookies.get('noesis_session'))
            throttle(('user', uid), 180)
            if request.method == 'GET':
                if resource == 'session': result = {'csrf': csrf, 'authentication': 'access' if access_digest is not None else 'password', **await run_in_threadpool(service.read, uid, 'me')}
                elif resource == 'provider': result = provider.state()
                else: result = await run_in_threadpool(service.read, uid, resource)
            else:
                if not hmac.compare_digest(request.headers.get('x-csrf-token',''), csrf): raise AppError('Invalid CSRF token', 403)
                key = request.headers.get('idempotency-key', '')
                if not key: raise AppError('Idempotency-Key required')
                if resource == 'generate':
                    throttle(('generate', uid), 5)
                    # Verify ownership before any source leaves the server.
                    decks = await run_in_threadpool(service.read, uid, 'decks')
                    if data.get('deck_id') not in [d['id'] for d in decks]: raise AppError('Not found', 404)
                    if data.get('consent') is not True: raise AppError('Confirm processing by the configured provider')
                    source = required(data, 'source', 30000)
                    result = await run_in_threadpool(service.cached, uid, 'generation', data, key)
                    if result is None:
                        items, metadata = await run_in_threadpool(provider.generate, source)
                        result = await run_in_threadpool(service.mutate, uid, 'generation', {**data,'items':items,'generation':metadata}, key, data, correlation)
                else: result = await run_in_threadpool(service.mutate, uid, resource, data, key, None, correlation)
            response = JSONResponse(result)
            if resource in ('logout', 'password'): response.delete_cookie('noesis_session')
            return response
        except AppError as e:
            return JSONResponse({'error': str(e), 'correlation_id': correlation}, status_code=e.status)
        except Conflict:
            return JSONResponse({'error': 'Idempotency key conflicts with earlier input', 'correlation_id': correlation}, status_code=409)
        except Exception:
            # Never return SQL, provider bodies, source text or credentials.
            return JSONResponse({'error':'Request failed', 'correlation_id':correlation}, status_code=500)

    async def health(request):
        try:
            from sqlalchemy import text
            with service.db.read() as s:
                s.execute(text('SELECT 1'))
                if not initialize:
                    if s.execute(text('SELECT version_num FROM alembic_version')).scalar() != '0002':
                        raise RuntimeError('Schema upgrade required')
            return JSONResponse({'status':'ok'})
        except Exception:
            return JSONResponse({'status':'unavailable'}, status_code=503)

    async def index(request): return Response((ASSETS/'index.html').read_bytes(), media_type='text/html')
    async def asset(request):
        name = request.path_params['name']
        if name not in ('app.js','style.css'): return Response(status_code=404)
        return Response((ASSETS/name).read_bytes(), media_type='text/javascript' if name.endswith('.js') else 'text/css')
    app = Starlette(routes=[Route('/', index), Route('/health', health), Route('/api/{resource:path}', api, methods=['GET','POST']), Route('/static/{name}', asset)])
    app.state.service = service

    security_headers = {'cache-control':'no-store', 'x-content-type-options':'nosniff', 'referrer-policy':'no-referrer', 'x-frame-options':'DENY', 'content-security-policy': "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"}
    class SecurityBoundary:
        state = app.state
        async def __call__(self, scope, receive, send):
            correlation = str(uuid4())
            scope['noesis_correlation'] = correlation
            path = scope.get('path','').split('/')
            operation = path[2] if len(path)>2 and path[1]=='api' and path[2] in {'login','session','logout','password','settings','cards','decks','proposals','generate','review','dashboard','export','me','provider'} else 'http'
            async def secure_send(message):
                if message['type'] == 'http.response.start':
                    message['headers'] = list(message.get('headers', [])) + [(k.encode(),v.encode()) for k,v in security_headers.items()] + [(b'x-request-id',correlation.encode())]
                    logger.info(json.dumps({'operation':operation,'correlation_id':correlation,'status':message['status']}))
                await send(message)
            if scope['type'] == 'http':
                raw = dict(scope['headers']).get(b'content-length', b'0')
                if raw.isdigit() and int(raw) > MAX_REQUEST_BYTES:
                    return await JSONResponse({'error':'Request too large'},status_code=413)(scope,receive,secure_send)
            return await app(scope,receive,secure_send)
    return SecurityBoundary()


def main():
    import uvicorn
    production = os.environ.get('NOESIS_ENV') == 'production'
    if production and not os.environ.get('NOESIS_DATABASE_URL','').startswith('postgresql+psycopg://'):
        raise SystemExit('Production requires a dedicated PostgreSQL database')
    if production and not os.environ.get('NOESIS_ORIGIN','').startswith('https://'):
        raise SystemExit('Production requires NOESIS_ORIGIN=https://…')
    secure_cookies = production or os.environ.get('NOESIS_SECURE_COOKIES', '').casefold() in {'1', 'true', 'yes', 'on'}
    app = create_app(secure_cookies=secure_cookies, initialize=not production)
    uvicorn.run(app, host='127.0.0.1', port=int(os.environ.get('NOESIS_WEB_PORT','8091')), access_log=False, proxy_headers=False)


if __name__ == '__main__': main()
