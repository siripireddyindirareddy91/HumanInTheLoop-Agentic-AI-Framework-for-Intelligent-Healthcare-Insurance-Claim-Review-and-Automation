import os
os.environ['DATABASE_URL']='sqlite:///./test-claimguard.db'
os.environ['JWT_SECRET']='test-secret-for-automated-tests-only-123456'
os.environ['DEMO_MODE']='true'
from fastapi.testclient import TestClient
from backend.main import app
from backend.database import Base,engine

def test_full_workflow_and_guards():
    Base.metadata.drop_all(engine)
    with TestClient(app) as c:
        assert c.get('/api/claims').status_code==401
        login=c.post('/api/auth/login',json={'email':'admin@claimguard.demo','password':'ClaimGuard!2026'})
        assert login.status_code==200,login.text
        h={'Authorization':'Bearer '+login.json()['access_token']}
        assert c.get('/api/claims',headers=h).status_code==200
        body={'reference':'TEST-CLAIM-1','patient':'SYN-TEST-1','provider':'Test Provider','policy':'DEMO-HEALTH-2026','service_date':'2026-01-05','diagnosis':'M25.561','procedure':'99213','amount':1200,'claim_type':'Outpatient','description':'Synthetic outpatient consultation with clinical documentation.'}
        r=c.post('/api/claims',json=body,headers=h); assert r.status_code==201,r.text
        cid=r.json()['id']
        assert c.post('/api/claims',json=body,headers=h).status_code==409
        assert c.post(f'/api/reviews/{cid}/decision',json={'action':'approve','reason':'Reviewed documentation carefully.','evidence':['fake']},headers=h).status_code==409
        r=c.post(f'/api/claims/{cid}/documents',files={'file':('visit.txt',b'Synthetic clinical note. Date 2026-01-05. Diagnosis M25.561. Procedure 99213. Billed $1200.00.','text/plain')},headers=h); assert r.status_code==201,r.text
        r=c.post(f'/api/claims/{cid}/investigate',headers=h); assert r.status_code==200,r.text
        run=c.get(f'/api/claims/{cid}/investigation',headers=h).json()
        assert run['status']=='waiting_for_human',run
        assert len(run['steps'])==11,run
        assert len(run['state']['evidence'])>0
        assert c.post(f'/api/reviews/{cid}/decision',json={'action':'approve','reason':'Reviewed documentation carefully.','evidence':['fake']},headers=h).status_code==422
        chunk=run['state']['evidence'][0]['chunk_id']
        # Simulate worker cold start: recover from durable SQL checkpoint.
        from backend.workflow import CHECKPOINTER
        CHECKPOINTER.delete_thread(run['id'])
        r=c.post(f'/api/reviews/{cid}/decision',json={'action':'approve','reason':'Human review confirms documentation meets the cited demonstration policy.','evidence':[chunk]},headers=h)
        assert r.status_code==200,r.text
        assert r.json()['status']=='approved'
        assert c.post(f'/api/claims/{cid}/investigate',headers=h).status_code==409
        assert c.get('/api/audit/integrity',headers=h).json()['valid'] is True
        a=c.post('/api/auth/login',json={'email':'auditor@claimguard.demo','password':'ClaimGuard!2026'}).json()
        ah={'Authorization':'Bearer '+a['access_token']}
        assert c.post('/api/claims',json={**body,'reference':'FORBIDDEN'},headers=ah).status_code==403
        assert c.get('/api/reports/claims.csv',headers=ah).status_code==200
        assert c.get('/api/knowledge/search?q=outpatient',headers=h).json()
        assert c.post('/api/knowledge/upload',files={'file':('bad.exe',b'data')},headers=h).status_code==400
        assert c.get('/api/models',headers=h).json()['metrics'] is None
        assert c.post('/api/auth/login',json={'email':'admin@claimguard.demo','password':'wrong'}).status_code==401

def test_registration_cannot_escalate_role():
    with TestClient(app) as c:
        r=c.post('/api/auth/register',json={'email':'new@example.test','password':'VerySecure!12345','name':'Test Reviewer','role':'admin'})
        assert r.status_code==201,r.text
        assert r.json()['user']['role']=='claim_reviewer'
        h={'Authorization':'Bearer '+r.json()['access_token']}
        assert c.get('/api/admin/settings',headers=h).status_code==403
        reset=c.post('/api/auth/forgot-password',json={'email':'new@example.test'}).json()
        assert c.post('/api/auth/reset-password',json={'token':reset['demo_reset_token'],'password':'Replacement!12345'}).status_code==200
        assert c.post('/api/auth/reset-password',json={'token':reset['demo_reset_token'],'password':'Replacement!12345'}).status_code==400
