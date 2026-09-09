from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agent'))

def test_upgrade_preserves_config_and_requires_it(tmp_path):
    import upgrade
    with pytest.raises(ValueError): upgrade.validate_existing_config(tmp_path/'config.ini')
    p=tmp_path/'config.ini'; original=b'{"server_url":"https://example.org","api_token":"local-secret","client_id":"existing"}'
    p.write_bytes(original)
    assert upgrade.validate_existing_config(p)['client_id']=='existing'
    assert p.read_bytes()==original

def test_installer_manual_admin_only():
    p=Path(__file__).resolve().parents[1]/'agent/upgrade.bat'
    assert p.exists()
    s=p.read_text().lower()
    assert 'net session' in s and 'run as administrator' in s
    assert '-verb runas' not in s and 'mshta' not in s
