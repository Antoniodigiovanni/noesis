import pytest
import asyncio
import functools

def async_test(fn):
    @functools.wraps(fn)
    def run(*args, **kwargs):
        async def execute():
            async def heartbeat():
                # Sandbox denies event-loop wakeup sockets. Keep its selector moving.
                while True: await asyncio.sleep(.01)
            task = asyncio.create_task(heartbeat())
            try: return await fn(*args, **kwargs)
            finally:
                await asyncio.get_running_loop().shutdown_default_executor()
                task.cancel()
        return asyncio.run(execute())
    return run
import httpx2 as httpx

@pytest.fixture
def anyio_backend(): return "asyncio"
from noesis.web.app import create_app





def test_nonproduction_https_proxy_can_enable_secure_session_cookies(monkeypatch):
    from noesis.web import app as web_app
    captured = {}

    class FakeUvicorn:
        @staticmethod
        def run(app, **kwargs):
            captured['runner'] = (app, kwargs)

    monkeypatch.setattr('uvicorn.run', FakeUvicorn.run)
    monkeypatch.setattr(web_app, 'create_app', lambda **kwargs: captured.update(kwargs) or object())
    monkeypatch.delenv('NOESIS_ENV', raising=False)
    monkeypatch.setenv('NOESIS_SECURE_COOKIES', 'true')

    web_app.main()

    assert captured['secure_cookies'] is True
    assert captured['initialize'] is True

from contextlib import asynccontextmanager


@asynccontextmanager
async def client(tmp_path):
    app = create_app(tmp_path/'web.db', secure_cookies=False)
    app.state.service.create_user('learner', 'a sufficiently long password')
    app.state.service.create_user('other', 'another long password')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as c:
        yield c


async def login(c, username='learner', password='a sufficiently long password'):
    r = await c.post('/api/login', json={'username': username, 'password': password}, headers={'Origin': 'http://testserver'})
    assert r.status_code == 200, r.text
    return {'X-CSRF-Token': r.json()['csrf'], 'Origin': 'http://testserver'}


async def post(c, path, data, h):
    import uuid
    return await c.post('/api/' + path, json=data, headers={**h, 'Idempotency-Key': str(uuid.uuid4())})


@async_test
async def test_authenticated_review_restart_idempotency_and_scoping(tmp_path):
    async with client(tmp_path) as c:
        assert (await c.get('/api/dashboard')).status_code == 401
        h = await login(c)
        assert (await post(c, 'decks', {'name': 'Systems'}, {})).status_code == 403
        deck = (await post(c, 'decks', {'name': 'Systems'}, h)).json()
        card = (await post(c, 'cards', {'deck_id': deck['id'], 'front': 'What persists?', 'back': 'Evidence', 'source': 'My notes'}, h)).json()
        review = (await post(c, 'review/start', {}, h)).json()
        assert 'back' not in review['card']
        assert (await post(c, 'review/grade', {'session_id': review['id'], 'card_id': card['id'], 'grade': 3}, h)).status_code == 409
        shown = (await post(c, 'review/reveal', {'session_id': review['id']}, h)).json()
        assert shown['card']['back'] == 'Evidence'
        assert (await post(c, 'review/start', {}, h)).json()['id'] == review['id']
        key = {**h, 'Idempotency-Key': 'grade-once'}
        data = {'session_id': review['id'], 'card_id': card['id'], 'grade': 3}
        first = await c.post('/api/review/grade', json=data, headers=key)
        assert first.status_code == 200, first.text
        assert first.json()['next_due_at']
        assert (await c.post('/api/review/grade', json=data, headers=key)).json() == first.json()
        assert (await c.get('/api/dashboard')).json()['reviews'] == 1
        await post(c, 'logout', {}, h)
        h2 = await login(c, 'other', 'another long password')
        assert (await c.get('/api/cards')).json() == []
        assert (await post(c, 'cards/'+card['id'], {'front': 'Stolen'}, h2)).status_code == 404
        assert (await post(c, 'review/reveal', {'session_id': review['id']}, h2)).status_code == 404
        assert (await post(c, 'cards', {'deck_id': deck['id'], 'front': 'No', 'back': 'No'}, h2)).status_code == 404


