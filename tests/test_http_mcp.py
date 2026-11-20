import httpx2 as httpx
from test_web import async_test
from noesis.application.web import WebService
from noesis.mcp.http import create_mcp


@async_test
async def test_remote_mcp_protocol_auth_and_approval_boundary(tmp_path):
    service=WebService(tmp_path/'mcp.db')
    uid=service.create_user('machine-owner','a long enough password')
    deck=service.mutate(uid,'decks',{'name':'Memory'},'deck')
    app=create_mcp(service,uid,'test-token-'+'x'*40)
    async with app.inner.router.lifespan_context(app.inner):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:8092') as c:
            assert (await c.post('/mcp',json={})).status_code==401
            headers={'Authorization':'Bearer test-token-'+'x'*40,'Accept':'application/json, text/event-stream'}
            async def rpc(method,params=None):
                response=await c.post('/mcp',headers=headers,json={'jsonrpc':'2.0','id':1,'method':method,'params':params or {}})
                assert response.status_code==200,response.text
                return response.json()['result']
            result=await rpc('initialize',{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'test','version':'1'}})
            headers['MCP-Protocol-Version']=result['protocolVersion']
            tools=await rpc('tools/list')
            assert {t['name'] for t in tools['tools']}=={'propose_capture','commit_capture','start_review','submit_attempt','resolve_learning_issue','update_learning_state','recall_context','get_progress'}
            assert 'sampling' not in result['capabilities'] and 'elicitation' not in result['capabilities']
            capture=await rpc('tools/call',{'name':'propose_capture','arguments':{'deck_id':deck['id'],'source':'Selected memory only','items':[{'front':'Q','back':'A'}],'idempotency_key':'capture'}})
            assert not capture.get('isError'),capture
            assert len(service.read(uid,'proposals'))==1
            assert service.read(uid,'cards')==[]
            blocked=await c.post('/mcp',headers={**headers,'Origin':'https://evil.test'},json={})
            assert blocked.status_code==403
