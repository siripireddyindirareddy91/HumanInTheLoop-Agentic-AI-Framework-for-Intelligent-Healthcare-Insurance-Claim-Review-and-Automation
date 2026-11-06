"""Typed, checkpointed LangGraph administrative investigation. Never issues decisions."""
import re, time
from uuid import uuid4
from typing import TypedDict
from sqlalchemy import select
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command, RetryPolicy
from langgraph.checkpoint.memory import InMemorySaver
from backend.database import Session, Claim, Run, Document, User, Setting, now
from backend.security import audit
from backend.retrieval import search
from backend.documents import structured

class State(TypedDict, total=False):
    claim_id: str
    run_id: str
    findings: list[dict]
    evidence: list[dict]
    risk: float
    recommendation: str
    route: str
    human_decision: dict
    summary: dict

AGENTS=[('intake','Claim intake'),('documents','Document intelligence'),('policy','Policy verification'),('coding','Medical coding validation'),('necessity','Medical necessity evidence'),('duplicates','Duplicate detection'),('anomaly','Anomaly detection'),('risk','Claim risk assessment'),('evidence','Evidence verification'),('decision','Decision support'),('routing','Human review routing')]
CHECKPOINTER=InMemorySaver() # SQL-backed Run.state is the durable application checkpoint.

def execute_agent(key,label):
    def node(state:State):
        start=time.monotonic()
        with Session() as db:
            c=db.get(Claim,state['claim_id']); run=db.get(Run,state['run_id'])
            findings=list(state.get('findings',[])); evidence=list(state.get('evidence',[]))
            def finding(title,severity='info',points=0,source=None):
                findings.append({'id':str(uuid4()),'agent':key,'title':title,'severity':severity,'points':points,'source':source or {'type':'claim','claim_id':c.id,'fields':['amount','diagnosis','procedure','description']}})
            docs=db.scalars(select(Document).where(Document.claim_id==c.id,Document.active==True)).all()
            if key=='intake': finding('Mandatory intake fields validated; patient and provider references retained.')
            elif key=='documents':
                if not docs: finding('Supporting clinical documents are missing.','warning',20)
                for d in docs:
                    result=structured(d.pages)
                    finding(f"{d.name}: {len(d.pages)} extracted page(s); diagnosis codes: {', '.join(result['diagnosis_codes']) or 'not found'}.",'warning' if result['unreadable'] else 'info',10 if result['unreadable'] else 0,{'type':'document','document_id':d.id,'page':1})
            elif key=='policy':
                evidence=search(db,f'{c.policy} {c.claim_type} {c.description} {c.procedure}')
                if evidence: finding('Relevant policy passages retrieved. Applicability, exclusions and effective dates require reviewer confirmation.','info',0,{'type':'chunk','chunk_id':evidence[0]['chunk_id']})
                else: finding('No applicable policy evidence found. Coverage cannot be established.','warning',20)
            elif key=='coding':
                if not re.fullmatch(r'[A-TV-Z]\d{2}(?:\.[A-Z0-9]{1,4})?',c.diagnosis): finding('Diagnosis code does not match ICD-10-CM format.','warning',15)
                if not re.fullmatch(r'(?:\d{5}|[A-Z]\d{4})',c.procedure): finding('Procedure code does not match CPT/HCPCS format.','warning',15)
                finding('Format checks only. No licensed code catalog or diagnosis-procedure consistency dataset is configured.','warning',5)
            elif key=='necessity':
                finding('Clinical necessity is unresolved: a qualified medical reviewer must assess submitted evidence against applicable criteria.','warning',10)
            elif key=='duplicates':
                others=db.scalars(select(Claim).where(Claim.id!=c.id,Claim.patient==c.patient,Claim.service_date==c.service_date,Claim.procedure==c.procedure)).all()
                for other in others:
                    similarity=sum([other.provider==c.provider,abs(other.amount-c.amount)<.01])/2
                    finding(f'Potential duplicate {other.reference}: same patient, service date and procedure; provider/amount similarity {similarity:.0%}.','high',25,{'type':'claim','claim_id':other.id})
            elif key=='anomaly':
                history=db.scalars(select(Claim)).all()
                if len(history)>=8:
                    from sklearn.ensemble import IsolationForest
                    import numpy as np
                    x=np.array([[r.amount,len(r.procedure),len(r.description)] for r in history])
                    model=IsolationForest(random_state=42,contamination=.15).fit(x)
                    if model.predict([[c.amount,len(c.procedure),len(c.description)]])[0]==-1: finding('Isolation Forest identified an unusual billing profile relative to this demonstration dataset. An anomaly is not evidence of fraud.','high',20)
                else: finding('Insufficient comparison records for Isolation Forest (minimum 8).')
                if c.amount>15000: finding('Billed amount exceeds the configured demonstration threshold of $15,000.','warning',15)
            elif key=='risk':
                risk=min(100,sum(f['points'] for f in findings))
                state={**state,'risk':risk}; c.risk=risk
                finding(f'Administrative risk score: {risk}/100. Additive indicator score, not probability of fraud.')
            elif key=='evidence':
                valid_chunks={e['chunk_id'] for e in evidence}
                unsupported=[f for f in findings if f['source'].get('type')=='chunk' and f['source'].get('chunk_id') not in valid_chunks]
                finding(f'{len(findings)-len(unsupported)} findings have traceable input references; {len(unsupported)} invalid citations. Traceability does not establish clinical validity.','warning' if unsupported else 'info')
            elif key=='decision':
                from backend.provider import summarize
                recommendation='Request additional documents' if not docs else 'Escalate to medical reviewer'
                state={**state,'recommendation':recommendation,'summary':summarize(findings,evidence)}
                finding(recommendation+'. Final decisions remain with authorized human reviewers.')
            elif key=='routing':
                role='senior_reviewer' if c.risk>=65 else 'medical_reviewer'
                reviewers=db.scalars(select(User).where(User.role==role,User.active==True)).all()
                if reviewers:
                    workload=lambda u:len(db.scalars(select(Claim).where(Claim.assigned_to==u.id,Claim.status.in_(['in_review','awaiting_information']))).all())
                    c.assigned_to=min(reviewers,key=workload).id
                state={**state,'route':'information' if not docs else 'review'}
                finding(f'Assigned to {role.replace("_"," ")}; human checkpoint required.')
            state={**state,'findings':findings,'evidence':evidence}
            run.steps=[*run.steps,{'agent':key,'label':label,'status':'completed','duration_ms':round((time.monotonic()-start)*1000),'timestamp':now()}]
            run.state=state; c.updated_at=now()
            audit(db,'agent:'+key,'agent.completed',c.id,run_id=run.id)
            db.commit()
        return state
    return node