@async_test
async def test_proposal_approval_provider_failure_and_security(tmp_path):
    async with client(tmp_path) as c:
        h = await login(c)
        deck = (await post(c, 'decks', {'name': 'Ideas'}, h)).json()
        p = (await post(c, 'proposals', {'deck_id': deck['id'], 'source': 'Selected memory', 'source_type': 'hermes_memory', 'origin': 'memory:123', 'items': [{'front': 'Q', 'back': 'A'}]}, h)).json()
        assert (await c.get('/api/cards')).json() == []
        approved = await post(c, 'proposals/'+p['id']+'/decide', {'items': [{'front': 'Edited?', 'back': 'Yes', 'decision': 'approve'}]}, h)
        assert approved.status_code == 200, approved.text
        assert (await c.get('/api/cards')).json()[0]['front'] == 'Edited?'
        assert (await post(c, 'generate', {'deck_id': deck['id'], 'source': 'notes', 'consent': True}, h)).status_code == 503
        assert (await post(c, 'review/start', {}, h)).json()['card']['front'] == 'Edited?'
        assert (await c.post('/api/decks', json={'name': 'X'}, headers={**h, 'Origin': 'https://evil.test', 'Idempotency-Key': 'x'})).status_code == 403
        assert (await c.get('/')).headers['content-security-policy']
        assert (await c.get('/api/export')).json()['cards']


@async_test
async def test_corrections_daily_limits_and_auditable_undo(tmp_path):
    async with client(tmp_path) as c:
        h=await login(c)
        deck=(await post(c,'decks',{'name':'Practice'},h)).json()
        card=(await post(c,'cards',{'deck_id':deck['id'],'front':'Question','back':'Answer'},h)).json()
        await post(c,'settings',{'daily_limit':1,'new_limit':1,'retention':.92},h)
        review=(await post(c,'review/start',{},h)).json()
        await post(c,'review/reveal',{'session_id':review['id']},h)
        grade=(await post(c,'review/grade',{'session_id':review['id'],'card_id':card['id'],'grade':1},h)).json()
        assert (await post(c,'review/start',{},h)).json()['status']=='complete'
        undo=await post(c,'review/undo',{'review_id':grade['id'],'reason':'Pressed the wrong grade'},h)
        assert undo.status_code==200,undo.text
        assert (await c.get('/api/dashboard')).json()['reviews']==1
        assert (await c.get('/api/cards')).json()[0]['due_at'] is None
        edited=(await post(c,'cards/'+card['id'],{'front':'Better question'},h)).json()
        assert edited['revision']==2
        exported=(await c.get('/api/export')).json()
        assert exported['reviews'][0]['revision']==1
        assert exported['reviews'][0]['invalidated'] is True


@async_test
async def test_configured_provider_success_and_safe_errors(tmp_path,monkeypatch):
    from noesis.web import provider
    monkeypatch.setenv('NOESIS_PROVIDER_URL','https://model.invalid/v1')
    monkeypatch.setenv('NOESIS_PROVIDER_MODEL','fixture-model')
    def response(request):
        body=__import__('json').loads(request.content)
        assert body['model']=='fixture-model'
        return httpx.Response(200,json={'choices':[{'message':{'content':'{"items":[{"front":"Why practice?","back":"To remember."}]}'}}]})
    real_client=httpx.Client
    monkeypatch.setattr(provider.httpx,'Client',lambda **kw: real_client(transport=httpx.MockTransport(response),**kw))
    async with client(tmp_path) as c:
        h=await login(c)
        deck=(await post(c,'decks',{'name':'Generation'},h)).json()
        r=await post(c,'generate',{'deck_id':deck['id'],'source':'Practice helps us remember.','consent':True},h)
        assert r.status_code==200,r.text
        assert r.json()['items'][0]['front']=='Why practice?'
        assert (await c.get('/api/cards')).json()==[]


