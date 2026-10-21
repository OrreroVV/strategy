import hashlib
import json
from pathlib import Path
import pandas as pd
import pytest
import yaml
from index_forecast.cli import execute, sample
from index_forecast.config import load_config


def test_v2_end_to_end_and_ledger(tmp_path):
    root=Path(__file__).resolve().parents[1]
    cfg=yaml.safe_load((root/'config/p1_synthetic.yaml').read_text(encoding='utf-8'))
    cfg['targets']['horizons']=[36,120]
    cfg['validation'].update(step_months=60,min_train=30,embargo_months=1)
    (tmp_path/'config').mkdir()
    path=tmp_path/'config'/'p1.yaml'
    path.write_text(yaml.safe_dump(cfg),encoding='utf-8')
    sample(tmp_path,42)
    out=execute('backtest',path)
    f=pd.read_csv(out/'relative_forecasts.csv')
    entries=[json.loads(line) for line in (out/'prediction_ledger.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(entries)==len(f)>0
    assert {e['prediction_id'] for e in entries}==set(f.prediction_id)
    for entry in entries:
        assert not set(entry)&{'actual_log_annual_return','error','y','y_relative'}
        assert entry['data_kind']=='synthetic'
        assert len(entry['protocol_hash'])==64
    assert 'SYNTHETIC_TEST_ONLY' in (out/'relative_report.md').read_text(encoding='utf-8')
    protocol=json.loads((out/'relative_protocol.json').read_text(encoding='utf-8'))
    expected=protocol.pop('protocol_hash')
    assert hashlib.sha256(json.dumps(protocol,sort_keys=True,default=str).encode()).hexdigest()==expected
    coverage=pd.read_csv(out/'cohort_coverage.csv')
    assert set(coverage.status)=={'predicted','skipped'}
    assert set(coverage.data_kind)=={'synthetic'}


def test_v1_cannot_silently_enable_relative(tmp_path):
    root=Path(__file__).resolve().parents[1]
    cfg=yaml.safe_load((root/'config/p1_synthetic.yaml').read_text())
    cfg['schema_version']=1
    path=tmp_path/'bad.yaml'
    path.write_text(yaml.safe_dump(cfg))
    with pytest.raises(ValueError,match='schema_version'):load_config(path)
