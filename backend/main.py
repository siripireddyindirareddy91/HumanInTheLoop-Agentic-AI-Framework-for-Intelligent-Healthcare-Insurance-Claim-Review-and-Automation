import os, csv, io, secrets, hashlib, time, re
from uuid import uuid4
from datetime import date, timedelta
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, func
from backend.database import Base, engine, Session, User, Claim, Document, Run, Review, Audit, Setting, ResetToken, RevokedToken, now
from backend.security import current, roles, token, decode, hasher, audit, DEMO
from backend.documents import extract, structured
from backend.retrieval import index_document, search
from backend.workflow import investigate, resume, AGENTS

def uid(): return str(uuid4())
def serialize(row): return {c.name:getattr(row,c.name) for c in row.__table__.columns if c.name!='password'}
def get_claim(db,cid):
    c=db.get(Claim,cid)
    if not c: raise HTTPException(404,'Claim not found')
    return c
REVIEW_ROLES=('admin','claim_reviewer','senior_reviewer','medical_reviewer','fraud_investigator','policy_specialist')
def seed():
    Base.metadata.create_all(engine)
    with Session() as db:
        if not DEMO or db.scalar(select(func.count()).select_from(User)): return
        password=hasher.hash(os.getenv('DEMO_PASSWORD','ClaimGuard!2026'))
        for role,name in [('admin','Alex Morgan'),('claim_reviewer','Jordan Lee'),('senior_reviewer','Priya Sharma'),('medical_reviewer','Dr. Sam Rivera'),('fraud_investigator','Taylor Chen'),('policy_specialist','Avery Wilson'),('auditor','Casey Brooks')]:
            db.add(User(id=role,email=role+'@claimguard.demo',name=name,password=password,role=role))
        db.flush()
        descriptions=['Outpatient orthopedic consultation and supporting evaluation','Diagnostic imaging for persistent knee pain','Hospital admission and surgical procedure','Preventive outpatient consultation','Physical therapy rehabilitation session','Emergency department evaluation']
        for i in range(18):
            db.add(Claim(id=f'demo-{i+1:03}',reference=f'CLM-2026-{1042+i}',patient=f'SYN-P-{100+i}',provider=['Northstar Medical Center','Evergreen Health Partners','Summit Orthopedics','Riverside Community Hospital'][i%4],policy='DEMO-HEALTH-2026',service_date=(date.today()-timedelta(days=i+2)).isoformat(),diagnosis=['M25.561','Z00.00','R07.9'][i%3],procedure=['99213','73721','27447','99214','97110','99285'][i%6],amount=[2450,850,18750,325,1200,5200,680,3100,22800][i%9],claim_type=['Outpatient','Imaging','Inpatient','Preventive','Rehabilitation','Emergency'][i%6],description=descriptions[i%6],status='submitted',created_by='admin',created_at=(date.today()-timedelta(days=i)).isoformat()+'T10:00:00+00:00'))
        d=Document(id='demo-policy',name='Demonstration Health Plan 2026.txt',category='coverage',version='2026.1',pages=[{'page':1,'text':'SYNTHETIC DEMONSTRATION POLICY — DEMO-HEALTH-2026. Effective January 1, 2026 through December 31, 2026. Section 1: Outpatient consultations and diagnostic imaging may be covered subject to documented clinical indication, eligibility and benefit limits. Section 2: Elective inpatient procedures require prior authorization evidence. Section 3: Claims must include itemized billing, diagnosis, procedure codes and clinical documentation. Missing evidence requires additional information. Section 4: No automated system may issue a final denial or authorize payment. This fictional policy is for software demonstration only.'}])
        db.add(d); db.flush(); index_document(db,d)
        audit(db,'system','demo.seeded',synthetic=True); db.commit()