@async_test
async def test_card_forms_and_history(tmp_path):
    async with client(tmp_path) as c:
        h=await login(c)
        deck=(await post(c,'decks',{'name':'Forms'},h)).json()
        reverse=await post(c,'cards',{'deck_id':deck['id'],'front':'Forward','back':'Backward','card_type':'reversed'},h)
        assert reverse.status_code==200,reverse.text
        assert len((await c.get('/api/cards')).json())==2
        cloze=(await post(c,'cards',{'deck_id':deck['id'],'front':'Recall uses {{c1::retrieval}}.','card_type':'cloze'},h)).json()
        assert cloze['front']=='Recall uses […].'
        assert cloze['back']=='Recall uses retrieval.'
        details=await c.get('/api/cards/'+cloze['id'])
        assert details.status_code==200
        assert len(details.json()['revisions'])==1


@async_test
async def test_all_grades_and_account_revocation(tmp_path):
    from sqlalchemy import select
    from noesis.persistence.web_models import Account
    async with client(tmp_path) as c:
        h=await login(c)
        deck=(await post(c,'decks',{'name':'Four grades'},h)).json()
        for n in range(4):
            await post(c,'cards',{'deck_id':deck['id'],'front':f'Question {n}','back':f'Answer {n}'},h)
        r=(await post(c,'review/start',{},h)).json()
        for grade in range(1,5):
            r=(await post(c,'review/reveal',{'session_id':r['id']},h)).json()
            result=await post(c,'review/grade',{'session_id':r['id'],'card_id':r['card']['id'],'grade':grade},h)
            assert result.status_code==200,result.text
            r=result.json()['review']
        assert r['status']=='complete'
        assert (await c.get('/api/dashboard')).json()['grades']==[1,1,1,1]
        assert c.cookies.get('noesis_session')
        svc=c._transport.app.state.service
        with svc.db.transaction() as s:
            s.scalar(select(Account).where(Account.username=='learner')).disabled=True
        assert (await c.get('/api/cards')).status_code==401


@async_test
async def test_secure_cookie_login_limit_and_xss_boundary(tmp_path):
    app=create_app(tmp_path/'secure.db',secure_cookies=True)
    app.state.service.create_user('safe','a sufficiently long password')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://testserver') as c:
        r=await c.post('/api/login',json={'username':'safe','password':'a sufficiently long password'},headers={'Origin':'https://testserver'})
        assert r.status_code==200
        cookie=r.headers['set-cookie'].lower()
        assert 'secure' in cookie and 'httponly' in cookie and 'samesite=strict' in cookie
        for n in range(8):
            bad=await c.post('/api/login',json={'username':'safe','password':'wrong'},headers={'Origin':'https://testserver'})
        assert bad.status_code==429
        html=(await c.get('/')).text
        assert '<script src="/static/app.js" defer>' in html
        assert 'frame-ancestors' in (await c.get('/')).headers['content-security-policy']


def test_provider_url_credentials_are_never_exposed(monkeypatch):
    from noesis.web.provider import Provider
    monkeypatch.setenv('NOESIS_PROVIDER_URL','https://operator:credential@model.invalid/v1?token=sensitive')
    monkeypatch.setenv('NOESIS_PROVIDER_MODEL','fixture')
    state=Provider().state()
    assert state['endpoint']==''
    assert state['enabled'] is False


@async_test
async def test_streamed_json_is_rejected_before_reading_the_remaining_body(tmp_path):
    async with client(tmp_path) as c:
        chunks_read = 0

        async def body():
            nonlocal chunks_read
            for chunk in (b'{"padding":"', b'x' * 60000, b'x' * 60000, b'"}'):
                chunks_read += 1
                yield chunk

        response = await c.post(
            '/api/login', content=body(),
            headers={'Origin': 'http://testserver', 'Content-Type': 'application/json'},
        )
        assert response.status_code == 413
        assert chunks_read == 3, 'The oversized request must not be drained into memory'
        assert response.headers['x-request-id'] == response.json()['correlation_id']
        assert (await c.get('/health')).status_code == 200


