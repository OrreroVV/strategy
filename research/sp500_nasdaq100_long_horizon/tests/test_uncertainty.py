import numpy as np
import pandas as pd
import pytest
from index_forecast.uncertainty import calibrate_intervals, interval_metrics, mature_history


def predictions(n=200):
    dates=pd.date_range('1980-01-31',periods=n,freq='ME')
    ends=(dates.to_period('M')+1).to_timestamp('M')
    return pd.DataFrame(dict(forecast_date=dates,decision_at=pd.to_datetime(dates,utc=True)+pd.Timedelta(hours=23),
        label_end=ends,label_available_at=pd.to_datetime(ends,utc=True)+pd.Timedelta(hours=23),
        index_id='SPX',target_id='nominal_log_return',target_unit='annualized_log_return',horizon_months=1,
        model_name='ridge',prediction_path='absolute',selection_version='fixed_test_v1',data_kind='synthetic',output_type='historical_oos',
        predicted_log_annual_return=.04,actual_log_annual_return=.04+.01*np.sin(np.arange(n))))


def settings():
    return dict(min_residuals_80=60,min_disjoint_80=5,min_residuals_95=120,min_disjoint_95=10)


def test_intervals_use_only_mature_residuals():
    p=predictions()
    out,audit=calibrate_intervals(p,settings())
    assert out.iloc[20].interval_status_80=='insufficient_history'
    assert out.iloc[-1].interval_status_95=='available'
    assert out.iloc[-1].lower_80_log<.04<out.iloc[-1].upper_80_log
    assert out.iloc[-1].lower_80_cagr==pytest.approx(np.expm1(out.iloc[-1].lower_80_log))
    cutoff=p.decision_at.iloc[100]
    altered=p.copy()
    altered.loc[altered.label_available_at>=cutoff,'actual_log_annual_return']=999.
    other,_=calibrate_intervals(altered,settings())
    cols=['lower_80_log','upper_80_log','lower_95_log','upper_95_log']
    pd.testing.assert_frame_equal(out.loc[out.decision_at<=cutoff,cols],other.loc[other.decision_at<=cutoff,cols])
    assert all(row['max_label_available_at'] is None or pd.Timestamp(row['max_label_available_at'])<pd.Timestamp(row['decision_at']) for row in audit)
    m=interval_metrics(out)
    assert m.n_intervals_80.iloc[0]>0 and 0<=m.coverage_80.iloc[0]<=1


def test_relative_interval_units_and_delayed_labels():
    p=predictions()
    p['target_id']='relative_log_return'
    p['target_unit']='annualized_log_return_difference'
    p['prediction_path']='indirect'
    out,_=calibrate_intervals(p,settings())
    assert out.lower_80_cagr.isna().all()
    assert out.lower_80_relative_wealth_cagr.notna().any()
    p['label_available_at']=pd.Timestamp('2100-01-01',tz='UTC')
    out,_=calibrate_intervals(p,settings())
    assert out.lower_80_log.isna().all()


def test_no_mixed_kinds_or_duplicate_prediction_keys():
    p=predictions()
    with pytest.raises(ValueError):calibrate_intervals(pd.concat([p,p.iloc[:1]]),settings())
    p.loc[0,'data_kind']='real'
    with pytest.raises(ValueError):calibrate_intervals(p,settings())


def test_overflow_is_missing_transformed_value_not_infinite_interval():
    p=predictions();p['actual_log_annual_return']=999
    out,_=calibrate_intervals(p,settings())
    row=out.iloc[-1]
    assert np.isfinite(row.upper_80_log)
    assert pd.isna(row.upper_80_cagr)
    assert row.interval_transform_status_80=='numeric_overflow'
