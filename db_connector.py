"""Vendor-neutral, SELECT-only connector; requires externally enforced read-only DB credentials.
Only administrator-supplied view names and fixed columns are queried. No user SQL.
"""
import os, re, json
from decimal import Decimal
from sqlalchemy import create_engine, MetaData, Table, select, column, literal_column
from sqlalchemy.engine import URL

COLUMNS={"assets":("asset_id","name","department","original_cost","book_value"),"finance":("entry_id","asset_id","amount","account","description")}
IDENT=re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

def identifier(name):
    if not isinstance(name,str) or not IDENT.fullmatch(name): raise ValueError("Invalid SQL identifier")
    return name

def config():
    cfg=json.loads(os.environ.get('ERP_VIEW_MAPPING','{}'))
    for domain in COLUMNS:
        if domain not in cfg: raise RuntimeError('Missing ERP_VIEW_MAPPING for '+domain)
        obj=cfg[domain]
        identifier(obj['view'])
        for logical in COLUMNS[domain]: identifier(obj['columns'][logical])
    return cfg

def fetch_db(domain,limit=200,offset=0):
    if domain not in COLUMNS: raise ValueError('Unsupported domain')
    limit=int(limit);offset=int(offset)
    if not (1<=limit<=500 and 0<=offset<=1000000):raise ValueError('Invalid pagination')
    url=os.getenv('ERP_DATABASE_URL','')
    if not url:raise RuntimeError('ERP_DATABASE_URL missing')
    cfg=config()[domain]
    fields=', '.join(identifier(cfg['columns'][col])+' AS '+col for col in COLUMNS[domain])
    view=identifier(cfg['view'])
    # Only fixed administrator-configured views; read-only role must be enforced at DB server.
    engine=create_engine(url,pool_pre_ping=True,pool_size=2,max_overflow=0,connect_args={})
    try:
        with engine.connect() as conn:
            t=Table(view,MetaData(),*[column(identifier(cfg['columns'][c])) for c in COLUMNS[domain]])
            selected=[t.c[identifier(cfg['columns'][c])].label(c) for c in COLUMNS[domain]]
            sql=select(*selected).select_from(t).order_by(t.c[identifier(cfg['columns'][COLUMNS[domain][0]])]).limit(limit).offset(offset)
            result=conn.execute(sql).mappings().all()
            return [{k:(float(v) if isinstance(v,Decimal) else v) for k,v in row.items()} for row in result]
    finally:engine.dispose()

def reconcile_db(max_rows=10000):
    # Fail closed on truncation, no false 'complete' reconciliation.
    assets=[];finance=[]
    for domain,out in [('assets',assets),('finance',finance)]:
        for offset in range(0,max_rows+1,500):
            page=fetch_db(domain,500,offset)
            if offset==max_rows and page: raise RuntimeError('Row limit exceeded; reconciliation aborted')
            out.extend(page)
            if len(page)<500:break
    from decimal import Decimal,InvalidOperation
    counts={};issues=[]
    for a in assets:
        k=str(a['asset_id']);counts[k]=counts.get(k,0)+1
        try:
            orig=Decimal(str(a['original_cost']));book=Decimal(str(a['book_value']))
            if orig<0 or book<0 or book>orig:issues.append({'rule':'INVALID_BOOK_VALUE','asset_id':k})
        except (InvalidOperation,TypeError):issues.append({'rule':'INVALID_AMOUNT','asset_id':k})
    for k,n in counts.items():
        if n>1:issues.append({'rule':'DUPLICATE_ASSET_ID','asset_id':k,'count':n})
    for f in finance:
        if f['asset_id'] is not None and str(f['asset_id']) not in counts:
            issues.append({'rule':'ORPHAN_FINANCE_ASSET','entry_id':str(f['entry_id']),'asset_id':str(f['asset_id'])})
    return {'asset_count':len(assets),'finance_count':len(finance),'exceptions':issues,'partial':False,'source':'external_database_readonly','note':'Financial entry amount is not assumed equal to asset original cost; accounting mapping requires validation.'}