@async_test
async def test_archiving_a_deck_keeps_deleted_cards_hidden_and_preserves_evidence(tmp_path):
    async with client(tmp_path) as c:
        h = await login(c)
        deck = (await post(c, 'decks', {'name': 'Lifecycle'}, h)).json()
        for n in range(2):
            await post(c, 'cards', {
                'deck_id': deck['id'], 'front': f'Question {n}', 'back': f'Answer {n}',
            }, h)
        study = (await post(c, 'review/start', {}, h)).json()
        deleted_id = study['card']['id']
        await post(c, 'review/reveal', {'session_id': study['id']}, h)
        graded = await post(c, 'review/grade', {
            'session_id': study['id'], 'card_id': deleted_id, 'grade': 3,
        }, h)
        assert graded.status_code == 200
        await post(c, 'cards/' + deleted_id, {'status': 'deleted', 'confirm': 'DELETE'}, h)
        before = (await c.get('/api/export')).json()

        archived = await post(c, 'decks/' + deck['id'], {'delete': True, 'confirm': 'DELETE'}, h)
        assert archived.status_code == 200
        visible = (await c.get('/api/cards')).json()
        assert deleted_id not in {card['id'] for card in visible}
        assert len(visible) == 1 and visible[0]['status'] == 'archived'
        after = (await c.get('/api/export')).json()
        assert next(card for card in after['cards'] if card['id'] == deleted_id)['status'] == 'deleted'
        assert after['reviews'] == before['reviews']
        assert (await post(c, 'review/start', {}, h)).json()['status'] == 'complete'


@async_test
async def test_password_change_preserves_exact_whitespace_and_revokes_other_sessions(tmp_path):
    old_password = '  original fixture password  '
    new_password = '  replacement fixture password  '
    async with client(tmp_path) as c:
        app = c._transport.app
        app.state.service.create_user('spaces', old_password)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url='http://testserver',
        ) as other_session:
            await login(other_session, 'spaces', old_password)
            h = await login(c, 'spaces', old_password)
            changed = await post(c, 'password', {
                'current_password': old_password, 'password': new_password,
            }, h)
            assert changed.status_code == 200
            assert (await other_session.get('/api/cards')).status_code == 401
            for wrong_password in (old_password, new_password.strip()):
                rejected = await c.post('/api/login', json={
                    'username': 'spaces', 'password': wrong_password,
                }, headers={'Origin': 'http://testserver'})
                assert rejected.status_code == 401
            await login(c, 'spaces', new_password)


@pytest.fixture
def access_verifier(monkeypatch):
    """Mock only the outbound loopback HTTP connection, not authentication."""
    import http.client
    state = {'calls': [], 'email': 'Owner@Example.test', 'status': 200, 'failure': False}

    class Connection:
        def __init__(self, host, port, timeout):
            assert (host, port) == ('127.0.0.1', 8790)
            assert 0 < timeout <= 2
        def request(self, method, path, body=None, headers=None):
            assert method == 'GET' and path == '/verify' and body is None
            assert set(headers) == {'Cf-Access-Jwt-Assertion'}
            assert headers['Cf-Access-Jwt-Assertion'] in {'abc.def.ghi', 'abc.def.rotated'}
            state['calls'].append(headers)
            if state['failure']: raise OSError('unavailable')
        def getresponse(self):
            return self
        @property
        def status(self): return state['status']
        def getheaders(self): return state.get('headers', [('X-Hermes-Verified-Email', state['email'])])
        def close(self): pass

    monkeypatch.setattr(http.client, 'HTTPConnection', Connection)
    monkeypatch.setenv('NOESIS_ACCESS_ENABLED', 'true')
    monkeypatch.setenv('NOESIS_ACCESS_EMAIL', 'owner@example.test')
    monkeypatch.delenv('NOESIS_ACCESS_OWNER', raising=False)
    return state


