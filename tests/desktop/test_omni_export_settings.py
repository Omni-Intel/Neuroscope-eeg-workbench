from test_connection_settings import run_desktop


def test_optional_omni_profile_and_export_readiness(tmp_path):
    run_desktop(f'''
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QComboBox
from neuroscope_eeg.desktop.app import NeuroScopeWindow
from neuroscope_eeg.desktop.omni_profile import edit_profile
from neuroscope_eeg.core.models import SourceMetadata, ConnectionState
app=QApplication([])
w=NeuroScopeWindow(settings_path=Path({str(tmp_path/'connections.json')!r}))
w.source_select.setCurrentText('公司 OmniBCI')
w.omni_type.setCurrentText('stm32')
assert w._extra_device_form.isRowVisible(w.omni_profile_button)
def accept(dialog):
    dialog.findChild(QLineEdit).setText('实际参考位置待补充')
    dialog.findChild(QComboBox).setCurrentText('50 Hz')
    return QDialog.DialogCode.Accepted
with patch.object(QDialog, 'exec', accept):
    edit_profile(w)
p=json.loads(Path(w.profile_path.text()).read_text(encoding='utf-8'))
assert p['power_line_frequency']==50 and p['confirmed'] is False
meta=SourceMetadata('omnibci','omnibci',250,tuple(f'CH{{i+1}}' for i in range(32)),('eeg',)*32,('uV',)*32,
    {{'device_model':'stm32','sdk_version':'0.2.0','native_sdk_version':'0.2.0',
      'frontend_config':{{'verified':True,'gains':[24]*32}}}})
w.controller=SimpleNamespace(error=None,state=ConnectionState.RUNNING,samples_received=100,
    last_data_age_sec=lambda:0.1,source=SimpleNamespace(metadata=meta))
w._refresh_connection_state()
assert 'EDF 参数已从 SDK 准备' in w.connection_detail.text()
assert '参考接法' in w.connection_detail.text()
w.controller=None
w.source_select.setCurrentText('模拟')
assert not w._extra_device_form.isRowVisible(w.omni_profile_button)
w.close()
''')
