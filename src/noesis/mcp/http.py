"""Remote MCP adapter with a separate machine credential and fixed account scope."""
from contextlib import asynccontextmanager
from pathlib import Path
import hmac
import os
import time
from collections import deque
from mcp.server.mcpserver import MCPServer
from starlette.responses import JSONResponse
from starlette.routing import Route
from noesis.application.web import WebService, AppError


def create_mcp(service, user_id, bearer_token):
    if len(bearer_token) < 32:
        raise ValueError('MCP token must contain at least 32 characters')
    server = MCPServer('noesis', version='0.1.0', instructions='Selected material only. All cards require approval in the Noesis web UI. Never mirror a memory store. Sampling and elicitation are not used.')

    def mutate(operation, data, key):
        try: return service.mutate(user_id, operation, data, key)
        except AppError as e: return {'error': str(e), 'status': e.status}

    @server.tool()
    def propose_capture(deck_id: str, source: str, items: list[dict], idempotency_key: str, source_type: str = 'hermes_memory', origin: str = '') -> dict:
        """Store an inactive selected memory/notes snapshot and draft cards for web approval."""
        return mutate('proposals', {'deck_id':deck_id,'source':source,'items':items,'source_type':source_type,'origin':origin}, idempotency_key)

    @server.tool()
    def commit_capture(proposal_id: str, idempotency_key: str) -> dict:
        """Inspect approval status. Machine credentials cannot approve or commit drafts."""
        pending = service.read(user_id, 'proposals')
        return {'approval_required_in_web': True, 'pending': any(p['id'] == proposal_id for p in pending)}

    @server.tool()
    def start_review(idempotency_key: str, review_session_id: str | None = None, reveal: bool = False) -> dict:
        """Start/resume a durable review; reveal only after the learner has tried to recall."""
        if reveal:
            return mutate('review/reveal', {'session_id':review_session_id}, idempotency_key)
        return mutate('review/start', {}, idempotency_key)

    @server.tool()
    def submit_attempt(review_session_id: str, card_id: str, self_grade: int, exact_response: str, idempotency_key: str) -> dict:
        """Record the learner's explicit self-grade (1 Again, 2 Hard, 3 Good, 4 Easy), after reveal."""
        return mutate('review/grade', {'session_id':review_session_id,'card_id':card_id,'grade':self_grade,'response':exact_response}, idempotency_key)

    @server.tool()
    def resolve_learning_issue(card_id: str, reason: str, idempotency_key: str) -> dict:
        """Suspend a questionable card for inspection/correction in the web UI; preserve history."""
        return mutate('cards/'+card_id, {'status':'suspended','reason':reason}, idempotency_key)

    @server.tool()
    def update_learning_state(card_id: str, lifecycle_status: str, idempotency_key: str) -> dict:
        """Suspend, archive, or resume a card; never set FSRS state or approve proposals."""
        if lifecycle_status not in ('active','suspended','archived'): return {'error':'Invalid lifecycle status'}
        return mutate('cards/'+card_id, {'status':lifecycle_status}, idempotency_key)

    @server.tool()
    def recall_context(query: str, limit: int = 10) -> dict:
        """Recall approved Noesis cards only, with submitted provenance and uncertainty."""
        tokens = query.casefold().split()[:20]
        cards = service.read(user_id, 'cards')
        return {'results':[c for c in cards if c['status']=='active' and any(t in (c['front']+' '+c['back']+' '+c.get('tags','')).casefold() for t in tokens)][:max(1,min(limit,50))], 'untrusted_content':True}

    @server.tool()
    def get_progress() -> dict:
        """Return this account's review counts and due load."""
        return service.read(user_id, 'dashboard')

    from mcp.server.transport_security import TransportSecuritySettings
    allowed = ['127.0.0.1:*', 'localhost:*', '[::1]:*'] + [h for h in os.environ.get('NOESIS_MCP_ALLOWED_HOSTS','').split(',') if h]
    inner = server.streamable_http_app(stateless_http=True, json_response=True, max_request_body_size=100000, transport_security=TransportSecuritySettings(allowed_hosts=allowed))
    timestamps = deque()

    async def health(request):
        from sqlalchemy import text
        try:
            with service.db.read() as s: s.execute(text('SELECT 1'))
            return JSONResponse({'status':'ok'})
        except Exception: return JSONResponse({'status':'unavailable'},status_code=503)
    inner.router.routes.append(Route('/health', health))

    class BearerBoundary:
        def __init__(self): self.server = server; self.inner = inner
        async def __call__(self, scope, receive, send):
            if scope['type'] != 'http': return await inner(scope, receive, send)
            headers = dict(scope['headers'])
            if scope['path'] == '/health': return await inner(scope, receive, send)
            supplied = headers.get(b'authorization', b'')
            if not hmac.compare_digest(supplied, ('Bearer '+bearer_token).encode()):
                return await JSONResponse({'error':'Machine authentication required'},status_code=401,headers={'WWW-Authenticate':'Bearer'})(scope,receive,send)
            if b'origin' in headers:
                return await JSONResponse({'error':'Browser access denied'},status_code=403)(scope,receive,send)
            now=time.monotonic()
            while timestamps and timestamps[0] < now-60: timestamps.popleft()
            if len(timestamps)>=120:
                return await JSONResponse({'error':'Rate limit exceeded'},status_code=429)(scope,receive,send)
            timestamps.append(now)
            # A disabled account revokes the machine credential as well.
            try: service.read(user_id, 'me')
            except AppError:
                return await JSONResponse({'error':'Account unavailable'},status_code=401)(scope,receive,send)
            return await inner(scope,receive,send)
    return BearerBoundary()


def main():
    import uvicorn
    production = os.environ.get('NOESIS_ENV') == 'production'
    if production and not os.environ.get('NOESIS_DATABASE_URL','').startswith('postgresql+psycopg://'):
        raise SystemExit('Production requires PostgreSQL')
    service = WebService(initialize=not production)
    token = Path(os.environ['NOESIS_MCP_TOKEN_FILE']).read_text().strip()
    app = create_mcp(service, os.environ['NOESIS_MCP_USER_ID'], token)
    uvicorn.run(app, host='127.0.0.1', port=int(os.environ.get('NOESIS_MCP_PORT','8092')), access_log=False, proxy_headers=False)


if __name__ == '__main__': main()
