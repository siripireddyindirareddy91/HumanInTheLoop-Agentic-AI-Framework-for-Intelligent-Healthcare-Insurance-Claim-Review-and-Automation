"""Synthetic live deployment smoke test; does not print authentication tokens."""
import os, time, uuid, argparse
import httpx
parser=argparse.ArgumentParser(description='Read-only verification by default. Writing synthetic hosted records requires explicit operator authorization.')
parser.add_argument('--allow-synthetic-writes',action='store_true',help='Explicitly authorize creation of synthetic hosted records and a synthetic approval decision')
args=parser.parse_args()
base=os.getenv('SMOKE_URL','https://claimguard-ai-rosy.vercel.app')
with httpx.Client(base_url=base,timeout=60) as c:
    r=c.get('/api/health'); r.raise_for_status(); print('Health:',r.json()['status'])
    r=c.post('/api/auth/login',json={'email':'admin@claimguard.demo','password':os.getenv('DEMO_PASSWORD','ClaimGuard!2026')}); r.raise_for_status()
    c.headers['Authorization']='Bearer '+r.json()['access_token']
    if not args.allow_synthetic_writes:
        for path in ['/api/analytics','/api/knowledge/search?q=outpatient','/api/models','/api/reports/claims.csv']:
            r=c.get(path); r.raise_for_status(); print('Read-only check passed:',path)
        raise SystemExit(0)
    body={'reference':'SMOKE-'+uuid.uuid4().hex[:10],'patient':'SYN-SMOKE-'+uuid.uuid4().hex[:6],'provider':'Synthetic Smoke Test Provider','policy':'DEMO-HEALTH-2026','service_date':'2026-01-05','diagnosis':'M25.561','procedure':'99213','amount':1200,'claim_type':'Outpatient','description':'Synthetic deployment verification consultation; no real patient data.'}
    r=c.post('/api/claims',json=body); r.raise_for_status(); cid=r.json()['id']; print('Claim creation: passed')
    r=c.post(f'/api/claims/{cid}/documents',files={'file':('synthetic-visit.txt',b'Synthetic visit record. Diagnosis M25.561. Procedure 99213. Date 2026-01-05. Billed $1200.00.','text/plain')}); r.raise_for_status(); print('Document extraction: passed')
    r=c.post(f'/api/claims/{cid}/investigate'); r.raise_for_status()
    for _ in range(20):
        r=c.get(f'/api/claims/{cid}/investigation'); r.raise_for_status(); run=r.json()
        if run['status'] not in ('queued','running'): break
        time.sleep(1)
    assert run['status']=='waiting_for_human',run
    assert len(run['steps'])==11
    print('Eleven-agent investigation and human checkpoint: passed')
    evidence=run['state']['evidence'][0]['chunk_id']
    r=c.post(f'/api/reviews/{cid}/decision',json={'action':'approve','reason':'Synthetic deployment smoke test: human review confirms the cited demonstration policy and supplied synthetic document.','evidence':[evidence]}); r.raise_for_status(); assert r.json()['status']=='approved'
    print('Human approval and graph resume: passed')
    r=c.get('/api/audit/integrity'); r.raise_for_status(); assert r.json()['valid']; print('Audit integrity: passed')
    r=c.get('/api/reports/claims.csv'); r.raise_for_status(); print('CSV export: passed')
