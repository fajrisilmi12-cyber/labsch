import sys, io, hashlib, json
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))
import downloader as d

def test_interrupted_launch_never_reexecutes(tmp_path):
    d.claim_task(tmp_path,'abc',None); d.mark_download_done(tmp_path,'abc','a'*64,3); d.claim_execution(tmp_path,'abc')
    reports=[]
    class C:
        def report_download_result(self,r): reports.append(r); return True
    def fail(*a): raise AssertionError('must never execute')
    runner=d.DownloadDispatcher(tmp_path,C(),worker=fail,jitter=lambda:0)
    runner.submit([{'task_id':'abc'}]); runner.wait(2)
    assert reports[0]['execution_state']=='failed_launch'
    assert 'unknown' in reports[0]['error']

def test_truncated_content_is_not_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(d,'resolve_url',lambda x:x); monkeypatch.setattr(d,'RETRY_BACKOFF',0)
    class R(io.BytesIO):
        status=200; headers={'Content-Length':'200','Content-Type':'application/pdf'}
    class O:
        def open(self,*a,**kw):return R(b'short')
    r=d.download_task(tmp_path,dict(task_id='abc',max_size_mb=1,url='https://example.org/x',filename='x.pdf',autorun=False),O())
    assert r['download_state']=='failed'
    assert not list(tmp_path.rglob('x.pdf'))

def test_each_task_has_isolated_destination(tmp_path, monkeypatch):
    monkeypatch.setattr(d,'resolve_url',lambda x:x)
    class R(io.BytesIO):
        status=200; headers={'Content-Length':'1'}
    class O:
        def open(self,*a,**k): return R(b'x')
    for tid in ['aaa','bbb']:
        d.download_task(tmp_path,dict(task_id=tid,max_size_mb=1,url='https://example.org/a',filename='same.txt',autorun=False),O())
    assert len(list(tmp_path.rglob('same.txt')))==2

def test_html_rejected_without_install(tmp_path, monkeypatch):
    monkeypatch.setattr(d,'resolve_url',lambda x:x); monkeypatch.setattr(d,'RETRY_BACKOFF',0)
    class R(io.BytesIO):
        status=200; headers={'Content-Type':'text/html'}
    class O:
        def open(self,*a,**kw):return R(b'<html>login</html>')
    r=d.download_task(tmp_path,dict(task_id='html',max_size_mb=1,url='https://example.org/x',filename='x.pdf',autorun=False),O())
    assert r['download_state']=='failed' and 'HTML' in r['error']
    assert not list(tmp_path.rglob('x.pdf'))

def test_connection_dns_rebinding_rejected(monkeypatch):
    monkeypatch.setattr(d.socket,'getaddrinfo',lambda *a,**kw:[(2,1,6,'',('127.0.0.1',443))])
    with pytest.raises(d.UnsafeUrlError):
        d.build_download_opener().open('https://example.org/x',timeout=1)