@async_test
async def test_access_reads_writes_and_request_identity(tmp_path, access_verifier):
    app = create_app(tmp_path/'access.db')
    app.state.service.create_user('owner', 'a sufficiently long password')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://testserver') as c:
        assert (await c.get('/health')).status_code == 200
        assert not access_verifier['calls']
        jwt = {'Cf-Access-Jwt-Assertion': 'abc.def.ghi'}
        session = await c.get('/api/session', headers=jwt)
        assert session.status_code == 200, session.text
        assert session.json()['username'] == 'owner'
        csrf = session.json()['csrf']
        assert 'set-cookie' not in session.headers
        assert not c.cookies
        assert (await c.get('/api/session', headers=jwt)).json()['csrf'] == csrf
        assert (await c.get('/api/decks', headers=jwt)).status_code == 200
        headers = {**jwt, 'Origin': 'https://testserver', 'Idempotency-Key': 'access-deck'}
        assert (await c.post('/api/decks', json={'name': 'Access'}, headers=headers)).status_code == 403
        headers['X-CSRF-Token'] = csrf
        assert (await c.post('/api/decks', json={'name': 'Access'}, headers={**headers, 'Origin': 'https://evil.test'})).status_code == 403
        assert (await c.post('/api/decks', json={'name': 'Access'}, headers=headers)).status_code == 200
        assert (await c.get('/api/decks')).status_code == 401
        assert (await c.post('/api/decks', json={'name': 'Gone'}, headers={k:v for k,v in headers.items() if k != 'Cf-Access-Jwt-Assertion'})).status_code == 401
        access_verifier['status'] = 403
        assert (await c.get('/api/decks', headers=jwt)).status_code == 401
        access_verifier['status'] = 200
        access_verifier['email'] = 'someone@example.test'
        assert (await c.get('/api/decks', headers=jwt)).status_code == 401
        access_verifier['failure'] = True
        assert (await c.get('/api/decks', headers=jwt)).status_code == 503


@async_test
async def test_access_spoofing_and_password_fallback(tmp_path, access_verifier):
    app = create_app(tmp_path/'fallback.db', secure_cookies=True)
    app.state.service.create_user('owner', 'a sufficiently long password')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://testserver') as c:
        assert (await c.get('/api/session', headers={'X-Hermes-Verified-Email': 'owner@example.test'})).status_code == 401
        for token in ('', 'abc.def.ghi,abc.def.ghi', 'x'*16385, 'Bearer abc.def.ghi', 'abc'):
            assert (await c.get('/api/session', headers={'Cf-Access-Jwt-Assertion': token})).status_code == 401
        assert (await c.get('/api/session', headers=[('Cf-Access-Jwt-Assertion','abc.def.ghi')]*2)).status_code == 401
        assert not access_verifier['calls']
        r = await c.post('/api/login', json={'username':'owner','password':'a sufficiently long password'}, headers={'Origin':'https://testserver'})
        assert r.status_code == 200
        cookie = r.headers['set-cookie'].lower()
        assert 'secure' in cookie and 'httponly' in cookie and 'samesite=strict' in cookie
        assert (await c.get('/api/session')).status_code == 200
        access_verifier['status'] = 403
        assert (await c.get('/api/session', headers={'Cf-Access-Jwt-Assertion':'abc.def.ghi'})).status_code == 401
        assert (await c.get('/api/session')).status_code == 200


@async_test
async def test_access_owner_must_exist_and_be_enabled(tmp_path, access_verifier, monkeypatch):
    from noesis.persistence.web_models import Account
    app = create_app(tmp_path/'owner.db')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://testserver') as c:
        headers = {'Cf-Access-Jwt-Assertion':'abc.def.ghi'}
        assert (await c.get('/api/session', headers=headers)).status_code == 401
        uid = app.state.service.create_user('owner', 'a sufficiently long password')
        assert (await c.get('/api/session', headers=headers)).status_code == 200
        with app.state.service.db.transaction() as s:
            s.get(Account, uid).disabled = True
        assert (await c.get('/api/session', headers=headers)).status_code == 401