@asynccontextmanager
async def lifespan(app): seed(); yield
app=FastAPI(title='ClaimGuard AI',version='1.0.0',description='Administrative decision support. Human authorization required for consequential decisions.',lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=os.getenv('CORS_ORIGINS','http://localhost:3000').split(','),allow_credentials=True,allow_methods=['GET','POST','PUT','PATCH','DELETE'],allow_headers=['Authorization','Content-Type'])

@app.middleware('http')
async def headers(request,call_next):
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'; response.headers['Cache-Control']='no-store'; response.headers['X-Frame-Options']='DENY'
    return response

class Login(BaseModel): email:str=Field(max_length=254); password:str=Field(min_length=1,max_length=128)
class Register(Login): name:str=Field(min_length=2,max_length=100)
class TokenBody(BaseModel): refresh_token:str
@app.get('/api/health')
def health():
    with Session() as db: db.execute(select(1))
    return {'status':'healthy','demo_mode':DEMO,'storage':'ephemeral serverless demonstration' if os.getenv('VERCEL') and not os.getenv('DATABASE_URL') else 'persistent database','llm':'local deterministic evidence analysis','agents':len(AGENTS)}
@app.post('/api/auth/login')
def login(body:Login):
    with Session() as db:
        u=db.scalar(select(User).where(User.email==body.email.lower().strip()))
        try:
            if not u or not u.active: raise ValueError()
            hasher.verify(u.password,body.password)
        except Exception: raise HTTPException(401,'Invalid email or password')
        audit(db,u.id,'auth.login'); db.commit()
        return {'access_token':token(u),'refresh_token':token(u,'refresh'),'user':serialize(u)}
@app.post('/api/auth/register',status_code=201)
def register(body:Register):
    email=body.email.lower().strip()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email) or len(body.password)<12: raise HTTPException(422,'Use a valid email and a password of at least 12 characters')
    with Session() as db:
        if db.scalar(select(User).where(User.email==email)): raise HTTPException(409,'Email already registered')
        u=User(id=uid(),email=email,name=body.name.strip(),password=hasher.hash(body.password),role='claim_reviewer'); db.add(u); db.flush(); audit(db,u.id,'auth.register'); db.commit()
        return {'access_token':token(u),'refresh_token':token(u,'refresh'),'user':serialize(u)}
@app.get('/api/auth/me')
def me(u=Depends(current)): return serialize(u)
@app.post('/api/auth/refresh')
def refresh(body:TokenBody):
    p=decode(body.refresh_token)
    if p.get('type')!='refresh': raise HTTPException(401,'Refresh token required')
    with Session() as db:
        u=db.get(User,p['sub'])
        if not u or not u.active: raise HTTPException(401,'Account unavailable')
        db.add(RevokedToken(jti=p['jti'])); db.commit()
        return {'access_token':token(u),'refresh_token':token(u,'refresh')}
@app.post('/api/auth/logout')
def logout(body:TokenBody,u=Depends(current)):
    p=decode(body.refresh_token)
    if p['sub']!=u.id: raise HTTPException(403,'Token owner mismatch')
    with Session() as db: db.add(RevokedToken(jti=p['jti'])); audit(db,u.id,'auth.logout'); db.commit()
    return {'ok':True}
class Forgot(BaseModel): email:str
@app.post('/api/auth/forgot-password')
def forgot(body:Forgot):
    result={'message':'If the account exists, a reset request has been created. Contact your administrator; email delivery is not configured.'}
    with Session() as db:
        u=db.scalar(select(User).where(User.email==body.email.lower()))
        if u:
            raw=secrets.token_urlsafe(32); db.add(ResetToken(token_hash=hashlib.sha256(raw.encode()).hexdigest(),user_id=u.id,expires=time.time()+900)); audit(db,u.id,'auth.reset_requested'); db.commit()
            if DEMO: result['demo_reset_token']=raw
    return result
