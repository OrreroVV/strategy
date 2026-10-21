import json
import hashlib
import numpy as np
from pathlib import Path
import pandas as pd
import pytest
import yaml
from index_forecast.cli import execute,sample
from index_forecast.config import load_config


def config(tmp_path):
    root=Path(__file__).resolve().parents[1]
    c=yaml.safe_load((root/'config/p1_extensions_synthetic.yaml').read_text(encoding='utf-8'))
    c['targets']['horizons']=[36]
    c['validation']['step_months']=60
    (tmp_path/'config').mkdir()
    path=tmp_path/'config'/'test.yaml'
    path.write_text(yaml.safe_dump(c),encoding='utf-8')
    return c,path


def test_extensions_end_to_end_missing_valuation_and_intervals(tmp_path):
    _,path=config(tmp_path);sample(tmp_path,42)
    out=execute('backtest',path)
    f=pd.read_csv(out/'ensemble_forecasts.csv')
    assert set(f.model_name)=={'ensemble_equal','ensemble_weighted','ensemble_shrink'}
    assert set(f.data_kind)=={'synthetic'}
    assert f.predicted_log_annual_return.notna().all()
    intervals=pd.read_csv(out/'prediction_intervals.csv')
    assert intervals.lower_80_log.isna().all()
    assert set(intervals.interval_status_80)=={'insufficient_history'}
    val=pd.read_csv(out/'valuation_forecasts.csv')
    assert val.empty
    diag=pd.read_csv(out/'valuation_diagnostics.csv')
    assert 'missing_fields' in set(diag.status)
    meta=json.loads((out/'run_metadata.json').read_text(encoding='utf-8'))
    assert meta['status']=='backtest_completed'
    assert meta['extensions_status']=='completed_with_explicit_availability_statuses'
    assert 'SYNTHETIC_TEST_ONLY' in (out/'extensions_report.md').read_text(encoding='utf-8')
    audit=json.loads((out/'ensemble_audit.json').read_text(encoding='utf-8'))
    for row in audit:
        assert abs(sum(row['weights'].values())-1)<1e-12
        assert row['max_weight_label_available_at'] is None or pd.Timestamp(row['max_weight_label_available_at'])<pd.Timestamp(row['decision_at'])


def test_final_audit_mode_cannot_use_online_selection(tmp_path):
    c,path=config(tmp_path)
    c['extensions']['phase']='final_audit'
    path.write_text(yaml.safe_dump(c))
    with pytest.raises(ValueError,match='final audit'):load_config(path)


def test_complete_synthetic_valuation_path(tmp_path):
    _,path=config(tmp_path);csv=sample(tmp_path,42)
    p=pd.read_csv(csv)
    months=pd.to_datetime(p.date).dt.to_period('M')
    month_index=months.map(lambda x:x.ordinal-months.min().ordinal)
    p['eps_ttm']=10*np.exp(month_index*.004)
    p['dividend_yield']=.02
    p['pe_definition_id']='SYNTHETIC_TTM_PE'
    p['eps_definition_id']='SYNTHETIC_TTM_EPS'
    for col in ['pe_available_at','eps_available_at','dividend_available_at']:
        p[col]=p.date+'T20:00:00Z'
    p.to_csv(csv,index=False)
    manifest_path=csv.parent/'manifest.json'
    manifest=json.loads(manifest_path.read_text())
    manifest['sha256']=hashlib.sha256(csv.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    out=execute('backtest',path)
    values=pd.read_csv(out/'valuation_forecasts.csv')
    assert not values.empty
    assert set(values.data_kind)=={'synthetic'}
    np.testing.assert_allclose(values.eps_growth_log,.048)
    np.testing.assert_allclose(values.valuation_log,0.)
    np.testing.assert_allclose(values.predicted_log_annual_return,np.log1p(.02)+.048)
