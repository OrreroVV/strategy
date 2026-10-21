import json
import numpy as np
import pandas as pd
import pytest
import yaml
from index_forecast.cli import sample, execute
from index_forecast.data import load_csv, sha256, DataError, features, asof_value
from index_forecast.config import load_config
from index_forecast.targets import build_targets
from index_forecast.backtest import training_rows, run_backtest


@pytest.fixture
def local_sample(tmp_path):
    csv = sample(tmp_path, 123)
    return csv, csv.parent/'manifest.json'


def test_import_synthetic_guard_hash_and_mapping(local_sample):
    csv, manifest = local_sample
    with pytest.raises(DataError,match='blocked'):
        load_csv(csv,manifest)
    frame,q,m = load_csv(csv,manifest,True)
    assert len(frame) == 1104
    assert q['data_kind'] == 'synthetic'
    assert m['sha256'] == sha256(csv)
    frame.rename(columns={'total_return_index':'TR'}).to_csv(csv,index=False)
    with pytest.raises(DataError,match='SHA-256'):
        load_csv(csv,manifest,True)
    m['sha256'] = sha256(csv)
    manifest.write_text(json.dumps(m),encoding='utf-8')
    remapped,_,_ = load_csv(csv,manifest,True,{'TR':'total_return_index'})
    assert 'total_return_index' in remapped


@pytest.mark.parametrize('field,value', [('currency','CNY'), ('return_type','price_return'),
    ('dividends_reinvested',False), ('point_in_time_verified',False), ('retrieved_at','bad')])
def test_manifest_contract(local_sample,field,value):
    csv,manifest = local_sample
    m = json.loads(manifest.read_text())
    m[field] = value
    manifest.write_text(json.dumps(m))
    with pytest.raises(DataError): load_csv(csv,manifest,True)


def test_mixed_real_synthetic_rejected(local_sample):
    csv,manifest = local_sample
    m = json.loads(manifest.read_text())
    m['data_kind'] = 'real'
    manifest.write_text(json.dumps(m))
    with pytest.raises(DataError,match='mislabeled'): load_csv(csv,manifest,True)


def test_no_overwrite_sample(local_sample):
    csv,_ = local_sample
    original = sha256(csv)
    with pytest.raises(ValueError,match='overwrite'): sample(csv.parent.parent.parent,123)
    assert sha256(csv) == original


def test_missing_csv_no_fallback(tmp_path):
    with pytest.raises(DataError,match='no synthetic fallback'):
        load_csv(tmp_path/'missing.csv',tmp_path/'missing.json',True)


def test_label_columns_never_features(panel):
    p = panel.copy()
    p['y'] = 999
    p['forward_pe'] = 10000
    pd.testing.assert_frame_equal(features(panel),features(p))


def test_optional_targets_remain_missing(panel):
    out = build_targets(panel.drop(columns=['cpi','trailing_pe']),[36])
    assert out.y_real.isna().all() and out.delta_log_pe.isna().all()
    assert out.y.notna().any()


def test_boundary_maturity_and_rolling(panel):
    ds = features(panel).merge(build_targets(panel,[36]),on=['date','index_id'])
    cutoff = pd.Timestamp('2000-01-31')
    train = training_rows(ds,cutoff,0,120)
    assert (train.label_end < cutoff).all()
    assert (train.date >= pd.Timestamp('1990-01-31')).all()
    assert not (train.label_end == cutoff).any()


def test_asof_missing_timestamp_is_error():
    rows = pd.DataFrame(dict(observation_date=['2000-01-01'],release_date=[None],vintage_date=['2000-02-01'],value=[1]))
    with pytest.raises(DataError): asof_value(rows,'2001-01-01')


def test_complete_offline_pipeline(tmp_path):
    (tmp_path/'config').mkdir()
    sample(tmp_path,42)
    cfg = dict(project=dict(name='SYNTHETIC_TEST_ONLY',seed=42),
        data=dict(csv='data/sample/SYNTHETIC_TEST_ONLY.csv',manifest='data/sample/manifest.json',allow_synthetic=True),
        targets=dict(horizons=[36,120]),validation=dict(min_train=30,step_months=60,embargo_months=1,
        window_months=None,holdout_start='2000-01-31'),models=dict(names=['historical_mean','ols','ridge','elastic_net'],
        ridge_alpha=10.,elastic_alpha=.01,elastic_l1_ratio=.5),reporting=dict(output_dir='outputs/runs'))
    config_path = tmp_path/'config'/'sample.yaml'
    config_path.write_text(yaml.safe_dump(cfg))
    out = execute('backtest',config_path)
    report = (out/'report.md').read_text(encoding='utf-8')
    assert 'SYNTHETIC_TEST_ONLY' in report and '未生成' in report
    assert (out/'source_snapshot.zip').is_file()
    meta = json.loads((out/'run_metadata.json').read_text(encoding='utf-8'))
    assert meta['status'] == 'backtest_completed'
    forecasts = pd.read_csv(out/'forecasts.csv')
    assert set(forecasts.data_kind) == {'synthetic'}
    assert (pd.to_datetime(forecasts.max_training_label_end) < pd.to_datetime(forecasts.forecast_date)).all()
    cfg['data']['allow_synthetic'] = False
    config_path.write_text(yaml.safe_dump(cfg))
    with pytest.raises(DataError,match='blocked'): execute('backtest',config_path)
    assert len(list((tmp_path/'outputs'/'runs').glob('*/failure.md'))) == 1


def test_config_rejects_random_or_invalid_models(tmp_path):
    config_path = tmp_path/'config.yaml'
    real = __import__('pathlib').Path(__file__).resolve().parents[1]/'config'/'synthetic.yaml'
    cfg = yaml.safe_load(real.read_text())
    cfg['models']['names'] = ['random_forest']
    config_path.write_text(yaml.safe_dump(cfg))
    with pytest.raises(ValueError): load_config(config_path)
