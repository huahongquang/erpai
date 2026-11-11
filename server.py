import asyncio, json, os, sqlite3, uuid, secrets
from urllib.parse import parse_qs
from datetime import datetime, timezone
from pathlib import Path
import httpx
from readonly_gateway import reconcile as replica_reconcile, fetch as replica_fetch
from db_connector import reconcile_db, fetch_db
from sqlserver_connector import reconcile as reconcile_sqlserver, fetch as fetch_sqlserver
from fastapi import FastAPI, HTTPException, Header, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE=Path(__file__).resolve().parent
DB_DEFAULT = str(Path('/tmp') / 'erp.sqlite3') if os.getenv('VERCEL') else str(BASE / 'data' / 'erp.sqlite3')
DB=Path(os.getenv('DATABASE_PATH', DB_DEFAULT))
DB.parent.mkdir(parents=True,exist_ok=True)

TOKEN=os.getenv('ADMIN_TOKEN','')
if len(TOKEN)<24:
    if os.getenv('VERCEL') or not TOKEN:
        TOKEN='agentspace_demo_admin_token_secret_12345'
    else:
        raise RuntimeError('ADMIN_TOKEN must be at least 24 characters')

app=FastAPI(title='AgentSpace ERP API',docs_url=None,redoc_url=None)

# ASGI Middleware to restore original route path from Vercel rewrite query parameter
class VercelPathMiddleware:
    def __init__(self, app):
        self.app = app
    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            qs = parse_qs(scope.get("query_string", b"").decode("latin-1"))
            if "__path__" in qs and qs["__path__"]:
                sub = qs["__path__"][0].strip("/")
                if sub == "ws":
                    scope["path"] = "/ws"
                else:
                    scope["path"] = "/api/" + sub
        await self.app(scope, receive, send)

app.add_middleware(VercelPathMiddleware)

if (BASE/'static').is_dir():
    app.mount('/static',StaticFiles(directory=BASE/'static'),name='static')

subscribers=set()
lock=asyncio.Lock()
SOURCE=os.getenv('ERP_SOURCE','replica')
if SOURCE not in ('replica','database','sqlserver'): raise RuntimeError('ERP_SOURCE must be replica, database or sqlserver')
def fetch(domain,limit=100): return fetch_sqlserver(domain,limit) if SOURCE=='sqlserver' else (fetch_db(domain,limit) if SOURCE=='database' else replica_fetch(domain,limit))
def reconcile(): return reconcile_sqlserver() if SOURCE=='sqlserver' else (reconcile_db() if SOURCE=='database' else replica_reconcile())
ROLES=[('manager','Điều phối ERP'),('finance','Tài chính - kế toán'),('assets','Quản trị tài sản'),('hr','Nhân sự'),('security','An toàn thông tin'),('audit','Kiểm soát nội bộ')]

def now(): return datetime.now(timezone.utc).isoformat()
def db():
 c=sqlite3.connect(DB);c.row_factory=sqlite3.Row;return c

def setup():
 with db() as c:
  c.executescript('''CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,title TEXT NOT NULL,request TEXT NOT NULL,department TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,result TEXT DEFAULT '');
  CREATE TABLE IF NOT EXISTS steps(id TEXT PRIMARY KEY,job_id TEXT NOT NULL,agent TEXT NOT NULL,status TEXT NOT NULL,output TEXT DEFAULT '',created_at TEXT NOT NULL,FOREIGN KEY(job_id) REFERENCES jobs(id));
  CREATE TABLE IF NOT EXISTS approvals(id TEXT PRIMARY KEY,job_id TEXT NOT NULL,action TEXT NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,decided_at TEXT DEFAULT '',FOREIGN KEY(job_id) REFERENCES jobs(id));
  CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT NOT NULL,kind TEXT NOT NULL,detail TEXT NOT NULL,created_at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS erp_records(id TEXT PRIMARY KEY,kind TEXT NOT NULL,title TEXT NOT NULL,amount REAL NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL);''')
  if c.execute('SELECT COUNT(*) FROM erp_records').fetchone()[0]==0:
   c.executemany('INSERT INTO erp_records VALUES(?,?,?,?,?,?)',[(str(uuid.uuid4()),k,t,a,'pending',now()) for k,t,a in [('expense','Thanh toán vật tư phòng thí nghiệm',18500000),('asset','Mua máy tính phòng đào tạo',45000000),('expense','Chi phí bảo trì thiết bị',6800000)]])
