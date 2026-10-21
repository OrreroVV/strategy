import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def panel():
    dates = pd.date_range('1980-01-31', periods=480, freq='ME')
    blocks = []
    for j, drift in [('SPX', .005), ('NDX', .007)]:
        r = drift + .02 * np.sin(np.arange(len(dates)) / 9)
        blocks.append(pd.DataFrame(dict(date=dates, index_id=j,
            total_return_index=100*np.exp(np.cumsum(r)), cpi=100*np.exp(np.arange(480)*.002),
            trailing_pe=20+np.sin(np.arange(480)/12), source='SYNTHETIC_TEST_ONLY',
            source_series_id=j, unit='index_points', quality_flag='SYNTHETIC_TEST_ONLY')))
    return pd.concat(blocks, ignore_index=True)


@pytest.fixture
def model_config():
    return dict(names=['historical_mean', 'ols', 'ridge', 'elastic_net'],
                ridge_alpha=10., elastic_alpha=.01, elastic_l1_ratio=.5)
