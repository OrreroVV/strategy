import numpy as np
import pandas as pd
import pytest
from index_forecast.point_in_time import prepare_nominal_dataset
from index_forecast.models.relative import run_relative_backtest, evaluate_relative


def validation():
    return dict(min_train=30,step_months=24,embargo_months=1,window_months=None,holdout_start='2000-01-31')


def test_relative_paths_same_cohort_and_units(panel,model_config):
    ds=prepare_nominal_dataset(panel,[36,120],'synthetic')
    forecasts,audits,coverage=run_relative_backtest(ds,validation(),model_config)
    assert set(forecasts.prediction_path)=={'direct','indirect'}
    assert (forecasts.groupby(['forecast_date','horizon_months','model_name']).size()==2).all()
    assert (pd.to_datetime(forecasts.max_training_label_available_at,utc=True)<pd.to_datetime(forecasts.decision_at,utc=True)).all()
    direct=forecasts[forecasts.prediction_path=='direct']
    assert direct.predicted_cagr_difference.isna().all()
    indirect=forecasts[forecasts.prediction_path=='indirect']
    np.testing.assert_allclose(indirect.predicted_cagr_difference,
        np.expm1(indirect.predicted_ndx_log_return)-np.expm1(indirect.predicted_spx_log_return))
    assert set(forecasts.target_unit)=={'annualized_log_return_difference'}
    metrics,comparison=evaluate_relative(forecasts)
    assert set(metrics.prediction_path)=={'direct','indirect'}
    assert len(comparison)*2==len(forecasts)
    assert not coverage.empty and audits


def test_relative_future_mutation_preserves_predictions(panel,model_config):
    cutoff=pd.Timestamp('2000-01-31')
    altered=panel.copy()
    altered.loc[(altered.date>cutoff)&(altered.index_id=='NDX'),'total_return_index']*=2
    outs=[]
    for p in [panel,altered]:
        ds=prepare_nominal_dataset(p,[36],'synthetic')
        f,_,_=run_relative_backtest(ds,validation(),model_config)
        outs.append(f[f.forecast_date<=cutoff][['forecast_date','model_name','prediction_path','predicted_log_annual_return']])
    pd.testing.assert_frame_equal(*outs)


def test_relative_missing_side_reported_not_silently_joined(panel,model_config):
    p=panel[~((panel.index_id=='NDX')&(panel.date==pd.Timestamp('2000-01-31')))]
    ds=prepare_nominal_dataset(p,[36],'synthetic')
    f,_,coverage=run_relative_backtest(ds,validation(),model_config)
    assert not (f.forecast_date==pd.Timestamp('2000-01-31')).any()
    row=coverage[coverage.forecast_date==pd.Timestamp('2000-01-31')].iloc[0]
    assert row.status=='skipped' and 'missing' in row.reason


def test_relative_insufficient_history(panel,model_config):
    cfg=validation()|{'min_train':10000}
    f,a,c=run_relative_backtest(prepare_nominal_dataset(panel,[120],'synthetic'),cfg,model_config)
    assert f.empty and not a and not c.empty
    metrics,comparison=evaluate_relative(f)
    assert metrics.empty and comparison.empty


def test_evaluation_rejects_unpaired_path(panel,model_config):
    ds=prepare_nominal_dataset(panel,[36],'synthetic')
    f,_,_=run_relative_backtest(ds,validation(),model_config)
    with pytest.raises(ValueError,match='paired'):
        evaluate_relative(f.iloc[1:])


def test_pairing_duplicate_key_rejected(panel,model_config):
    ds=prepare_nominal_dataset(panel,[36],'synthetic')
    with pytest.raises(ValueError,match='Duplicate'):
        run_relative_backtest(pd.concat([ds,ds.iloc[:1]]),validation(),model_config)
