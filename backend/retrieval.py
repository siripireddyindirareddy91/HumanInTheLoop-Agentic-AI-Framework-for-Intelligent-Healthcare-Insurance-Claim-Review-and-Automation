import re, math
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy import select
from backend.database import Document, Chunk

def index_document(db,document):
    for page in document.pages:
        words=page['text'].split()
        for start in range(0,len(words),180):
            from uuid import uuid4
            db.add(Chunk(id=str(uuid4()),document_id=document.id,page=page['page'],text=' '.join(words[start:start+220])))

def search(db,query,limit=6):
    pairs=db.execute(select(Chunk,Document).join(Document,Chunk.document_id==Document.id).where(Document.active==True,Document.claim_id==None)).all()
    if not pairs or not query.strip(): return []
    texts=[c.text for c,d in pairs]
    # BM25 + character TF-IDF: local lexical hybrid, not neural semantic embeddings.
    tokenize=lambda s:re.findall(r'\w+',s.lower())
    tokens=[tokenize(t) for t in texts]; q=tokenize(query); avg=sum(map(len,tokens))/len(tokens)
    bm=[]
    for ts in tokens:
        score=0
        for term in q:
            freq=ts.count(term); df=sum(term in t for t in tokens)
            idf=math.log(1+(len(tokens)-df+.5)/(df+.5))
            score+=idf*freq*2.5/(freq+1.5*(.25+.75*len(ts)/max(avg,1))) if freq else 0
        bm.append(score)
    vector=TfidfVectorizer(analyzer='char_wb',ngram_range=(3,5)); matrix=vector.fit_transform(texts+[query]); cos=cosine_similarity(matrix[-1],matrix[:-1]).ravel()
    scores=.65*np.array(bm)/max(max(bm),1)+.35*cos
    result=[]
    for i in np.argsort(scores)[::-1][:limit]:
        if scores[i]<.03: continue
        c,d=pairs[i]
        result.append({'chunk_id':c.id,'document_id':d.id,'document':d.name,'version':d.version,'page':c.page,'text':c.text,'score':round(float(scores[i]),3),'uploaded_at':d.created_at,'section':d.category})
    return result