class Reset(BaseModel): token:str; password:str=Field(min_length=12,max_length=128)
@app.post('/api/auth/reset-password')
def reset(body:Reset):
    with Session() as db:
        t=db.get(ResetToken,hashlib.sha256(body.token.encode()).hexdigest())
        if not t or t.used or t.expires<time.time(): raise HTTPException(400,'Reset token invalid or expired')
        u=db.get(User,t.user_id); u.password=hasher.hash(body.password); t.used=True; audit(db,u.id,'auth.password_reset'); db.commit()
    return {'ok':True}

class ClaimInput(BaseModel):
    reference:str=Field(min_length=3,max_length=80)
    patient:str=Field(min_length=2,max_length=100)
    provider:str=Field(min_length=2,max_length=150)
    policy:str=Field(min_length=2,max_length=100)
    service_date:date
    diagnosis:str=Field(min_length=3,max_length=20)
    procedure:str=Field(min_length=3,max_length=20)
    amount:float=Field(gt=0,le=10000000,allow_inf_nan=False)
    claim_type:str=Field(min_length=2,max_length=50)
    description:str=Field(min_length=10,max_length=10000)
    @field_validator('service_date')
    @classmethod
    def valid_date(cls,v):
        if v>date.today(): raise ValueError('Date of service cannot be in the future')
        return v
@app.get('/api/claims')
def claims(q:str='',status:str='',risk:str='',u=Depends(current)):
    with Session() as db:
        stmt=select(Claim).order_by(Claim.created_at.desc())
        if q: stmt=stmt.where(Claim.reference.ilike(f'%{q}%')|Claim.patient.ilike(f'%{q}%')|Claim.provider.ilike(f'%{q}%'))
        if status: stmt=stmt.where(Claim.status==status)
        if risk=='high': stmt=stmt.where(Claim.risk>=65)
        return [serialize(c) for c in db.scalars(stmt.limit(500))]
@app.post('/api/claims',status_code=201)
def create_claim(body:ClaimInput,u=Depends(roles(*REVIEW_ROLES))):
    with Session() as db:
        if db.scalar(select(Claim).where(Claim.reference==body.reference)): raise HTTPException(409,'Claim reference already exists')
        data=body.model_dump(); data['service_date']=body.service_date.isoformat()
        c=Claim(id=uid(),created_by=u.id,**data); db.add(c); db.flush(); audit(db,u.id,'claim.created',c.id); db.commit(); return serialize(c)
@app.get('/api/claims/{cid}')
def detail(cid:str,u=Depends(current)):
    with Session() as db:
        c=get_claim(db,cid); result=serialize(c)
        result['documents']=[{**serialize(d),'extracted':structured(d.pages)} for d in db.scalars(select(Document).where(Document.claim_id==cid))]
        result['reviews']=[serialize(r) for r in db.scalars(select(Review).where(Review.claim_id==cid))]
        run=db.scalar(select(Run).where(Run.claim_id==cid).order_by(Run.created_at.desc())); result['investigation']=serialize(run) if run else None
        result['reviewer']=serialize(db.get(User,c.assigned_to)) if c.assigned_to else None
        return result
@app.put('/api/claims/{cid}')
def update_claim(cid:str,body:ClaimInput,u=Depends(roles(*REVIEW_ROLES))):
    with Session() as db:
        c=get_claim(db,cid)
        if c.status not in ['submitted','returned','awaiting_information']: raise HTTPException(409,'Return claim for correction before editing')
        for k,v in body.model_dump().items(): setattr(c,k,v.isoformat() if isinstance(v,date) else v)
        c.updated_at=now(); c.risk=0; c.status='submitted'; audit(db,u.id,'claim.updated',cid); db.commit(); return serialize(c)

async def save_document(db,file,claim_id=None,category='medical',version='1.0'):
    data=await file.read(10*1024*1024+1); pages=extract(file.filename or 'unnamed',data)
    d=Document(id=uid(),name=os.path.basename(file.filename or 'document'),claim_id=claim_id,pages=pages,category=category,version=version)
    db.add(d); db.flush()
    if not claim_id: index_document(db,d)
    return d
