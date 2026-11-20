"""Operator commands; configuration comes from protected environment/secret files."""
import argparse
import getpass
import json
import os
from pathlib import Path
import subprocess
import sys
from sqlalchemy import select, delete
from noesis.application.web import WebService
from noesis.persistence.web_models import Account, LoginSession


def main():
    parser = argparse.ArgumentParser(prog='noesis-admin')
    sub=parser.add_subparsers(dest='command', required=True)
    user=sub.add_parser('user'); user.add_argument('action',choices=['list','create','disable']);user.add_argument('username',nargs='?')
    sub.add_parser('diagnose')
    sub.add_parser('db-upgrade')
    transfer=sub.add_parser('import-sqlite');transfer.add_argument('backup',type=Path);transfer.add_argument('--confirm',required=True)
    args=parser.parse_args()
    if args.command=='db-upgrade':
        subprocess.run([sys.executable,'-m','alembic','-c',os.environ.get('NOESIS_ALEMBIC_CONFIG','alembic.ini'),'upgrade','head'],check=True)
        return
    svc=WebService(initialize=os.environ.get('NOESIS_ENV')!='production')
    if args.command=='diagnose':
        from sqlalchemy import text
        with svc.db.read() as s:
            s.execute(text('SELECT 1'))
            try: version=s.execute(text('SELECT version_num FROM alembic_version')).scalar()
            except Exception: version='unversioned-dev'
        print(json.dumps({'database_engine':svc.db.engine.dialect.name,'database_name':svc.db.engine.url.database,'schema':version,'scheduler':svc.scheduler.version,'status':'ok'}))
    elif args.command=='import-sqlite':
        if args.confirm!='IMPORT-INTO-EMPTY': parser.error('Confirmation must be IMPORT-INTO-EMPTY')
        from noesis.persistence.transfer import transfer_sqlite
        print(json.dumps({'target_database':svc.db.engine.url.database,'row_counts':transfer_sqlite(args.backup,svc.db)}))
    elif args.action=='create':
        if not args.username: parser.error('username required')
        password=getpass.getpass('New password: ')
        if password!=getpass.getpass('Repeat password: '): parser.error('Passwords differ')
        print(json.dumps({'user_id':svc.create_user(args.username,password)}))
    elif args.action=='list':
        with svc.db.read() as s:
            print(json.dumps([{'id':u.id,'username':u.username,'disabled':u.disabled} for u in s.scalars(select(Account))]))
    else:
        if not args.username: parser.error('username required')
        with svc.db.transaction() as s:
            user=s.scalar(select(Account).where(Account.username==args.username.casefold()))
            if not user: parser.error('Account not found')
            user.disabled=True;s.execute(delete(LoginSession).where(LoginSession.user_id==user.id))
        print('Account disabled; browser sessions and machine access revoked.')


if __name__=='__main__': main()
