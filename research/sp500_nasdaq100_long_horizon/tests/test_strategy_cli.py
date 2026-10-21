import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
import yaml
from PIL import Image
from index_forecast.cli import execute,sample
from index_forecast.config import load_config


def settings(tmp_path):
    root=Path(__file__).resolve().parents[1]
    c=yaml.safe_load((root/'config/p1_strategy_synthetic.yaml').read_text(encoding='utf-8'))
    c['targets']['horizons']=[36]
    c['validation']['step_months']=60
    c['portfolio'].update(end='2011-12-31',cost_bps=[0,5],tilt_limits=[.05],signal_horizon_months=36)
    c['plots']['horizon_months']=36
    (tmp_path/'config').mkdir()
    path=tmp_path/'config'/'strategy.yaml';path.write_text(yaml.safe_dump(c))
    return c,path


def test_strategy_bundle_money_and_chart_sources(tmp_path):
    _,path=settings(tmp_path);sample(tmp_path,42)
    out=execute('backtest',path)
    ledger=pd.read_csv(out/'strategy_ledger.csv');metrics=pd.read_csv(out/'strategy_metrics.csv')
    assert len(metrics)==20 and len(ledger)==20*24
    assert set(ledger.data_kind)=={'synthetic'}
    np.testing.assert_allclose(ledger.nav,ledger.nav_before_flow+ledger.external_flow-ledger.trading_cost,rtol=1e-12,atol=1e-8)
    assert ledger.signal_active.sum()==0
    assert metrics.sharpe.isna().all()
    for (funding,cost),g in ledger.groupby(['funding_kind','cost_bps']):
        a=g[g.strategy=='strategic_new_money'].sort_values('date')
        b=g[g.strategy=='limited_tilt_new_money'].sort_values('date')
        np.testing.assert_allclose(a.nav,b.nav)
    charts=json.loads((out/'chart_manifest.json').read_text(encoding='utf-8'))
    rendered=[x for x in charts['figures'] if x['status']=='rendered']
    assert len(rendered)==8
    for chart in rendered:
        source=pd.read_csv(out/chart['source_csv'])
        assert len(source)==chart['rows'] and set(source.data_kind)=={'synthetic'}
        with Image.open(out/chart['path']) as image:
            assert image.width>500 and image.height>300
    assert 'SYNTHETIC_TEST_ONLY' in (out/'strategy_report.md').read_text(encoding='utf-8')
    assert '未实施策略回测' not in (out/'report.md').read_text(encoding='utf-8')


def test_strategy_cannot_silently_run_without_interval_module(tmp_path):
    c,path=settings(tmp_path);c['extensions']['enabled']=False
    path.write_text(yaml.safe_dump(c))
    with pytest.raises(ValueError,match='requires relative and extensions'):load_config(path)
