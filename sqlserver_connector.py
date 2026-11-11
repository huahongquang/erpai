"""Microsoft SQL Server read-only connector; server-side SELECT grants are mandatory."""
import os, re, json
from decimal import Decimal
from sqlalchemy import create_engine, MetaData, Table, Column, String, select, text
from sqlalchemy.engine import URL

IDENT=re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
FIELDS={"assets":("asset_id","name","department","original_cost","book_value"),"finance":("entry_id","asset_id","amount","account","description")}

def safe_identifier(v):
    if not isinstance(v,str) or not IDENT.fullmatch(v): raise ValueError("Invalid configured SQL identifier")
    return v

def mapping():
    m=json.loads(os.environ.get("ERP_VIEW_MAPPING","{}"))
    for domain, fields in FIELDS.items():
        cfg=m[domain]
        safe_identifier(cfg.get("schema","ai_read"));safe_identifier(cfg["view"])
        for f in fields:safe_identifier(cfg["columns"][f])
    return m

def engine():
    required=("ERP_SQL_HOST","ERP_SQL_DATABASE","ERP_SQL_USER","ERP_SQL_PASSWORD")
    if any(not os.getenv(x) for x in required):raise RuntimeError("Missing SQL Server connection configuration")
    driver=os.getenv("ERP_SQL_ODBC_DRIVER","ODBC Driver 18 for SQL Server")
    if driver!="ODBC Driver 18 for SQL Server":raise RuntimeError("Only ODBC Driver 18 is supported")
    url=URL.create("mssql+pyodbc",username=os.environ["ERP_SQL_USER"],password=os.environ["ERP_SQL_PASSWORD"],host=os.environ["ERP_SQL_HOST"],port=int(os.getenv("ERP_SQL_PORT","1433")),database=os.environ["ERP_SQL_DATABASE"],query={"driver":driver,"Encrypt":"yes","TrustServerCertificate":"no","Connection Timeout":"8","ApplicationIntent":"ReadOnly"})
    return create_engine(url,pool_pre_ping=True,pool_size=2,max_overflow=0,pool_timeout=10,connect_args={"timeout":15})

def fetch(domain,limit=200,offset=0):
    if domain not in FIELDS:raise ValueError("Unsupported domain")
    limit=int(limit);offset=int(offset)
    if not (1<=limit<=500 and 0<=offset<=1000000):raise ValueError("Invalid pagination")
    cfg=mapping()[domain]
    # Columns and table names are admin-controlled and strictly validated; no agent-supplied SQL.
    t=Table(cfg["view"],MetaData(),*[Column(cfg["columns"][k],String) for k in FIELDS[domain]],schema=cfg.get("schema","ai_read"))
    stmt=select(*(t.c[cfg["columns"][k]].label(k) for k in FIELDS[domain])).order_by(t.c[cfg["columns"][FIELDS[domain][0]]]).offset(offset).limit(limit)
    eng=engine()
    try:
        with eng.connect() as conn:
            conn.execute(text("SET LOCK_TIMEOUT 5000"))
            rows=conn.execute(stmt).mappings().all()
            return [{k:(str(v) if isinstance(v,Decimal) else v) for k,v in row.items()} for row in rows]
    finally:eng.dispose()

def reconcile(max_rows=10000):
    from decimal import Decimal,InvalidOperation
    data={}
    for domain in FIELDS:
        records=[]
        for offset in range(0,max_rows+1,500):
            page=fetch(domain,500,offset)
            if offset==max_rows and page:raise RuntimeError("Row cap exceeded; refusing partial reconciliation")
            records.extend(page)
            if len(page)<500:break
        data[domain]=records
    assets=data["assets"]; finance=data["finance"]; seen={};issues=[]
    for a in assets:
        aid=str(a["asset_id"] or "").strip()
        if not aid:issues.append({"rule":"MISSING_ASSET_ID"});continue
        seen[aid]=seen.get(aid,0)+1
        try:
            orig=Decimal(str(a["original_cost"]));book=Decimal(str(a["book_value"]))
            if not (orig.is_finite() and book.is_finite()) or orig<0 or book<0 or book>orig:issues.append({"rule":"INVALID_BOOK_VALUE","asset_id":aid})
        except (InvalidOperation,TypeError):issues.append({"rule":"INVALID_AMOUNT","asset_id":aid})
    for aid,n in seen.items():
        if n>1:issues.append({"rule":"DUPLICATE_ASSET_ID","asset_id":aid,"count":n})
    for f in finance:
        aid=str(f["asset_id"] or "").strip()
        if aid and aid not in seen:issues.append({"rule":"ORPHAN_FINANCE_ASSET","entry_id":str(f["entry_id"]),"asset_id":aid})
    return {"source":"sqlserver_readonly","asset_count":len(assets),"finance_count":len(finance),"exceptions":issues,"partial":False,"note":"No assertion that accounting amounts equal acquisition costs; requires approved mapping."}
