import pandas as pd
import pytest
from index_forecast.data import validate_panel, DataError


def test_valid_sorted(panel):
    out, quality = validate_panel(panel.sample(frac=1, random_state=4))
    assert out[out.index_id == 'SPX'].date.is_monotonic_increasing
    assert quality['rows'] == len(panel)


@pytest.mark.parametrize('kind', ['duplicate','unit','negative','date','missing','infinite'])
def test_invalid_data(panel, kind):
    p = panel.copy()
    if kind == 'duplicate': p = pd.concat([p,p.iloc[:1]])
    if kind == 'unit': p.loc[0,'unit'] = 'USD'
    if kind == 'negative': p.loc[0,'total_return_index'] = -1
    if kind == 'date': p.loc[0,'date'] = pd.NaT
    if kind == 'missing': p = p.drop(columns='source')
    if kind == 'infinite': p.loc[0,'total_return_index'] = float('inf')
    with pytest.raises(DataError): validate_panel(p)


def test_gaps_diagnosed_not_filled(panel):
    p = panel[panel.date != pd.Timestamp('1983-01-31')]
    out, q = validate_panel(p)
    assert len(out) == len(p)
    assert q['series']['SPX']['missing_months'] == 1