@async_test
@pytest.mark.parametrize('verifier_status, expected', [(200, 200), (403, 401)])
async def test_access_without_email_uses_verifier(tmp_path, access_verifier, monkeypatch, verifier_status, expected):
    monkeypatch.delenv('NOESIS_ACCESS_EMAIL', raising=False)
    access_verifier['email'] = 'human@example.test'
    access_verifier['status'] = verifier_status
    app = create_app(tmp_path/'no-email.db')
    app.state.service.create_user('owner', 'a sufficiently long password')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://testserver') as c:
        assert (await c.get('/api/session', headers={'X-Hermes-Verified-Email':'human@example.test'})).status_code == 401
        response = await c.get('/api/session', headers={'Cf-Access-Jwt-Assertion':'abc.def.ghi'})
        assert response.status_code == expected
        if expected == 200:
            assert response.json()['username'] == 'owner'
            assert response.json()['authentication'] == 'access'
        assert len(access_verifier['calls']) == 1
        access_verifier['status'] = 200
        for email in ('', 'service-token', 'human@example.test,other@example.test', ' human@example.test'):
            access_verifier['email'] = email
            assert (await c.get('/api/session', headers={'Cf-Access-Jwt-Assertion':'abc.def.ghi'})).status_code == 401


@async_test
async def test_access_default_off_and_explicit_owner(tmp_path, access_verifier, monkeypatch):
    monkeypatch.delenv('NOESIS_ACCESS_ENABLED')
    app = create_app(tmp_path/'off.db')
    app.state.service.create_user('owner', 'a sufficiently long password')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://testserver') as c:
        assert (await c.get('/api/session', headers={'Cf-Access-Jwt-Assertion':'abc.def.ghi'})).status_code == 401
        assert not access_verifier['calls']
    monkeypatch.setenv('NOESIS_ACCESS_ENABLED', 'true')
    monkeypatch.setenv('NOESIS_ACCESS_OWNER', 'Learner')
    app = create_app(tmp_path/'custom.db')
    app.state.service.create_user('learner', 'a sufficiently long password')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://testserver') as c:
        r = await c.get('/api/session', headers={'Cf-Access-Jwt-Assertion':'abc.def.ghi'})
        assert r.status_code == 200
        assert r.json()['username'] == 'learner'


@async_test
async def test_access_verifier_response_and_csrf_scope(tmp_path, access_verifier, capsys):
    app = create_app(tmp_path/'response.db')
    app.state.service.create_user('owner', 'a sufficiently long password')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://testserver') as c:
        jwt = {'Cf-Access-Jwt-Assertion': 'abc.def.ghi'}
        csrf = (await c.get('/api/session', headers=jwt)).json()['csrf']
        rotated = {'Cf-Access-Jwt-Assertion': 'abc.def.rotated'}
        assert (await c.get('/api/session', headers=rotated)).json()['csrf'] != csrf
        assert (await c.post('/api/decks', json={'name':'Stale'}, headers={**rotated, 'Origin':'https://testserver', 'X-CSRF-Token':csrf, 'Idempotency-Key':'stale'})).status_code == 403
        for headers in ([], [('X-Hermes-Verified-Email','owner@example.test')]*2, [('X-Hermes-Verified-Email','x'*255)], [('X-Hermes-Verified-Email','owner@example.test,other@example.test')]):
            access_verifier['headers'] = headers
            r = await c.get('/api/session', headers=jwt)
            assert r.status_code == 401
            assert 'abc.def.ghi' not in r.text
    output = capsys.readouterr()
    assert 'abc.def.ghi' not in output.err + output.out


@async_test
async def test_access_verification_has_total_deadline(tmp_path, access_verifier, monkeypatch):
    import http.client
    import time
    connection = http.client.HTTPConnection
    class SlowConnection(connection):
        def getresponse(self):
            time.sleep(2.2)
            return super().getresponse()
    monkeypatch.setattr(http.client, 'HTTPConnection', SlowConnection)
    app = create_app(tmp_path/'timeout.db')
    app.state.service.create_user('owner', 'a sufficiently long password')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://testserver') as c:
        r = await c.get('/api/session', headers={'Cf-Access-Jwt-Assertion':'abc.def.ghi'})
        assert r.status_code == 503
