"""Standalone app tables; legacy domain tables remain intact."""
from datetime import datetime
from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from noesis.persistence.models import Base, new_id, utcnow


class Account(Base):
    __tablename__ = 'app_accounts'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(128), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    preferences: Mapped[dict] = mapped_column(JSON, default=lambda: {'daily_limit': 50, 'new_limit': 10, 'retention': 0.9})
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LoginSession(Base):
    __tablename__ = 'app_login_sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('app_accounts.id'), index=True)
    csrf: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Deck(Base):
    __tablename__ = 'app_decks'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey('app_accounts.id'), index=True)
    name: Mapped[str] = mapped_column(String(200))
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class Card(Base):
    __tablename__ = 'app_cards'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey('app_accounts.id'), index=True)
    deck_id: Mapped[str] = mapped_column(ForeignKey('app_decks.id'), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(24), default='active')
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class CardRevision(Base):
    __tablename__ = 'app_card_revisions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    card_id: Mapped[str] = mapped_column(ForeignKey('app_cards.id'), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint('card_id', 'revision'),)


class Proposal(Base):
    __tablename__ = 'app_proposals'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey('app_accounts.id'), index=True)
    deck_id: Mapped[str] = mapped_column(ForeignKey('app_decks.id'))
    status: Mapped[str] = mapped_column(String(24), default='pending')
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StudySession(Base):
    __tablename__ = 'app_study_sessions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey('app_accounts.id'), index=True)
    cards: Mapped[list] = mapped_column(JSON)
    position: Mapped[int] = mapped_column(Integer, default=0)
    revealed: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(24), default='open')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReviewEvidence(Base):
    __tablename__ = 'app_review_evidence'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey('app_accounts.id'), index=True)
    session_id: Mapped[str] = mapped_column(ForeignKey('app_study_sessions.id'))
    position: Mapped[int] = mapped_column(Integer)
    card_id: Mapped[str] = mapped_column(ForeignKey('app_cards.id'), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    grade: Mapped[int] = mapped_column(Integer)
    response: Mapped[str] = mapped_column(Text, default='')
    transition: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint('session_id', 'position'),)


class ReviewInvalidation(Base):
    __tablename__ = 'app_review_invalidations'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey('app_accounts.id'), index=True)
    review_id: Mapped[str] = mapped_column(ForeignKey('app_review_evidence.id'), unique=True)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
