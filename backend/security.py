import os, secrets, jwt, hashlib, json
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from argon2 import PasswordHasher
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from backend.database import Session, User, Audit, RevokedToken, now

DEMO = os.getenv('DEMO_MODE', 'true').lower() == 'true'
SECRET = os.getenv('JWT_SECRET')
if not SECRET:
    if not DEMO: raise RuntimeError('JWT_SECRET is required outside demonstration mode')
    SECRET = secrets.token_urlsafe(48)
hasher=PasswordHasher()
bearer=HTTPBearer(auto_error=False)
def token(user, kind='access'):
    return jwt.encode({'sub':user.id,'type':kind,'jti':str(uuid4()),'exp':datetime.now(timezone.utc)+timedelta(minutes=60 if kind=='access' else 1440)}, SECRET, algorithm='HS256')
def decode(value):
    try:
        payload=jwt.decode(value,SECRET,algorithms=['HS256'])
        with Session() as db:
            if db.get(RevokedToken,payload['jti']): raise ValueError('revoked')
        return payload
    except Exception: raise HTTPException(401,'Session expired or invalid. Please sign in.')
def current(credentials: HTTPAuthorizationCredentials | None=Depends(bearer)):
    if not credentials: raise HTTPException(401,'Sign in required')
    payload=decode(credentials.credentials)
    if payload.get('type')!='access': raise HTTPException(401,'Access token required')
    with Session() as db: user=db.get(User,payload['sub'])
    if not user or not user.active: raise HTTPException(401,'Account unavailable')
    return user
def roles(*allowed):
    def check(user=Depends(current)):
        if user.role not in allowed: raise HTTPException(403,'Your role does not permit this action')
        return user
    return check
def audit(db, actor, action, claim_id=None, **details):
    previous=db.scalars(select(Audit).order_by(Audit.created_at.desc(),Audit.id.desc())).first()
    row=Audit(id=str(uuid4()),actor=actor,action=action,claim_id=claim_id,details=details,created_at=now(),previous_hash=previous.hash if previous else '0'*64)
    row.hash=hashlib.sha256(json.dumps([row.previous_hash,row.id,row.actor,row.action,row.claim_id,row.details,row.created_at],sort_keys=True).encode()).hexdigest()
    db.add(row)
    return row
