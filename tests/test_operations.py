from sqlalchemy import select
from noesis.application.web import WebService
from noesis.persistence.transfer import transfer_sqlite
from noesis.persistence.web_models import Account


def test_read_only_transfer_preserves_data_and_rejects_nonempty_target(tmp_path):
    source = WebService(tmp_path/'source.db')
    uid = source.create_user('old', 'fourteen plus characters')
    source.mutate(uid, 'decks', {'name':'Preserved'}, 'one')
    target = WebService(tmp_path/'target.db')
    report = transfer_sqlite(tmp_path/'source.db', target.db)
    assert report['app_accounts'] == 1
    with target.db.read() as s: assert s.scalar(select(Account)).username == 'old'
    import pytest
    with pytest.raises(ValueError, match='empty'): transfer_sqlite(tmp_path/'source.db', target.db)
