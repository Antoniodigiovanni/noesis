"""Opt-in browser acceptance. Creates only a disposable DB and loopback listener."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request
from noesis.application.web import WebService

with tempfile.TemporaryDirectory(prefix='noesis-browser-') as directory:
    db=Path(directory)/'browser.db'
    service=WebService(db)
    uid=service.create_user('browser-fixture','disposable browser password')
    deck=service.mutate(uid,'decks',{'name':'Browser acceptance'},'deck')
    service.mutate(uid,'cards',{'deck_id':deck['id'],'front':'What survives a restart?','back':'Persisted evidence'},'card')
    env={**os.environ,'NOESIS_DB_PATH':str(db),'NOESIS_ENV':'development','NOESIS_WEB_PORT':'18091'}
    env.pop('NOESIS_DATABASE_URL',None);env.pop('NOESIS_ORIGIN',None)
    server=subprocess.Popen([sys.executable,'-m','noesis.web.app'],env=env,stdout=subprocess.DEVNULL)
    try:
        for _ in range(40):
            if server.poll() is not None: raise SystemExit('Disposable web server failed to start (socket restrictions may apply)')
            try:
                with urllib.request.urlopen('http://127.0.0.1:18091/health',timeout=.3): break
            except OSError: time.sleep(.1)
        else: raise SystemExit('Disposable web server not reachable')
        subprocess.run(['node','tests/browser/smoke.cjs'],check=True,timeout=35)
    finally:
        server.terminate();server.wait(timeout=5)
