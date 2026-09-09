"""Production synthetic-only API verification with exact-ID cleanup."""
import json, os, sys, uuid, urllib.request, urllib.error, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'agent'))
from config_sync import AgentClient
url=os.environ.get('SCHOOL_SERVER_URL','').rstrip('/')
token=os.environ.get('SCHOOL_API_TOKEN','')
if not url or not token:
    raise SystemExit('Set SCHOOL_SERVER_URL and SCHOOL_API_TOKEN before running this production check.')
cid='synthetic-download-'+uuid.uuid4().hex[:12]
tasks=[]; checks=[]
def api(path,body=None,method=None):
    req=urllib.request.Request(url+'/api/'+path,data=json.dumps(body).encode() if body is not None else None,method=method or ('POST' if body is not None else 'GET'),headers={'X-Agent-Token':token,'User-Agent':'labschctl/0.4.0','Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=20) as r:return r.status,json.load(r)
try:
    for p in ['health','admin/config','admin/profiles','admin/device','clients']:
        assert api(p)[0]==200; checks.append(p+':200')
    client=AgentClient(url,token,cid)
    hb=client.heartbeat('SYNTHETIC-DOWNLOAD', '127.0.0.1','synthetic','0.4.0-test1','dev-'+uuid.uuid4().hex[:16],'02:00:00:00:00:99',display_name='Synthetic Download',is_test=True)
    assert hb and 'disable_camera' in hb and 'disable_audio' in hb
    checks.append('synthetic heartbeat backward-compatible:200')
    status,created=api('admin/downloads',dict(url='https://example.org/test.txt',filename='test.txt',autorun=False,clients=[cid],ttl_seconds=60,max_size_mb=1))
    assert status==201; tid=created['task_id']; tasks.append(tid)
    pending=client.get_pending_downloads(); assert any(t['task_id']==tid for t in pending)
    assert api('downloads/pending?client_id='+cid)[1]['pending_downloads']==[]
    assert api('downloads/pending?client_id=synthetic-other&protocol=1&version=0.4.0')[1]['pending_downloads']==[]
    # Synthetic report only: no bytes downloaded and no file executed.
    result=dict(task_id=tid,download_state='done',execution_state='not_requested',bytes=0)
    assert client.report_download_result(result); assert client.report_download_result(result)
    assert client.get_pending_downloads()==[]
    row=next(t for t in api('admin/downloads')[1]['tasks'] if t['task_id']==tid)
    assert row['rollup']['done']==1 and row['expires_at']-row['created_at']==60
    assert row['clients'][0]['execution_state']=='not_requested'
    assert api('admin/downloads/'+tid+'/cancel',method='POST')[0]==200
    checks.append('create -> protocol/target gate -> AgentClient pending/report twice -> rollup/TTL -> cancel:PASS')
finally:
    ids=','.join("'"+t+"'" for t in tasks) or "''"
    sql=f"DELETE FROM download_status WHERE task_id IN ({ids}); DELETE FROM download_tasks WHERE task_id IN ({ids}); DELETE FROM events WHERE client_id='{cid}'; DELETE FROM clients WHERE client_id='{cid}'; SELECT COUNT(*) AS remaining FROM clients WHERE client_id='{cid}'; SELECT COUNT(*) AS remaining_tasks FROM download_tasks WHERE task_id IN ({ids});"
    r=subprocess.run([str(ROOT/'workers/node_modules/.bin/wrangler'),'d1','execute','labsch-db','--remote','--command',sql,'--json'],cwd=ROOT/'workers',capture_output=True,text=True,timeout=60)
    assert r.returncode==0,r.stderr
    cleanup=json.loads(r.stdout)
    assert cleanup[-1]['results'][0]['remaining_tasks']==0 and cleanup[-2]['results'][0]['remaining']==0
    checks.append('exact synthetic task/client/event cleanup verified:0 remaining')
print(json.dumps(dict(checks=checks,synthetic_client=cid,synthetic_tasks=tasks,real_pc_tasks_queued=False),indent=2))
