import os
from datetime import datetime, timezone
from sqlalchemy import create_engine, String, Text, Float, ForeignKey, DateTime, Boolean, JSON, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

def now(): return datetime.now(timezone.utc).isoformat()
url = os.getenv('DATABASE_URL', 'sqlite:///' + ('/tmp/claimguard.db' if os.getenv('VERCEL') else './claimguard.db'))
if url.startswith('postgres://'): url = url.replace('postgres://', 'postgresql+psycopg://', 1)
if url.startswith('postgresql://'): url = url.replace('postgresql://', 'postgresql+psycopg://', 1)
engine = create_engine(url, connect_args={'check_same_thread': False} if url.startswith('sqlite') else {}, pool_pre_ping=True)
if url.startswith('sqlite'):
    @event.listens_for(engine, 'connect')
    def foreign_keys(connection, record):
        connection.execute('PRAGMA foreign_keys=ON')
Session = sessionmaker(engine, expire_on_commit=False)
class Base(DeclarativeBase): pass
class User(Base):
    __tablename__='users'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str] = mapped_column(String)
    password: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String, default='claim_reviewer')
    active: Mapped[bool] = mapped_column(Boolean, default=True)
class Claim(Base):
    __tablename__='claims'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    reference: Mapped[str] = mapped_column(String, unique=True)
    patient: Mapped[str] = mapped_column(String, index=True)
    provider: Mapped[str] = mapped_column(String)
    policy: Mapped[str] = mapped_column(String)
    service_date: Mapped[str] = mapped_column(String)
    diagnosis: Mapped[str] = mapped_column(String)
    procedure: Mapped[str] = mapped_column(String)
    amount: Mapped[float] = mapped_column(Float)
    claim_type: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default='submitted', index=True)
    risk: Mapped[float] = mapped_column(Float, default=0)
    assigned_to: Mapped[str | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[str] = mapped_column(String, default=now)
    updated_at: Mapped[str] = mapped_column(String, default=now)
class Document(Base):
    __tablename__='documents'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    claim_id: Mapped[str | None] = mapped_column(ForeignKey('claims.id'), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String)
    version: Mapped[str] = mapped_column(String, default='1.0')
    category: Mapped[str] = mapped_column(String, default='medical')
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    pages: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String, default=now)
class Chunk(Base):
    __tablename__='knowledge_chunks'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey('documents.id'))
    page: Mapped[int] = mapped_column()
    text: Mapped[str] = mapped_column(Text)
class Run(Base):
    __tablename__='agent_runs'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    claim_id: Mapped[str] = mapped_column(ForeignKey('claims.id'), index=True)
    status: Mapped[str] = mapped_column(String, default='queued')
    steps: Mapped[list] = mapped_column(JSON, default=list)
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String, default=now)
class Review(Base):
    __tablename__='human_reviews'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    claim_id: Mapped[str] = mapped_column(ForeignKey('claims.id'))
    reviewer_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    action: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String, default=now)
class Audit(Base):
    __tablename__='audit_logs'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    actor: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    claim_id: Mapped[str | None] = mapped_column(String, nullable=True)
    details: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String, default=now)
    previous_hash: Mapped[str] = mapped_column(String)
    hash: Mapped[str] = mapped_column(String)
class Setting(Base):
    __tablename__='system_settings'
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
class ResetToken(Base):
    __tablename__='password_reset_tokens'
    token_hash: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    expires: Mapped[float] = mapped_column(Float)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
class RevokedToken(Base):
    __tablename__='revoked_tokens'
    jti: Mapped[str] = mapped_column(String, primary_key=True)