setup()

def auth(authorization):
 if not authorization or not secrets.compare_digest(authorization,'Bearer '+TOKEN):raise HTTPException(401,'Unauthorized')

def rows(sql,args=()):
 with db() as c:return [dict(x) for x in c.execute(sql,args).fetchall()]

async def broadcast(data):
 for ws in list(subscribers):
  try: await ws.send_json(data)
  except Exception: subscribers.discard(ws)

async def event(job,kind,detail):
 with db() as c:c.execute('INSERT INTO events(job_id,kind,detail,created_at) VALUES(?,?,?,?)',(job,kind,detail,now()))
 await broadcast({'type':'event','job_id':job,'kind':kind,'detail':detail,'at':now()})

def status(job,value,result=None):
 with db() as c:
  if result is None:c.execute('UPDATE jobs SET status=?,updated_at=? WHERE id=?',(value,now(),job))
  else:c.execute('UPDATE jobs SET status=?,result=?,updated_at=? WHERE id=?',(value,result,now(),job))

async def llm(agent,request,context):
 if SOURCE=='sqlserver' and os.getenv('ALLOW_ERP_DATA_TO_LLM','false').lower()!='true':
  raise RuntimeError('External AI processing of ERP data disabled; set ALLOW_ERP_DATA_TO_LLM=true only after data protection review')
 key=os.getenv('OPENAI_API_KEY')
 if not key:raise RuntimeError('OPENAI_API_KEY is not configured; task cannot execute')
 prompt=f'Bạn là agent {agent} trong hệ thống ERP đại học. Chỉ phân tích thông tin cung cấp, không khẳng định đã cập nhật ERP thật. Phân biệt dữ liệu mẫu và dữ liệu thực. Viết tiếng Việt, ngắn gọn, có đề xuất và rủi ro.'
 async with httpx.AsyncClient(timeout=75) as client:
  response=await client.post('https://api.openai.com/v1/chat/completions',headers={'Authorization':'Bearer '+key},json={'model':os.getenv('OPENAI_MODEL','gpt-4.1-mini'),'messages':[{'role':'system','content':prompt},{'role':'user','content':json.dumps({'request':request,'context':context},ensure_ascii=False)[:18000]}]})
  response.raise_for_status()
  return response.json()['choices'][0]['message']['content']

async def process(job):
 async with lock:
  jobrow=rows('SELECT * FROM jobs WHERE id=?',(job,))[0]
  status(job,'running');await event(job,'workflow','Bắt đầu xử lý')
  try:
   context={'source':SOURCE,'reconciliation':reconcile(),'assets':fetch('assets',50),'finance':fetch('finance',50)}
  except Exception as ex:
   status(job,'failed');await event(job,'error',f'Không có dữ liệu ERP chỉ đọc hợp lệ: {str(ex)[:120]}');return
  for agent,label in ROLES:
   step=str(uuid.uuid4())
   with db() as c:c.execute('INSERT INTO steps(id,job_id,agent,status,created_at) VALUES(?,?,?,?,?)',(step,job,agent,'running',now()))
   await event(job,'agent',f'{label}: đang thực hiện')
   try: output=await llm(label,jobrow['request'],context)
   except Exception as ex:
    with db() as c:c.execute('UPDATE steps SET status=?,output=? WHERE id=?',('failed',str(ex)[:500],step))
    status(job,'failed');await event(job,'error',f'{label}: {str(ex)[:180]}');return
   with db() as c:c.execute('UPDATE steps SET status=?,output=? WHERE id=?',('done',output,step))
   context[agent]=output[:5000]
   await event(job,'agent',f'{label}: hoàn thành')
  payload=json.dumps({'kind':jobrow['department'],'title':jobrow['title'],'summary':context['audit'][:1200]},ensure_ascii=False)
  with db() as c:c.execute('INSERT INTO approvals VALUES(?,?,?,?,?,?,?)',(str(uuid.uuid4()),job,'review_reconciliation_only',payload,'pending',now(),''))
  status(job,'awaiting_approval',context['audit'])
  await event(job,'approval','Chờ duyệt báo cáo đối chiếu; không ghi dữ liệu ERP')

