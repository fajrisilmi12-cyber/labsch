import sys, ast, os
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))

def test_windows_launch_fails_closed_off_windows(tmp_path):
    import windows_launch
    with pytest.raises(OSError, match='Windows'):
        windows_launch.launch_user_file(tmp_path/'a.pdf')

def test_main_import_has_no_unconditional_fcntl():
    tree=ast.parse((Path(__file__).resolve().parents[1]/'agent/labsch_agent.py').read_text())
    assert not any(isinstance(n,ast.Import) and any(a.name=='fcntl' for a in n.names) for n in tree.body)

def test_main_integrates_background_poll():
    s=(Path(__file__).resolve().parents[1]/'agent/labsch_agent.py').read_text()
    assert 'DownloadDispatcher(CONFIG_DIR, client)' in s
    assert 'downloads.poll()' in s
