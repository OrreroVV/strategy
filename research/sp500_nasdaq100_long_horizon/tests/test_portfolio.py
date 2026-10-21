import numpy as np
import pandas as pd
import pytest
from index_forecast.portfolio import xirr,simulate_portfolio,signal_target


def prices(flat=False):
    dates=pd.date_range('2001-01-31',periods=3,freq='ME')
    return pd.DataFrame(dict(date=dates,SPX=[100,100,100] if flat else [100,110,121],
                             NDX=[100,100,100] if flat else [100,110,121]))


def signals():
    return pd.DataFrame([dict(signal_id='SYNTHETIC_TEST_ONLY',forecast_date='2001-01-31',
        decision_at='2001-01-31T23:59:59Z',direct_prediction=.04,indirect_prediction=.03,
        lower_80_log=.01,upper_80_log=.06,evidence_grade='B',paths_conflict=False)])


def test_xirr_unique_zero_and_ambiguous_patterns():
    assert xirr(pd.DataFrame(dict(date=['2001-01-01','2002-01-01'],amount=[-100,110])))['rate']==pytest.approx(.1)
    assert xirr(pd.DataFrame(dict(date=['2001-01-01','2002-01-01'],amount=[-100,100])))['rate']==pytest.approx(0,abs=1e-10)
    assert xirr(pd.DataFrame(dict(date=['2001-01-01','2002-01-01'],amount=[100,110])))['status']=='no_sign_change'
    result=xirr(pd.DataFrame(dict(date=['2001-01-01','2002-01-01','2003-01-01'],amount=[-100,230,-132])))
    assert result['status']=='potential_multiple_roots' and np.isnan(result['rate'])


def test_dca_external_flows_do_not_create_twr_returns():
    ledger,flows,metrics=simulate_portfolio(prices(True),None,'strategic_new_money',
        initial_capital=0,monthly_contribution=100,cost_bps=0)
    assert ledger.nav.iloc[-1]==pytest.approx(300)
    assert metrics['twr_total_return']==pytest.approx(0)
    assert metrics['xirr']==pytest.approx(0,abs=1e-10)
    assert metrics['total_contributions']==300
    assert metrics['sharpe'] is None


def test_fees_and_positions_conserve_money():
    ledger,flows,metrics=simulate_portfolio(prices(True),None,'fixed_50_50_annual',
        initial_capital=100,monthly_contribution=100,cost_bps=50)
    np.testing.assert_allclose(ledger.nav,ledger.nav_before_flow+ledger.external_flow-ledger.trading_cost,rtol=1e-12)
    np.testing.assert_allclose(ledger.nav,ledger.spx_value+ledger.ndx_value+ledger.cash,rtol=1e-12)
    np.testing.assert_allclose(ledger.spx_value,ledger.spx_price*ledger.spx_units,rtol=1e-12)
    np.testing.assert_allclose(ledger.ndx_value,ledger.ndx_price*ledger.ndx_units,rtol=1e-12)
    assert (ledger.cash>=-1e-9).all() and (ledger.spx_units>=0).all() and (ledger.ndx_units>=0).all()
    assert ledger.nav.iloc[-1]==pytest.approx(metrics['total_contributions']-metrics['total_cost'])


def test_holding_market_return_and_no_monthly_deposits():
    ledger,_,m=simulate_portfolio(prices(),None,'spx_hold',initial_capital=100,monthly_contribution=0,cost_bps=0)
    assert ledger.nav.iloc[-1]==pytest.approx(121)
    assert m['twr_total_return']==pytest.approx(.21)
    assert ledger.trade_notional.iloc[1:].sum()==0


def test_signal_cannot_trade_on_its_own_close_and_low_evidence_blocks():
    s=signals()
    assert signal_target(s,'2001-01-31T23:59:59Z',.5,.05,3)['target_ndx']==.5
    assert signal_target(s,'2001-02-28T23:59:59Z',.5,.05,3)['target_ndx']==.55
    bad=s.copy();bad['evidence_grade']='D'
    assert signal_target(bad,'2001-02-28T23:59:59Z',.5,.05,3)['target_ndx']==.5
    ledger,_,_=simulate_portfolio(prices(),s,'limited_tilt_new_money',initial_capital=0,
        monthly_contribution=100,cost_bps=0,review_months=list(range(1,13)))
    assert ledger.target_ndx.iloc[0]==.5 and ledger.target_ndx.iloc[1]==.55
    assert ledger.signal_active.iloc[0]==False


def test_expired_or_conflicting_signals_not_used():
    s=signals()
    assert signal_target(s,'2002-01-31T23:59:59Z',.5,.05,3)['target_ndx']==.5
    s['paths_conflict']=True
    assert signal_target(s,'2001-02-28T23:59:59Z',.5,.05,3)['target_ndx']==.5


def test_realized_labels_and_missing_price_month_rejected():
    s=signals();s['actual_log_annual_return']=999
    with pytest.raises(ValueError,match='signal'):simulate_portfolio(prices(),s,'limited_tilt_new_money')
    with pytest.raises(ValueError,match='calendar'):simulate_portfolio(prices().iloc[[0,2]],None,'spx_hold')


def test_future_prices_do_not_change_past_trades():
    p=prices();a,_,_=simulate_portfolio(p,None,'fixed_50_50_annual')
    p.loc[2,'NDX']=9999
    b,_,_=simulate_portfolio(p,None,'fixed_50_50_annual')
    pd.testing.assert_frame_equal(a.iloc[:2],b.iloc[:2])


def test_drawdown_recovery_and_continuous_new_highs():
    _,_,up=simulate_portfolio(prices(),None,'spx_hold',cost_bps=0)
    assert up['longest_recovery_days_completed']==0 and up['max_drawdown']==0
    p=prices();p['SPX']=[100,80,100]
    _,_,recovered=simulate_portfolio(p,None,'spx_hold',cost_bps=0)
    assert recovered['max_drawdown']==pytest.approx(-.2)
    assert recovered['longest_recovery_days_completed']==59 and not recovered['unrecovered_at_end']
    p['SPX']=[100,80,70]
    _,_,down=simulate_portfolio(p,None,'spx_hold',cost_bps=0)
    assert down['unrecovered_at_end'] and down['longest_recovery_days_completed']==0
