import numpy as np
import pandas as pd
import pytest
from index_forecast.targets import build_targets


@pytest.mark.parametrize('h', [36, 60, 84, 120])
def test_formula(panel, h):
    out = build_targets(panel, [h])
    a = out[(out.index_id == 'SPX') & (out.horizon_months == h)].iloc[0]
    p = panel[panel.index_id == 'SPX'].reset_index(drop=True)
    y = 12/h*np.log(p.total_return_index.iloc[h]/p.total_return_index.iloc[0])
    assert a.y == pytest.approx(y)
    assert a.cagr == pytest.approx(np.expm1(y))
    assert a.y_real == pytest.approx(y-.024)
    assert a.delta_log_pe == pytest.approx(np.log(p.trailing_pe.iloc[h]/p.trailing_pe.iloc[0]))
    assert a.y_relative == pytest.approx(.024)
    assert out[out.date == out.date.max()].y.isna().all()


def test_missing_calendar_month_does_not_shift_horizon(panel):
    missing = panel[panel.date != pd.Timestamp('1983-01-31')]
    out = build_targets(missing, [36])
    assert out[out.date == pd.Timestamp('1980-01-31')].y.isna().all()
