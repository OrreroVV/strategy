import numpy as np
import pandas as pd
from index_forecast.backtest import run_backtest, evaluate
from index_forecast.data import features
from index_forecast.targets import build_targets


def test_models_oos_audit_and_reproducibility(panel, model_config):
    ds = features(panel).merge(build_targets(panel, [36,120]), on=['date','index_id'])
    cfg = dict(min_train=30, step_months=24, embargo_months=0, window_months=None,
               holdout_start='2000-01-31')
    a, audit, skips = run_backtest(ds, cfg, model_config)
    b, _, _ = run_backtest(ds, cfg, model_config)
    pd.testing.assert_frame_equal(a,b)
    assert set(a.model_name) == set(model_config['names'])
    assert (pd.to_datetime(a.max_training_label_end) < pd.to_datetime(a.forecast_date)).all()
    assert set(a.output_type) == {'historical_oos'}
    np.testing.assert_allclose(a.predicted_cagr, np.expm1(a.predicted_log_annual_return))
    metrics = evaluate(a)
    assert (metrics[metrics.model_name == 'historical_mean'].oos_r2.abs() < 1e-10).all()


def test_future_mutation_preserves_past_predictions(panel, model_config):
    cutoff = pd.Timestamp('2000-01-31')
    altered = panel.copy()
    altered.loc[altered.date > cutoff,'total_return_index'] *= 2
    cfg = dict(min_train=30, step_months=24, embargo_months=0, window_months=None,
               holdout_start='1990-01-31')
    outs = []
    for p in [panel,altered]:
        ds = features(p).merge(build_targets(p,[36]),on=['date','index_id'])
        out,_,_ = run_backtest(ds,cfg,model_config)
        outs.append(out[out.forecast_date <= cutoff][['forecast_date','index_id','model_name','predicted_log_annual_return']])
    pd.testing.assert_frame_equal(*outs)


def test_insufficient_labels_are_explicit(panel, model_config):
    ds = features(panel).merge(build_targets(panel,[120]),on=['date','index_id'])
    cfg = dict(min_train=10000,step_months=12,embargo_months=0,window_months=None,holdout_start='2000-01-31')
    forecasts,audits,skips = run_backtest(ds,cfg,model_config)
    assert forecasts.empty and not audits
    assert 'forecast_date' in forecasts.columns
    assert not skips.empty
    assert set(skips.reason) == {'insufficient_matured_training_labels'}
    assert 'oos_r2' in evaluate(forecasts).columns
