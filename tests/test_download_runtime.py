import sys, io, hashlib, threading, time, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'agent'))
import downloader as d

def test_containment_not_substring(tmp_path):
    p = tmp_path / 'evil' / 'Users/Public/Desktop/a.pdf'
    p.parent.mkdir(parents=True); p.write_bytes(b'x')
    assert d.evaluate_launch(tmp_path, {'sha256': hashlib.sha256(b'x').hexdigest()}, p)['execution_state'] != 'launchable'

def test_reserved_windows_names():
    for s in ['CON.txt', 'nul', 'LPT1.pdf', 'a. ', 'a:evil.exe']:
        assert d.sanitize_filename(s) != s

def test_malformed_url_is_rejected():
    for s in ['https://[invalid/x', 'https://example.com:bad/x', 'https://example.com\\evil/x']:
        assert d.validate_source_url(s) is None

def test_corrupt_registry_fails_closed(tmp_path):
    (tmp_path / 'downloads.json').write_text('{broken')
    import pytest
    with pytest.raises(ValueError): d._load_registry(tmp_path)

def test_task_download_html_and_launch_failure_are_terminal(tmp_path, monkeypatch):
    monkeypatch.setattr(d, 'resolve_url', lambda x:x)
    monkeypatch.setattr(d, 'RETRY_BACKOFF', 0)
    class Response(io.BytesIO):
        status=200
        headers={'Content-Type':'application/pdf', 'Content-Length':'3'}
    class Opener:
        calls=0
        def open(self,*a,**k):
            self.calls+=1; return Response(b'pdf')
    import windows_launch
    def fail(p): raise OSError('no active session')
    monkeypatch.setattr(windows_launch,'launch_user_file', fail)
    t=dict(task_id='abc',max_size_mb=1,url='https://example.org/a',filename='a.pdf',sha256=hashlib.sha256(b'pdf').hexdigest())
    op=Opener(); r=d.download_task(tmp_path,t,op)
    assert r['download_state']=='done' and r['execution_state']=='failed_launch'
    assert op.calls==1
    assert list(tmp_path.rglob('a.pdf'))
    assert not list(tmp_path.rglob('*.part'))

def test_dispatcher_bounded_nonblocking_and_replays(tmp_path):
    entered = threading.Event(); release = threading.Event(); calls=[]
    def work(root, task, opener):
        calls.append(task['task_id']); entered.set(); release.wait(3)
        return dict(task_id=task['task_id'], download_state='done', execution_state='not_requested')
    class Client:
        ok=False
        def report_download_result(self, result): return self.ok
    c=Client(); runner=d.DownloadDispatcher(tmp_path,c,worker=work,jitter=lambda:0)
    t={'task_id':'test-a'}
    assert runner.submit([t, t, {'task_id':'test-b'}]) == 1
    assert entered.wait(1)
    assert runner.submit([t]) == 0
    release.set(); runner.wait(3)
    assert calls == ['test-a']
    c.ok=True
    runner.submit([t]); runner.wait(3)
    assert calls == ['test-a']
    state=json.loads((tmp_path/'downloads.json').read_text())['test-a']
    assert state['reported'] is True
    runner.close()
