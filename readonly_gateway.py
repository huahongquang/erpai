"""Safe read-only integration gateway. Never accepts SQL from agents."""
import csv, io, os, sqlite3
from pathlib import Path

ALLOWED = {'assets': {'asset_id','name','department','original_cost','book_value'}, 'finance': {'entry_id','asset_id','amount','account','description'}}

def connect():
    path = Path(os.environ.get('ERP_READONLY_DB','/app/data/erp_readonly.sqlite3'))
    if not path.is_file():
        raise RuntimeError('ERP_READONLY_DB missing: import verified ERP exports first')
    return sqlite3.connect(f'file:{path}?mode=ro',uri=True)

def fetch(domain,limit=100):
    if domain not in ALLOWED: raise ValueError('unsupported domain')
    limit=max(1,min(int(limit),500))
    cols=','.join(sorted(ALLOWED[domain]))
    with connect() as c:
        c.row_factory=sqlite3.Row
        return [dict(x) for x in c.execute(f'SELECT {cols} FROM {domain} LIMIT ?', (limit,))]

def reconcile():
    assets=fetch('assets',500); finance=fetch('finance',500)
    ids={str(a['asset_id']) for a in assets}
    exceptions=[{'rule':'ORPHAN_FINANCE_ASSET','entry_id':f['entry_id'],'asset_id':f['asset_id']} for f in finance if f['asset_id'] and str(f['asset_id']) not in ids]
    duplicates=[]; seen=set()
    for a in assets:
        k=str(a['asset_id'])
        if k in seen:duplicates.append({'rule':'DUPLICATE_ASSET_ID','asset_id':k})
        seen.add(k)
        if a['book_value'] is not None and a['original_cost'] is not None and (a['book_value']<0 or a['book_value']>a['original_cost']):
            exceptions.append({'rule':'INVALID_BOOK_VALUE','asset_id':k})
    return {'asset_count':len(assets),'finance_count':len(finance),'exceptions':exceptions+duplicates,'partial':len(assets)==500 or len(finance)==500}

def import_csv(db_path,asset_csv,finance_csv):
    """Offline importer: run only on trusted, reviewed exports. Writes local replica, never ERP."""
    def read(path,cols):
        with open(path,encoding='utf-8-sig',newline='') as f:
            r=csv.DictReader(f)
            if set(r.fieldnames or [])!=cols:raise ValueError(f'CSV columns must be {sorted(cols)}')
            return list(r)
    a=read(asset_csv,ALLOWED['assets']); f=read(finance_csv,ALLOWED['finance'])
    p=Path(db_path);p.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(p) as c:
        c.executescript('DROP TABLE IF EXISTS assets; DROP TABLE IF EXISTS finance; CREATE TABLE assets(asset_id TEXT,name TEXT,department TEXT,original_cost REAL,book_value REAL); CREATE TABLE finance(entry_id TEXT,asset_id TEXT,amount REAL,account TEXT,description TEXT);')
        c.executemany('INSERT INTO assets VALUES(?,?,?,?,?)',[(x['asset_id'],x['name'],x['department'],float(x['original_cost']),float(x['book_value'])) for x in a])
        c.executemany('INSERT INTO finance VALUES(?,?,?,?,?)',[(x['entry_id'],x['asset_id'],float(x['amount']),x['account'],x['description']) for x in f])
    return len(a),len(f)

if __name__=='__main__':
    import sys
    if len(sys.argv)!=5:raise SystemExit('Usage: python readonly_gateway.py replica.db assets.csv finance.csv import')
    print(import_csv(sys.argv[1],sys.argv[2],sys.argv[3]))
