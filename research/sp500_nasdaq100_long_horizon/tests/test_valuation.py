import numpy as np
import pandas as pd
import pytest
from index_forecast.models.valuation import valuation_forecast


def history():
    dates=pd.date_range('1980-01-31',periods=181,freq='ME')
    return pd.DataFrame(dict(date=dates,trailing_pe=20+np.arange(len(dates))*.01,
        eps_ttm=10*np.exp(np.arange(len(dates))*.005),dividend_yield=.02,
        pe_available_at=pd.to_datetime(dates,utc=True)+pd.Timedelta(hours=20),
        eps_available_at=pd.to_datetime(dates,utc=True)+pd.Timedelta(hours=20),
        dividend_available_at=pd.to_datetime(dates,utc=True)+pd.Timedelta(hours=20),
        pe_definition_id='SYNTHETIC_TTM_PE',eps_definition_id='SYNTHETIC_TTM_EPS'))


def test_valuation_components_and_no_future_reference():
    p=history();date=p.date.iloc[150];decision=pd.Timestamp(date,tz='UTC')+pd.Timedelta(hours=23)
    result=valuation_forecast(p,decision,60,lambda_value=.5)
    assert result['status']=='available'
    assert result['eps_growth_log']==pytest.approx(.06)
    assert result['dividend_log']==pytest.approx(np.log1p(.02))
    assert result['predicted_log_annual_return']==pytest.approx(result['dividend_log']+result['eps_growth_log']+result['valuation_log'])
    changed=p.copy();changed.loc[changed.date>date,'trailing_pe']=9999
    assert valuation_forecast(changed,decision,60,lambda_value=.5)==result


def test_missing_fields_and_nonpositive_eps_explicit():
    p=history()
    assert valuation_forecast(p.drop(columns='eps_ttm'),'1995-01-31T23:00:00Z',36)['status']=='missing_fields'
    p.loc[150,'eps_ttm']=-1
    assert valuation_forecast(p,'1995-01-31T23:00:00Z',36)['status']=='invalid_eps'


def test_definition_change_or_late_feature_not_silently_used():
    p=history();p.loc[100,'pe_definition_id']='OTHER'
    assert valuation_forecast(p,'1995-01-31T23:00:00Z',36)['status']=='definition_change'
    p=history();p['pe_available_at']=pd.Timestamp('2100-01-01',tz='UTC')
    assert valuation_forecast(p,'1995-01-31T23:00:00Z',36)['status']=='insufficient_pe_history'
