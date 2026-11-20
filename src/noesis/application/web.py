"""Authenticated product service. All web and remote MCP mutations pass here."""
from __future__ import annotations
import hashlib
import hmac
import secrets
import re
from datetime import timedelta
from sqlalchemy import select, delete
from noesis.application.common import add_event, as_utc, now_utc, get_idempotent, save_idempotent
from noesis.persistence.database import Database
from noesis.persistence.web_models import Account, LoginSession, Deck, Card, CardRevision, Proposal, StudySession, ReviewEvidence, ReviewInvalidation
from noesis.scheduler.fsrs_adapter import FsrsAdapter


class AppError(Exception):
    def __init__(self, message, status=400):
        self.status = status
        super().__init__(message)


def required(data, name, maximum=20000):
    value = data.get(name)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise AppError(f'{name} must be nonempty text (max {maximum})')
    return value.strip()


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    return salt + ':' + hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()


DUMMY_PASSWORD_HASH = password_hash('dummy verification password', '00'*16)


class WebService:
    def __init__(self, database=None, initialize=True):
        self.db = Database(database)
        if initialize:
            self.db.create_schema()
        self.scheduler = FsrsAdapter()

    def create_user(self, username, password):
        username = required({'username': username}, 'username', 128).casefold()
        if len(password) < 14 or len(password) > 1024:
            raise AppError('Password must contain 14–1024 characters')
        with self.db.transaction() as s:
            if s.scalar(select(Account).where(Account.username == username)):
                raise AppError('Account already exists', 409)
            user = Account(username=username, password_hash=password_hash(password))
            s.add(user); s.flush()
            return user.id

    def login(self, username, password):
        if not isinstance(username, str) or len(username) > 128 or not isinstance(password, str) or len(password) > 1024:
            raise AppError('Invalid credentials', 401)
        with self.db.transaction() as s:
            user = s.scalar(select(Account).where(Account.username == username.casefold()))
            stored = user.password_hash if user else DUMMY_PASSWORD_HASH
            if not hmac.compare_digest(password_hash(password, stored.split(':')[0]), stored) or not user or user.disabled:
                raise AppError('Invalid credentials', 401)
            s.execute(delete(LoginSession).where(LoginSession.expires_at <= now_utc()))
            token, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
            s.add(LoginSession(token_hash=digest(token), user_id=user.id, csrf=csrf, expires_at=now_utc()+timedelta(hours=12)))
            return token, csrf

    def access_owner(self, username):
        with self.db.read() as s:
            user = s.scalar(select(Account).where(Account.username == username.casefold()))
            if not user or user.disabled:
                raise AppError('Sign in required', 401)
            return user.id

    def authenticate(self, token):
        with self.db.read() as s:
            login = s.get(LoginSession, digest(token or ''))
            if not login or as_utc(login.expires_at) <= now_utc():
                raise AppError('Sign in required', 401)
            user = s.get(Account, login.user_id)
            if not user or user.disabled:
                raise AppError('Sign in required', 401)
            return user.id, login.csrf

    @staticmethod
    def owned(s, model, entity_id, uid):
        row = s.scalar(select(model).where(model.id == entity_id, model.user_id == uid).with_for_update())
        if not row:
            raise AppError('Not found', 404)
        return row

    @staticmethod
    def revision(s, card):
        return s.scalar(select(CardRevision).where(CardRevision.card_id == card.id, CardRevision.revision == card.revision)).content

    def card_payload(self, s, card):
        return {'id': card.id, 'deck_id': card.deck_id, 'status': card.status, 'revision': card.revision, 'due_at': as_utc(card.due_at).isoformat() if card.due_at else None, **self.revision(s, card)}

    def content(self, data):
        card_type = data.get('card_type','basic')
        if card_type not in ('basic','reversed','cloze'): raise AppError('Invalid card type')
        cloze_text = ''
        if card_type == 'cloze':
            cloze_text = data.get('cloze_text') or required(data, 'front')
            if '{{c1::' in str(data.get('front','')): cloze_text = data['front']
            if not re.search(r'\{\{c1::.+?\}\}', cloze_text, re.S): raise AppError('Cloze requires {{c1::answer}} in the question field')
            data = {**data, 'front':re.sub(r'\{\{c1::(.+?)\}\}', '[…]', cloze_text, flags=re.S), 'back':re.sub(r'\{\{c1::(.+?)\}\}', r'\1', cloze_text, flags=re.S)}
        return {'card_type':card_type, 'cloze_text':cloze_text, 'front': required(data, 'front'), 'back': required(data, 'back'),
                'source': str(data.get('source', ''))[:30000], 'source_type': str(data.get('source_type', 'notes'))[:64],
                'origin': str(data.get('origin', ''))[:2000], 'tags': str(data.get('tags', ''))[:1000],
                'explanation': str(data.get('explanation', ''))[:10000], 'uncertainty': str(data.get('uncertainty', ''))[:4000],
                'generation': data.get('generation', {}), 'captured_at': data.get('captured_at') or now_utc().isoformat()}

    def add_card(self, s, uid, deck_id, data):
        self.owned(s, Deck, deck_id, uid)
        card = Card(user_id=uid, deck_id=deck_id)
        s.add(card); s.flush()
        s.add(CardRevision(card_id=card.id, revision=1, content=self.content(data))); s.flush()
        return self.card_payload(s, card)

    def study_payload(self, s, study):
        while study.position < len(study.cards):
            card = self.owned(s, Card, study.cards[study.position]['id'], study.user_id)
            if card.status == 'active' and card.revision == study.cards[study.position]['revision']:
                break
            study.position += 1
            study.revealed = False
        if study.position >= len(study.cards):
            study.status = 'complete'
        payload = {'id': study.id, 'status': study.status, 'position': study.position, 'total': len(study.cards), 'revealed': study.revealed}
        if study.status == 'open':
            data = self.card_payload(s, card)
            payload['card'] = data if study.revealed else {k: data[k] for k in ('id', 'front', 'deck_id')}
        return payload

    def read(self, uid, resource):
        with self.db.read() as s:
            user = s.get(Account, uid)
            if not user or user.disabled:
                raise AppError('Sign in required', 401)
            cards = list(s.scalars(select(Card).where(Card.user_id == uid)))
            if resource == 'me':
                return {'username': user.username, 'preferences': user.preferences}
            if resource.startswith('cards/'):
                card = self.owned(s, Card, resource.split('/')[1], uid)
                history = list(s.scalars(select(ReviewEvidence).where(ReviewEvidence.user_id == uid, ReviewEvidence.card_id == card.id).order_by(ReviewEvidence.created_at.desc())))
                return {**self.card_payload(s, card), 'revisions':[{'revision':r.revision, 'content':r.content, 'created_at':as_utc(r.created_at).isoformat()} for r in s.scalars(select(CardRevision).where(CardRevision.card_id == card.id).order_by(CardRevision.revision))], 'history':[{'id':r.id,'grade':r.grade,'revision':r.revision,'created_at':as_utc(r.created_at).isoformat(),'next_due_at':r.transition['next_due_at']} for r in history]}
            if resource == 'cards':
                return [self.card_payload(s, c) for c in cards if c.status != 'deleted']
            if resource == 'decks':
                return [{'id': d.id, 'name': d.name, 'archived': d.archived, 'count': sum(c.deck_id == d.id and c.status != 'deleted' for c in cards)} for d in s.scalars(select(Deck).where(Deck.user_id == uid))]
            if resource == 'proposals':
                return [{'id': p.id, 'deck_id': p.deck_id, 'status': p.status, **p.payload} for p in s.scalars(select(Proposal).where(Proposal.user_id == uid, Proposal.status == 'pending'))]
            reviews = list(s.scalars(select(ReviewEvidence).where(ReviewEvidence.user_id == uid).order_by(ReviewEvidence.created_at.desc())))
            invalid = set(s.scalars(select(ReviewInvalidation.review_id).where(ReviewInvalidation.user_id == uid)))
            if resource == 'export':
                return {'format': 'noesis-web-v1', 'cards': [self.card_payload(s, c) for c in cards], 'reviews': [{'card_id': r.card_id, 'revision': r.revision, 'grade': r.grade, 'invalidated': r.id in invalid, 'response': r.response, 'transition': r.transition, 'created_at': as_utc(r.created_at).isoformat()} for r in reviews]}
            if resource == 'dashboard':
                active = [c for c in cards if c.status == 'active']
                days = [(now_utc()-timedelta(days=i)).date().isoformat() for i in reversed(range(14))]
                return {'total': len([c for c in cards if c.status != 'deleted']), 'due': sum(c.due_at is not None and as_utc(c.due_at) <= now_utc() for c in active), 'new': sum(not c.state for c in active), 'reviews': len(reviews), 'today': sum(as_utc(r.created_at).date() == now_utc().date() for r in reviews), 'grades': [sum(r.grade == g and r.id not in invalid for r in reviews) for g in range(1,5)], 'activity': [{'date': d, 'count': sum(as_utc(r.created_at).date().isoformat() == d for r in reviews)} for d in days], 'recent': [{'id': r.id, 'invalidated': r.id in invalid, 'card_id': r.card_id, 'grade': r.grade, 'created_at': as_utc(r.created_at).isoformat()} for r in reviews[:10]], 'suspended': sum(c.status == 'suspended' for c in cards)}
            raise AppError('Not found', 404)

    def cached(self, uid, operation, data, key):
        if not key or len(key) > 128: raise AppError('Idempotency-Key required (max 128)')
        with self.db.read() as s:
            return get_idempotent(s, 'web:'+operation, uid+':'+key, data)

    def mutate(self, uid, operation, data, key, request_data=None, correlation_id=None):
        if not key or len(key) > 128:
            raise AppError('Idempotency-Key required (max 128)')
        scoped_key = uid + ':' + key
        request_data = data if request_data is None else request_data
        with self.db.transaction() as s:
            # Lock the account to serialize per-user mutations on PostgreSQL too.
            user = s.scalar(select(Account).where(Account.id == uid).with_for_update())
            if not user or user.disabled:
                raise AppError('Sign in required', 401)
            cached = get_idempotent(s, 'web:'+operation, scoped_key, request_data)
            if cached is not None:
                return cached
            result = self._mutate(s, uid, user, operation, data)
            add_event(s, aggregate_type='web', aggregate_id=result.get('id', uid), event_type=operation, actor=uid, correlation_id=correlation_id or secrets.token_hex(16), idempotency_key=scoped_key, payload={'operation': operation, 'status': result.get('status'), 'revision': result.get('revision')})
            save_idempotent(s, 'web:'+operation, scoped_key, request_data, result)
            return result

    def _mutate(self, s, uid, user, operation, data):
        parts = operation.split('/')
        if operation == 'logout':
            s.execute(delete(LoginSession).where(LoginSession.user_id == uid))
            return {'ok': True}
        if operation == 'settings':
            try:
                prefs = {'daily_limit': int(data['daily_limit']), 'new_limit': int(data['new_limit']), 'retention': float(data['retention'])}
            except (KeyError, ValueError, TypeError):
                raise AppError('Invalid settings')
            if not 1 <= prefs['daily_limit'] <= 1000 or not 0 <= prefs['new_limit'] <= 1000 or not .7 <= prefs['retention'] <= .99:
                raise AppError('Settings outside supported range')
            user.preferences = prefs
            return prefs
        if operation == 'password':
            # Passwords are opaque: creation and login preserve whitespace too.
            current = data.get('current_password')
            if not isinstance(current, str) or not 1 <= len(current) <= 1024:
                raise AppError('current_password must contain 1–1024 characters')
            if not hmac.compare_digest(password_hash(current, user.password_hash.split(':')[0]), user.password_hash):
                raise AppError('Invalid credentials', 401)
            new = data.get('password')
            if not isinstance(new, str) or not 14 <= len(new) <= 1024:
                raise AppError('Password must contain 14–1024 characters')
            user.password_hash = password_hash(new)
            s.execute(delete(LoginSession).where(LoginSession.user_id == uid))
            return {'ok': True}
        if operation == 'decks':
            d = Deck(user_id=uid, name=required(data, 'name', 200)); s.add(d); s.flush()
            return {'id': d.id, 'name': d.name}
        if parts[0] == 'decks' and len(parts) == 2:
            d = self.owned(s, Deck, parts[1], uid)
            if 'name' in data: d.name = required(data, 'name', 200)
            if data.get('delete') is True:
                if data.get('confirm') != 'DELETE': raise AppError('Type DELETE to confirm')
                d.archived = True
                for c in s.scalars(select(Card).where(
                    Card.deck_id == d.id, Card.user_id == uid, Card.status != 'deleted',
                )): c.status = 'archived'
            return {'id': d.id, 'name': d.name}
        if operation == 'cards':
            result = self.add_card(s, uid, required(data, 'deck_id', 36), data)
            if data.get('card_type') == 'reversed':
                reverse = self.add_card(s, uid, data['deck_id'], {**data,'front':data['back'],'back':data['front'],'card_type':'basic'})
                result['reversed_id'] = reverse['id']
            return result
        if parts[0] == 'cards' and len(parts) == 2:
            c = self.owned(s, Card, parts[1], uid)
            if 'status' in data:
                if data['status'] not in ('active', 'suspended', 'archived', 'deleted'): raise AppError('Invalid status')
                if data['status'] == 'deleted' and data.get('confirm') != 'DELETE': raise AppError('Type DELETE to confirm')
                c.status = data['status']
            if any(k in data for k in ('front','back','source','source_type','origin','tags','explanation','uncertainty','card_type')):
                old = self.revision(s, c)
                if old.get('card_type') == 'cloze':
                    old = {**old, 'front':old['cloze_text']}
                    old.pop('cloze_text', None)
                content = self.content({**old, **data})
                c.revision += 1
                s.add(CardRevision(card_id=c.id, revision=c.revision, content=content)); s.flush()
            return self.card_payload(s, c)
        if operation in ('proposals', 'generation'):
            self.owned(s, Deck, data.get('deck_id'), uid)
            items = data.get('items')
            if not isinstance(items, list) or not 1 <= len(items) <= 30: raise AppError('Provide 1–30 proposal items')
            source = required(data, 'source', 30000)
            common = {k: data.get(k, '') for k in ('source_type', 'origin', 'generation')}
            common['source'] = source
            parsed = [self.content({**i, **common}) for i in items]
            existing = [self.revision(s,c)['front'].casefold() for c in s.scalars(select(Card).where(Card.user_id == uid))]
            for item in parsed: item['duplicate'] = item['front'].casefold() in existing
            p = Proposal(user_id=uid, deck_id=data['deck_id'], payload={'items': parsed, **common}); s.add(p); s.flush()
            return {'id': p.id, **p.payload}
        if parts[0] == 'proposals' and len(parts) == 3 and parts[2] == 'decide':
            p = self.owned(s, Proposal, parts[1], uid)
            if p.status != 'pending': raise AppError('Proposal already decided', 409)
            decisions = data.get('items', [])
            if len(decisions) != len(p.payload['items']): raise AppError('Decide every item')
            created = []
            for old, decision in zip(p.payload['items'], decisions):
                if decision.get('decision') not in ('approve', 'reject'): raise AppError('Invalid decision')
                if decision['decision'] == 'approve': created.append(self.add_card(s, uid, p.deck_id, {**old, **{k: decision[k] for k in ('front','back','explanation','tags','uncertainty') if k in decision}}))
            p.status = 'decided'
            p.payload = {**p.payload, 'decisions': decisions}
            return {'id': p.id, 'created': created}
        if operation == 'review/undo':
            evidence = self.owned(s, ReviewEvidence, data.get('review_id'), uid)
            if s.scalar(select(ReviewInvalidation).where(ReviewInvalidation.review_id == evidence.id)):
                raise AppError('Review already invalidated', 409)
            reason = required(data, 'reason', 1000)
            s.add(ReviewInvalidation(user_id=uid, review_id=evidence.id, reason=reason)); s.flush()
            invalid = set(s.scalars(select(ReviewInvalidation.review_id).where(ReviewInvalidation.user_id == uid)))
            card = self.owned(s, Card, evidence.card_id, uid)
            valid = list(s.scalars(select(ReviewEvidence).where(ReviewEvidence.user_id == uid, ReviewEvidence.card_id == card.id).order_by(ReviewEvidence.created_at, ReviewEvidence.id)))
            state, due = {}, None
            for r in valid:
                if r.id in invalid: continue
                rebuilt = self.scheduler.schedule(state or None, r.grade, as_utc(r.created_at), r.transition['retention'])
                state, due = rebuilt.state, rebuilt.next_due
            card.state, card.due_at = state, due
            return {'id': evidence.id, 'invalidated': True, 'next_due_at': due.isoformat() if due else None}
        if operation == 'review/start':
            study = s.scalar(select(StudySession).where(StudySession.user_id == uid, StudySession.status == 'open').order_by(StudySession.created_at))
            if not study:
                cards = list(s.scalars(select(Card).join(Deck, Deck.id == Card.deck_id).where(Card.user_id == uid, Card.status == 'active', Deck.archived.is_(False)).order_by(Card.due_at.asc().nullsfirst(), Card.id)))
                today = list(s.scalars(select(ReviewEvidence).where(ReviewEvidence.user_id == uid, ReviewEvidence.created_at >= now_utc().replace(hour=0,minute=0,second=0,microsecond=0))))
                new_used = sum(not r.transition['input'] for r in today)
                new_limit = max(0, user.preferences['new_limit']-new_used)
                due = [c for c in cards if c.state and c.due_at and as_utc(c.due_at) <= now_utc()]
                new = [c for c in cards if not c.state][:new_limit]
                selected = (due+new)[:max(0,user.preferences['daily_limit']-len(today))]
                study = StudySession(user_id=uid, cards=[{'id':c.id, 'revision':c.revision} for c in selected]); s.add(study); s.flush()
            return self.study_payload(s, study)
        if operation in ('review/reveal', 'review/grade'):
            study = self.owned(s, StudySession, data.get('session_id'), uid)
            self.study_payload(s, study)
            if study.status != 'open': raise AppError('Review complete', 409)
            if operation == 'review/reveal':
                study.revealed = True
                return self.study_payload(s, study)
            if not study.revealed: raise AppError('Reveal the answer first', 409)
            c = self.owned(s, Card, study.cards[study.position]['id'], uid)
            if data.get('card_id') != c.id: raise AppError('Current card changed', 409)
            grade = data.get('grade')
            if type(grade) is not int or grade not in (1,2,3,4): raise AppError('Invalid grade')
            now = now_utc()
            scheduled = self.scheduler.schedule(c.state or None, grade, now, user.preferences['retention'])
            transition = {'input': c.state, 'output': scheduled.state, 'next_due_at': scheduled.next_due.isoformat(), 'retention': user.preferences['retention'], 'scheduler': self.scheduler.version}
            evidence = ReviewEvidence(user_id=uid, session_id=study.id, position=study.position, card_id=c.id, revision=c.revision, grade=grade, response=str(data.get('response',''))[:20000], transition=transition, created_at=now)
            s.add(evidence); s.flush()
            c.state, c.due_at = scheduled.state, scheduled.next_due
            study.position += 1; study.revealed = False
            return {'id': evidence.id, 'next_due_at': scheduled.next_due.isoformat(), 'review': self.study_payload(s, study)}
        raise AppError('Not found', 404)