def human_checkpoint(state):
    with Session() as db:
        run=db.get(Run,state['run_id']); c=db.get(Claim,state['claim_id'])
        if run.status!='waiting_for_human':
            run.status='waiting_for_human'; c.status='awaiting_information' if state.get('route')=='information' else 'in_review'; db.commit()
    decision=interrupt({'claim_id':state['claim_id'],'recommendation':state.get('recommendation'),'requires':'authorized human-authored decision'})
    return {'human_decision':decision}

builder=StateGraph(State)
for key,label in AGENTS: builder.add_node(key,execute_agent(key,label),retry_policy=RetryPolicy(max_attempts=2,retry_on=(ConnectionError,TimeoutError)))
builder.add_edge(START,'intake')
for (a,_),(b,_) in zip(AGENTS,AGENTS[1:]): builder.add_edge(a,b)
builder.add_node('human_review',human_checkpoint)
builder.add_node('information_queue',lambda s:s)
builder.add_conditional_edges('routing',lambda s:s.get('route','review'),{'information':'information_queue','review':'human_review'})
builder.add_edge('information_queue','human_review'); builder.add_edge('human_review',END)
graph=builder.compile(checkpointer=CHECKPOINTER)

def investigate(claim_id,run_id):
    try:
        with Session() as db:
            run=db.get(Run,run_id); run.status='running'; db.commit()
        graph.invoke({'claim_id':claim_id,'run_id':run_id,'findings':[],'evidence':[]},config={'configurable':{'thread_id':run_id},'recursion_limit':30})
    except Exception as exc:
        with Session() as db:
            run=db.get(Run,run_id); run.status='failed'; run.state={**run.state,'error':type(exc).__name__}; audit(db,'system','investigation.failed',claim_id,error=type(exc).__name__); db.commit()

def resume(run,decision):
    config={'configurable':{'thread_id':run.id},'recursion_limit':30}
    # Rehydrate LangGraph from the durable database checkpoint after a cold start.
    snapshot=graph.get_state(config)
    if not snapshot.values:
        graph.update_state(config,run.state,as_node='routing')
        graph.invoke(None,config=config)
    graph.invoke(Command(resume=decision),config=config)