@app.post('/api/claims/{cid}/documents',status_code=201)
async def upload_claim(cid:str,file:UploadFile=File(...),u=Depends(roles(*REVIEW_ROLES))):
    with Session() as db:
        c=get_claim(db,cid)
        if c.status in ['approved','denied']: raise HTTPException(409,'Finalized claim is read-only')
        d=await save_document(db,file,cid); audit(db,u.id,'document.uploaded',cid,document_id=d.id); db.commit(); return serialize(d)
@app.get('/api/claims/{cid}/documents')
def claim_documents(cid:str,u=Depends(current)):
    with Session() as db: get_claim(db,cid); return [serialize(d) for d in db.scalars(select(Document).where(Document.claim_id==cid))]
@app.post('/api/claims/{cid}/investigate')
def start(cid:str,bg:BackgroundTasks,u=Depends(roles(*REVIEW_ROLES))):
    with Session() as db:
        c=get_claim(db,cid)
        if c.status in ['approved','denied']: raise HTTPException(409,'Finalized claim cannot be reinvestigated')
        running=db.scalar(select(Run).where(Run.claim_id==cid,Run.status.in_(['queued','running'])))
        if running: return serialize(running)
        run=Run(id=uid(),claim_id=cid,status='queued',steps=[],state={}); db.add(run); c.status='investigating'; audit(db,u.id,'investigation.started',cid,run_id=run.id); db.commit()
        bg.add_task(investigate,cid,run.id); return serialize(run)
@app.get('/api/claims/{cid}/investigation')
@app.get('/api/claims/{cid}/agents')
def investigation(cid:str,u=Depends(current)):
    with Session() as db:
        get_claim(db,cid); run=db.scalar(select(Run).where(Run.claim_id==cid).order_by(Run.created_at.desc())); return serialize(run) if run else None
@app.get('/api/agents/runs/{rid}')
def get_run(rid:str,u=Depends(current)):
    with Session() as db:
        r=db.get(Run,rid)
        if not r: raise HTTPException(404,'Run not found')
        return serialize(r)
@app.get('/api/reviews/pending')
def pending(u=Depends(current)):
    with Session() as db: return [serialize(c) for c in db.scalars(select(Claim).where(Claim.status.in_(['in_review','awaiting_information','escalated'])))]
class Decision(BaseModel):
    action:str
    reason:str=Field(min_length=15,max_length=5000)
    evidence:list[str]=Field(default_factory=list,max_length=30)
    @field_validator('reason')
    @classmethod
    def meaningful_reason(cls,value):
        value=value.strip()
        if len(value)<15: raise ValueError('Provide at least 15 non-padding characters explaining your decision')
        return value