class JobIn(BaseModel):
 title:str=Field(min_length=3,max_length=160)
 request:str=Field(min_length=10,max_length=4000)
 department:str=Field(default='expense',pattern='^(expense|asset|hr)$')
class Decision(BaseModel):
 approve:bool
 reason:str=Field(default='Đã xem xét và quyết định',min_length=3,max_length=1000)

@app.get('/')
@app.get('/index')
async def home():
    idx = BASE / 'static' / 'index.html'
    if idx.is_file():
        return FileResponse(idx)
    return RedirectResponse(url='/static/index.html')

@app.get('/erp/readonly/{domain}')
@app.get('/api/erp/readonly/{domain}')
async def erp_read(domain:str,authorization:str|None=Header(None)):
 auth(authorization)
 try: return {'source':SOURCE,'rows':fetch(domain)}
 except (ValueError,RuntimeError,sqlite3.Error) as ex:raise HTTPException(422,str(ex))

@app.get('/erp/reconcile')
@app.get('/api/erp/reconcile')
async def erp_reconcile(authorization:str|None=Header(None)):
 auth(authorization)
 try:return reconcile()
 except (ValueError,RuntimeError,sqlite3.Error) as ex:raise HTTPException(422,str(ex))

@app.get('/snapshot')
@app.get('/api/snapshot')
async def snapshot(authorization:str|None=Header(None)):
 auth(authorization)
 return {'jobs':rows('SELECT * FROM jobs ORDER BY created_at DESC LIMIT 50'),'steps':rows('SELECT * FROM steps ORDER BY created_at DESC LIMIT 150'),'approvals':rows('SELECT * FROM approvals ORDER BY created_at DESC LIMIT 100'),'events':rows('SELECT * FROM events ORDER BY id DESC LIMIT 100'),'records':rows('SELECT * FROM erp_records ORDER BY created_at DESC LIMIT 100'),'agents':ROLES}

@app.post('/jobs',status_code=201)
@app.post('/api/jobs',status_code=201)
async def create_job(body:JobIn,authorization:str|None=Header(None)):
 auth(authorization);jid=str(uuid.uuid4())
 with db() as c:c.execute('INSERT INTO jobs(id,title,request,department,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(jid,body.title,body.request,body.department,'queued',now(),now()))
 await event(jid,'workflow','Đã tiếp nhận công việc')
 if os.getenv('VERCEL') or os.getenv('SYNC_PROCESS', '').lower() == 'true':
  await process(jid)
 else:
  asyncio.create_task(process(jid))
 return {'id':jid,'status':'queued' if not os.getenv('VERCEL') else 'processed'}

@app.post('/approvals/{approval_id}')
@app.post('/api/approvals/{approval_id}')
async def decide(approval_id:str,body:Decision,authorization:str|None=Header(None)):
 approval_token=os.getenv('APPROVER_TOKEN', TOKEN)
 if len(approval_token)<24 or not authorization or not secrets.compare_digest(authorization,'Bearer '+approval_token):raise HTTPException(403,'Separate approver credential required')
 with db() as c:
  a=c.execute('SELECT * FROM approvals WHERE id=?',(approval_id,)).fetchone()
  if not a:raise HTTPException(404,'Approval not found')
  if a['status']!='pending':raise HTTPException(409,'Already decided')
  new='approved' if body.approve else 'rejected'
  c.execute('UPDATE approvals SET status=?,decided_at=? WHERE id=?',(new,now(),approval_id))
  c.execute('UPDATE jobs SET status=?,updated_at=? WHERE id=?',('completed' if body.approve else 'rejected',now(),a['job_id']))
 reason_text = body.reason if body.reason else ('Phê duyệt' if body.approve else 'Từ chối')
 await event(a['job_id'],'approval',('Đã duyệt báo cáo; không ghi ERP' if body.approve else 'Đã từ chối')+'; lý do: '+reason_text[:200])
 return {'status':new,'erp_write':False}

@app.websocket('/ws')
@app.websocket('/api/ws')
async def ws(websocket:WebSocket):
 token=websocket.query_params.get('token','')
 if not secrets.compare_digest(token,TOKEN):await websocket.close(code=1008);return
 await websocket.accept();subscribers.add(websocket)
 try:
  while True:await websocket.receive_text()
 except WebSocketDisconnect:pass
 finally:subscribers.discard(websocket)
