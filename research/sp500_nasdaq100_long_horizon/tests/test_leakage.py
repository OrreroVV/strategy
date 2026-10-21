import numpy as np
import pandas as pd
import pytest
from index_forecast.data import features, asof_value
from index_forecast.backtest import training_rows, fit_predict
from index_forecast.targets import build_targets


def test_future_mutation_preserves_past_features(panel):
    cutoff = pd.Timestamp('2000-01-31')
    altered = panel.copy()
    altered.loc[altered.date > cutoff, 'total_return_index'] *= 10
    a, b = features(panel), features(altered)
    pd.testing.assert_frame_equal(a[a.date <= cutoff], b[b.date <= cutoff])


def test_asof_vintage_and_release():
    rows = pd.DataFrame({'observation_date':['2000-01-01']*3,
        'release_date':['2000-02-10', '2000-02-10', '2000-04-10'],
        'vintage_date':['2000-02-10','2000-03-10','2000-04-10'], 'value':[1., 99., 3.]})
    assert np.isnan(asof_value(rows, '2000-02-01'))
    assert asof_value(rows, '2000-02-28') == 1.
    assert asof_value(rows, '2000-03-31') == 99.


def test_purge_and_maturity(panel):
    ds = features(panel).merge(build_targets(panel, [36]), on=['date','index_id'])
    rows = training_rows(ds[ds.index_id == 'SPX'], pd.Timestamp('2000-01-31'), 2)
    assert (rows.label_end < pd.Timestamp('1999-11-30')).all()
    assert (rows.date < pd.Timestamp('1997-01-31')).all()


def test_preprocessing_fit_only_training(model_config):
    x = pd.DataFrame({'momentum_12m':[1., 2., 3.], 'vol_12m':[2., 3., 4.]})
    test = pd.DataFrame({'momentum_12m':[9999.], 'vol_12m':[9999.]})
    _, meta = fit_predict('ridge', x, np.array([.1,.2,.3]), test, model_config)
    assert meta['scaler_mean'] == [2., 3.]


def test_target_columns_rejected(model_config):
    with pytest.raises(ValueError, match='feature'):
        fit_predict('ols', pd.DataFrame({'y':[1.,2.]}), np.array([1.,2.]),
                    pd.DataFrame({'y':[3.]}), model_config)