@app.post('/api/reviews/{cid}/decision')
@app.post('/api/reviews/{cid}/request-information')
@app.post('/api/reviews/{cid}/escalate')
def decision(cid:str,body:Decision,u=Depends(roles(*REVIEW_ROLES))):
    actions={'approve':'approved','deny':'denied','request_information':'awaiting_information','escalate':'escalated','medical_review':'escalated','investigation':'escalated','return':'returned'}
    if body.action not in actions: raise HTTPException(422,'Unknown review action')
    with Session() as db:
        c=get_claim(db,cid)
        if c.status in ['approved','denied']: raise HTTPException(409,'Claim has already been finalized')
        if c.assigned_to and c.assigned_to!=u.id and u.role not in ['admin','senior_reviewer']: raise HTTPException(403,'Claim is assigned to another reviewer')
        run=db.scalar(select(Run).where(Run.claim_id==cid).order_by(Run.created_at.desc()))
        if body.action in ['approve','deny']:
            if not run or run.status!='waiting_for_human': raise HTTPException(409,'Complete investigation before a final human decision')
            if not body.evidence: raise HTTPException(422,'Select supporting evidence for a final decision')
            allowed={e['chunk_id'] for e in run.state.get('evidence',[])}|{d.id for d in db.scalars(select(Document).where(Document.claim_id==cid))}
            if any(e not in allowed for e in body.evidence): raise HTTPException(422,'Evidence must belong to this investigation')
            if body.action=='deny' and not set(body.evidence)&{e['chunk_id'] for e in run.state.get('evidence',[])}: raise HTTPException(422,'Denial requires a cited policy passage and a policy-grounded reason')
            if body.action=='deny' and u.role not in ['admin','senior_reviewer']: raise HTTPException(403,'Denial requires senior reviewer authorization')
        previous=c.status
        if body.action in ['approve','deny']:
            resume(run,{'actor':u.id,**body.model_dump()})
            run.status='completed'; run.state={**run.state,'human_decision':{'actor':u.id,**body.model_dump()}}
        c.status=actions[body.action]; c.updated_at=now()
        db.add(Review(id=uid(),claim_id=cid,reviewer_id=u.id,action=body.action,reason=body.reason.strip(),evidence=body.evidence))
        audit(db,u.id,'review.'+body.action,cid,previous=previous,new=c.status,reason=body.reason,evidence=body.evidence,review_process='Request reconsideration through an authorized senior reviewer; no payment is executed.')
        db.commit(); return serialize(c)
class Assignment(BaseModel): claim_id:str; reviewer_id:str
@app.post('/api/reviews/assign')
def assign(body:Assignment,u=Depends(roles('admin','senior_reviewer'))):
    with Session() as db:
        c=get_claim(db,body.claim_id); reviewer=db.get(User,body.reviewer_id)
        if not reviewer or not reviewer.active or reviewer.role not in REVIEW_ROLES: raise HTTPException(422,'Invalid reviewer')
        c.assigned_to=reviewer.id; audit(db,u.id,'review.assigned',c.id,reviewer=reviewer.id); db.commit(); return serialize(c)

@app.post('/api/knowledge/upload',status_code=201)
async def upload_knowledge(file:UploadFile=File(...),category:str=Form('coverage'),version:str=Form('1.0'),u=Depends(roles('admin','policy_specialist'))):
    with Session() as db:
        d=await save_document(db,file,category=category,version=version); audit(db,u.id,'knowledge.uploaded',document_id=d.id); db.commit(); return serialize(d)
@app.get('/api/knowledge/documents')
def knowledge(u=Depends(current)):
    with Session() as db: return [serialize(d) for d in db.scalars(select(Document).where(Document.claim_id==None).order_by(Document.created_at.desc()))]
@app.get('/api/knowledge/search')
def retrieval(q:str='',u=Depends(current)):
    with Session() as db: return search(db,q)
@app.delete('/api/knowledge/documents/{did}')
def deactivate(did:str,u=Depends(roles('admin','policy_specialist'))):
    with Session() as db:
        d=db.get(Document,did)
        if not d or d.claim_id: raise HTTPException(404,'Knowledge document not found')
        d.active=False; audit(db,u.id,'knowledge.deactivated',document_id=did); db.commit(); return {'ok':True}

