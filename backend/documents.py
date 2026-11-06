import io, re
from fastapi import HTTPException

MAX_SIZE=10*1024*1024
def extract(name: str, data: bytes):
    if not data or len(data)>MAX_SIZE: raise HTTPException(400,'Upload a nonempty document smaller than 10 MB')
    ext=name.lower().rsplit('.',1)[-1]
    try:
        if ext=='pdf':
            if not data.startswith(b'%PDF'): raise ValueError('Invalid PDF signature')
            import fitz
            doc=fitz.open(stream=data,filetype='pdf')
            if len(doc)>100: raise ValueError('Maximum 100 pages per document')
            pages=[]
            for i,page in enumerate(doc):
                text=page.get_text()
                if not text.strip():
                    from PIL import Image
                    import pytesseract
                    pix=page.get_pixmap(matrix=fitz.Matrix(1.5,1.5))
                    text=pytesseract.image_to_string(Image.open(io.BytesIO(pix.tobytes('png'))))
                pages.append({'page':i+1,'text':text})
            return pages
        if ext=='docx':
            import zipfile
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if sum(x.file_size for x in z.infolist())>30*1024*1024: raise ValueError('Expanded document too large')
            from docx import Document
            d=Document(io.BytesIO(data))
            return [{'page':1,'text':'\n'.join([p.text for p in d.paragraphs]+[' | '.join(c.text for c in r.cells) for t in d.tables for r in t.rows]),'pagination':'DOCX logical page; original pagination unavailable'}]
        if ext in ('png','jpg','jpeg'):
            from PIL import Image
            import pytesseract
            im=Image.open(io.BytesIO(data)); im.verify()
            im=Image.open(io.BytesIO(data))
            if im.width*im.height>20_000_000: raise ValueError('Image exceeds 20 megapixels')
            return [{'page':1,'text':pytesseract.image_to_string(im)}]
        if ext=='txt': return [{'page':1,'text':data.decode('utf-8')}]
        raise HTTPException(400,'Supported formats: PDF, DOCX, PNG, JPG and TXT')
    except HTTPException: raise
    except Exception as exc: raise HTTPException(422,f'Document extraction failed. For scanned documents install Tesseract OCR. {type(exc).__name__}')

def structured(pages):
    text='\n'.join(p['text'] for p in pages)
    return {'diagnosis_codes':sorted(set(re.findall(r'\b[A-TV-Z]\d{2}(?:\.[A-Z0-9]{1,4})?\b',text))), 'procedure_codes':sorted(set(re.findall(r'\b(?:\d{5}|[A-Z]\d{4})\b',text))), 'dates':re.findall(r'\b\d{4}-\d{2}-\d{2}\b',text), 'amounts':re.findall(r'\$\s*[\d,]+(?:\.\d{2})?',text),'unreadable':not text.strip(),'method':'Pattern extraction; fields not present are left absent'}