@app.get('/api/analytics')
@app.get('/api/dashboard')
def analytics(u=Depends(current)):
    with Session() as db:
        rows=db.scalars(select(Claim)).all(); runs=db.scalars(select(Run)).all(); reviews=db.scalars(select(Review)).all()
        statuses={s:sum(c.status==s for c in rows) for s in ['submitted','investigating','in_review','approved','denied','awaiting_information','escalated','returned']}
        trend={}
        for c in rows: trend[c.created_at[:10]]=trend.get(c.created_at[:10],0)+1
        return {'total':len(rows),'total_value':sum(c.amount for c in rows),'statuses':statuses,'high_risk':sum(c.risk>=65 for c in rows),'risk_distribution':{'Low':sum(c.risk<35 for c in rows),'Medium':sum(35<=c.risk<65 for c in rows),'High':sum(c.risk>=65 for c in rows)},'trend':[{'date':k,'claims':v} for k,v in sorted(trend.items())],'agents':[{'name':label,'runs':sum(any(s['agent']==key for s in r.steps) for r in runs),'duration_ms':sum(s['duration_ms'] for r in runs for s in r.steps if s['agent']==key)} for key,label in AGENTS],'reviews':len(reviews),'reviewers':[{'name':x.name,'role':x.role,'assigned':sum(c.assigned_to==x.id for c in rows),'completed':sum(r.reviewer_id==x.id for r in reviews)} for x in db.scalars(select(User).where(User.active==True))]}
@app.get('/api/reports/claims.csv')
def export(u=Depends(roles('admin','senior_reviewer','auditor'))):
    with Session() as db:
        out=io.StringIO(); writer=csv.writer(out); writer.writerow(['reference','patient','provider','amount','status','risk','created_at'])
        for c in db.scalars(select(Claim)):
            values=[c.reference,c.patient,c.provider,c.amount,c.status,c.risk,c.created_at]
            writer.writerow(["'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v for v in values])
        return Response(out.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename=claimguard-claims.csv'})
@app.get('/api/audit')
def audits(u=Depends(roles('admin','senior_reviewer','auditor'))):
    with Session() as db: return [serialize(a) for a in db.scalars(select(Audit).order_by(Audit.created_at.desc()).limit(1000))]
@app.get('/api/audit/integrity')
def integrity(u=Depends(roles('admin','auditor'))):
    with Session() as db:
        import json
        rows=db.scalars(select(Audit).order_by(Audit.created_at,Audit.id)).all(); previous='0'*64
        for a in rows:
            expected=hashlib.sha256(json.dumps([a.previous_hash,a.id,a.actor,a.action,a.claim_id,a.details,a.created_at],sort_keys=True).encode()).hexdigest()
            if a.hash!=expected or a.previous_hash!=previous: return {'valid':False,'record':a.id}
            previous=a.hash
        return {'valid':True,'records':len(rows),'head':previous}
@app.get('/api/admin/users')
def users(u=Depends(roles('admin','senior_reviewer'))):
    with Session() as db: return [serialize(x) for x in db.scalars(select(User))]
class UserUpdate(BaseModel): role:str; active:bool=True
@app.patch('/api/admin/users/{user_id}')
def update_user(user_id:str,body:UserUpdate,u=Depends(roles('admin'))):
    if body.role not in [*REVIEW_ROLES,'auditor']: raise HTTPException(422,'Invalid role')
    if u.id==user_id: raise HTTPException(409,'Cannot change own administrator access')
    with Session() as db:
        x=db.get(User,user_id)
        if not x: raise HTTPException(404,'User not found')
        x.role=body.role; x.active=body.active; audit(db,u.id,'user.updated',user_id=user_id,role=body.role,active=body.active); db.commit(); return serialize(x)
@app.get('/api/admin/settings')
def settings(u=Depends(roles('admin'))):
    return {'provider':'Local deterministic analysis','rag':'BM25 + character TF-IDF lexical hybrid','coding':'Format validation only; no licensed catalog','risk':'Transparent additive administrative indicator','ocr':'Tesseract (requires system installation)','decision_policy':'Human authorization required','demo_mode':DEMO}
@app.get('/api/models')
def models(u=Depends(current)):
    return {'name':'Isolation Forest','version':'demo-1.0','provenance':'Current synthetic demonstration claim records only; fitted per investigation','supervised_model':None,'metrics':None,'limitations':['Not clinically validated','No labeled real-world training dataset','No fraud probability calibration','Accuracy, precision, recall and ROC-AUC are unavailable without labeled validation data']}
