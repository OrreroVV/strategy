"""Monthly index-proxy book with explicit flows, delayed signals and internal fees."""
import hashlib
import json
import numpy as np
import pandas as pd
from scipy.optimize import brentq
from .point_in_time import utc_timestamp

SIGNAL_COLUMNS=['signal_id','forecast_date','decision_at','direct_prediction','indirect_prediction',
                'lower_80_log','upper_80_log','evidence_grade','paths_conflict']
STRATEGIES=('spx_hold','ndx_hold','fixed_50_50_annual','strategic_new_money','limited_tilt_new_money')


def xirr(cashflows):
    """Actual days/365. Conservative refusal when multiple sign changes permit multiple roots."""
    if not {'date','amount'}.issubset(cashflows):raise ValueError('Cashflow date/amount required')
    p=cashflows[['date','amount']].copy()
    p['date']=pd.to_datetime(p.date,utc=True,errors='raise').dt.normalize()
    p['amount']=pd.to_numeric(p.amount,errors='raise')
    if not np.isfinite(p.amount).all() or p.date.isna().any():raise ValueError('Invalid cashflow')
    p=p.groupby('date',as_index=False).amount.sum().sort_values('date')
    p=p[p.amount.abs()>1e-12]
    fail=lambda status:dict(status=status,rate=np.nan)
    if p.empty:return fail('no_cashflows')
    signs=np.sign(p.amount.to_numpy());changes=int(np.sum(signs[1:]!=signs[:-1]))
    if not changes:return fail('no_sign_change')
    if changes>1:return fail('potential_multiple_roots')
    if signs[0]>=0 or signs[-1]<=0:return fail('unsupported_cashflow_pattern')
    times=(p.date-p.date.min()).dt.total_seconds().to_numpy()/(365*24*3600)
    amounts=p.amount.to_numpy()
    def scaled_npv(z):
        exponent=-z*times
        return float(np.sum(amounts*np.exp(exponent-exponent.max())))
    lo,hi=-30.,30.
    if scaled_npv(lo)*scaled_npv(hi)>0:return fail('no_root_in_numeric_bracket')
    z=brentq(scaled_npv,lo,hi,xtol=1e-12)
    return dict(status='unique_root_single_sign_change',rate=float(np.expm1(z)))


def validate_signals(signals):
    if signals is None:return pd.DataFrame(columns=SIGNAL_COLUMNS)
    if set(signals)-set(SIGNAL_COLUMNS) or set(SIGNAL_COLUMNS)-set(signals):
        raise ValueError('Only registered signal columns accepted; realized labels/errors forbidden')
    p=signals.copy()
    if p.empty:return p
    p['decision_at']=pd.to_datetime([utc_timestamp(x,'signal decision_at') for x in p.decision_at],utc=True)
    p['forecast_date']=pd.to_datetime(p.forecast_date,utc=True)
    if p.signal_id.isna().any() or p.signal_id.duplicated().any() or p.decision_at.duplicated().any():raise ValueError('Duplicate/missing signal identity')
    if not p.forecast_date.dt.is_month_end.all() or not p.forecast_date.dt.normalize().eq(p.decision_at.dt.normalize()).all():
        raise ValueError('Signal date must match decision UTC month-end')
    if not p.evidence_grade.isin(['A','B','C','D']).all():raise ValueError('Invalid evidence grade')
    if not p.paths_conflict.map(lambda x:isinstance(x,(bool,np.bool_))).all():raise ValueError('Invalid signal conflict flag')
    for col in ['direct_prediction','indirect_prediction','lower_80_log','upper_80_log']:
        p[col]=pd.to_numeric(p[col],errors='raise')
        if np.isinf(p[col]).any():raise ValueError('Infinite signal')
    finite=p.lower_80_log.notna()&p.upper_80_log.notna()
    if (p.loc[finite,'lower_80_log']>p.loc[finite,'upper_80_log']).any():raise ValueError('Inverted signal interval')
    return p.sort_values('decision_at').reset_index(drop=True)


def signal_target(signals,execution_at,strategic_ndx=.5,max_tilt=.05,max_age_months=3):
    if not 0<=strategic_ndx<=1 or not 0<=max_tilt<=1 or type(max_age_months) is not int or max_age_months<1:
        raise ValueError('Invalid signal target parameters')
    p=validate_signals(signals)
    t=utc_timestamp(execution_at)
    neutral=dict(target_ndx=strategic_ndx,signal_active=False,signal_id=None,signal_decision_at=None,reason='no_prior_signal')
    if p.empty:return neutral
    past=p[p.decision_at<t]
    if past.empty:return neutral
    row=past.iloc[-1]
    neutral.update(signal_id=row.signal_id,signal_decision_at=row.decision_at)
    age=t.tz_localize(None).to_period('M').ordinal-row.decision_at.tz_localize(None).to_period('M').ordinal
    reasons=[]
    if age>max_age_months:reasons.append('stale_signal')
    if row.evidence_grade not in ['A','B']:reasons.append('insufficient_evidence')
    values=[row.direct_prediction,row.indirect_prediction,row.lower_80_log,row.upper_80_log]
    if not np.isfinite(values).all():reasons.append('missing_prediction_or_interval')
    if row.paths_conflict or np.sign(row.direct_prediction)!=np.sign(row.indirect_prediction):reasons.append('path_conflict')
    if np.isfinite([row.lower_80_log,row.upper_80_log]).all() and row.lower_80_log<=0<=row.upper_80_log:reasons.append('interval_crosses_zero')
    if reasons:return neutral|dict(reason=';'.join(reasons))
    direction=1 if row.lower_80_log>0 else -1
    if np.sign(row.direct_prediction)!=direction:return neutral|dict(reason='interval_point_direction_conflict')
    return neutral|dict(target_ndx=float(np.clip(strategic_ndx+direction*max_tilt,0,1)),signal_active=True,reason='eligible_tilt')


def signals_from_intervals(intervals,model_name,horizon_months):
    p=intervals[(intervals.target_id=='relative_log_return')&(intervals.model_name==model_name)&
                (intervals.horizon_months==horizon_months)]
    rows=[]
    for date,g in p.groupby('forecast_date',sort=True):
        if g.prediction_path.duplicated().any():raise ValueError('Duplicate signal path')
        if set(g.prediction_path)!={'direct','indirect'}:continue
        direct=g[g.prediction_path=='direct'].iloc[0];indirect=g[g.prediction_path=='indirect'].iloc[0]
        if pd.Timestamp(direct.decision_at)!=pd.Timestamp(indirect.decision_at):raise ValueError('Signal path decision mismatch')
        if not np.isfinite([direct.predicted_log_annual_return,indirect.predicted_log_annual_return]).all():continue
        grades=['A','B','C','D']
        grade=max([direct.evidence_grade,indirect.evidence_grade],key=lambda x:grades.index(x))
        identity=dict(date=str(date),decision=str(direct.decision_at),model=model_name,horizon=int(horizon_months))
        rows.append(dict(signal_id=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest(),
            forecast_date=date,decision_at=direct.decision_at,direct_prediction=float(direct.predicted_log_annual_return),
            indirect_prediction=float(indirect.predicted_log_annual_return),lower_80_log=direct.lower_80_log,
            upper_80_log=direct.upper_80_log,evidence_grade=grade,
            paths_conflict=bool(np.sign(direct.predicted_log_annual_return)!=np.sign(indirect.predicted_log_annual_return))))
    return validate_signals(pd.DataFrame(rows,columns=SIGNAL_COLUMNS))


def simulate_portfolio(prices,signals,strategy,initial_capital=10000.,monthly_contribution=0.,
                       cost_bps=5.,strategic_ndx=.5,max_tilt=.05,max_signal_age_months=3,
                       review_months=(1,4,7,10)):
    if strategy not in STRATEGIES:raise ValueError('Unknown strategy')
    if any(not np.isfinite(x) or x<0 for x in [initial_capital,monthly_contribution,cost_bps]) or cost_bps>=10000:
        raise ValueError('Invalid capital/contribution/cost')
    if initial_capital+monthly_contribution<=0 or not 0<=strategic_ndx<=1 or not 0<=max_tilt<=1:
        raise ValueError('Invalid funding/target weights')
    if type(max_signal_age_months) is not int or max_signal_age_months<1 or not review_months or any(type(x) is not int or not 1<=x<=12 for x in review_months):
        raise ValueError('Invalid signal review settings')
    p=prices.copy()
    if not {'date','SPX','NDX'}.issubset(p) or p.empty:raise ValueError('Paired prices required')
    p['date']=pd.to_datetime(p.date,utc=True).dt.tz_localize(None)
    p=p.sort_values('date').reset_index(drop=True)
    if p.date.duplicated().any() or not p.date.eq(p.date.dt.normalize()).all() or not p.date.dt.is_month_end.all() or list(p.date)!=list(pd.date_range(p.date.min(),p.date.max(),freq='ME')):
        raise ValueError('Complete unique calendar month-end prices required; no filling')
    if not np.isfinite(p[['SPX','NDX']].to_numpy(dtype=float)).all() or (p[['SPX','NDX']]<=0).any().any():raise ValueError('Positive finite prices required')
    signal_frame=validate_signals(signals)
    units=np.zeros(2);cash=0.;previous_nav=0.;unit_nav=1.;fee_rate=cost_bps/10000
    state=dict(target_ndx=strategic_ndx,signal_active=False,signal_id=None,signal_decision_at=None,reason='no_prior_signal')
    rows=[];cashflows=[]
    for position,row in enumerate(p.itertuples(index=False)):
        date=row.date;execution=pd.Timestamp(date,tz='UTC')+pd.Timedelta(hours=23,minutes=59,seconds=59)
        quote=np.array([row.SPX,row.NDX],dtype=float);asset_values=units*quote
        before=float(asset_values.sum()+cash)
        flow=float(monthly_contribution+(initial_capital if position==0 else 0))
        if flow:cashflows.append(dict(date=date,amount=-flow,kind='external_contribution'))
        cash+=flow;pretrade=before+flow
        if strategy=='spx_hold':target=0.;reason='fixed_spx';active=False;signal_id=None;signal_time=None
        elif strategy=='ndx_hold':target=1.;reason='fixed_ndx';active=False;signal_id=None;signal_time=None
        else:
            if strategy=='limited_tilt_new_money':
                if date.month in review_months:
                    state=signal_target(signal_frame,execution,strategic_ndx,max_tilt,max_signal_age_months)
                elif state['signal_decision_at'] is not None:
                    age=date.to_period('M').ordinal-pd.Timestamp(state['signal_decision_at']).tz_localize(None).to_period('M').ordinal
                    if age>max_signal_age_months:state=state|dict(target_ndx=strategic_ndx,signal_active=False,reason='stale_signal')
                target=state['target_ndx'];reason=state['reason'];active=state['signal_active'];signal_id=state['signal_id'];signal_time=state['signal_decision_at']
            else:target=.5 if strategy=='fixed_50_50_annual' else strategic_ndx;reason='strategic_rule';active=False;signal_id=None;signal_time=None
        weights=np.array([1-target,target])
        full_rebalance=strategy=='fixed_50_50_annual' and (position==0 or date.month==1)
        delta=np.zeros(2)
        if full_rebalance:
            def balance(net):return net+fee_rate*np.abs(weights*net-asset_values).sum()-pretrade
            net=pretrade if fee_rate==0 else brentq(balance,0,pretrade,xtol=1e-10)
            delta=weights*net-asset_values
        elif cash>0:
            budget=cash/(1+fee_rate)
            deficits=np.maximum(weights*pretrade-asset_values,0)
            allocation=deficits/deficits.sum() if deficits.sum()>0 else weights
            delta=budget*allocation
        notional=float(np.abs(delta).sum());fee=fee_rate*notional
        units+=delta/quote;cash-=float(delta.sum())+fee
        tolerance=1e-8*max(1,pretrade)
        if abs(cash)<tolerance:cash=0.
        nav=float(np.dot(units,quote)+cash)
        if cash < -tolerance or units.min() < -1e-10 or abs(nav-(pretrade-fee))>tolerance:
            raise ValueError('Portfolio money/position conservation failed')
        market_factor=before/previous_nav if previous_nav>0 else 1.
        cost_factor=nav/pretrade if pretrade>0 else 1.
        period_factor=market_factor*cost_factor;unit_nav*=period_factor
        rows.append(dict(date=date,execution_at=execution,strategy=strategy,nav_before_flow=before,external_flow=flow,
            nav=nav,cash=cash,spx_price=float(quote[0]),ndx_price=float(quote[1]),spx_units=float(units[0]),ndx_units=float(units[1]),
            spx_value=float(units[0]*quote[0]),ndx_value=float(units[1]*quote[1]),
            spx_trade=float(delta[0]),ndx_trade=float(delta[1]),trade_notional=notional,trading_cost=fee,
            turnover=notional/pretrade if pretrade>0 else 0.,period_twr=period_factor-1,unit_nav=unit_nav,
            target_ndx=target,signal_active=active,signal_id=signal_id,signal_decision_at=signal_time,signal_reason=reason))
        previous_nav=nav
    ledger=pd.DataFrame(rows)
    peak=np.maximum.accumulate(np.maximum(ledger.unit_nav.to_numpy(),1.))
    ledger['drawdown']=ledger.unit_nav/peak-1
    cashflows.append(dict(date=ledger.date.iloc[-1],amount=float(ledger.nav.iloc[-1]),kind='terminal_valuation_not_sale'))
    flows=pd.DataFrame(cashflows)
    rate=xirr(flows)
    years=(ledger.date.iloc[-1]-ledger.date.iloc[0]).days/365.25
    returns=ledger.period_twr.iloc[1:]
    peak_value=1.;peak_date=ledger.date.iloc[0];completed=0;observed=0;unrecovered=False
    for r in ledger.itertuples():
        if r.unit_nav>=peak_value-1e-12:
            if unrecovered:completed=max(completed,(r.date-peak_date).days)
            peak_value=max(peak_value,r.unit_nav);peak_date=r.date;unrecovered=False
        else:observed=max(observed,(r.date-peak_date).days);unrecovered=True
    metrics=dict(strategy=strategy,start=str(ledger.date.iloc[0].date()),end=str(ledger.date.iloc[-1].date()),
        total_contributions=float(ledger.external_flow.sum()),terminal_nav=float(ledger.nav.iloc[-1]),
        profit_after_flows=float(ledger.nav.iloc[-1]-ledger.external_flow.sum()),twr_total_return=float(unit_nav-1),
        twr_cagr=float(unit_nav**(1/years)-1) if years>0 else np.nan,
        annualized_volatility=float(returns.std(ddof=1)*np.sqrt(12)) if len(returns)>1 else np.nan,
        downside_volatility=float(np.sqrt(np.mean(np.minimum(returns,0)**2))*np.sqrt(12)) if len(returns) else np.nan,
        max_drawdown=float(ledger.drawdown.min()),longest_recovery_days_completed=completed,
        longest_drawdown_days_observed=max(observed,completed),unrecovered_at_end=unrecovered,
        annualized_turnover=float(ledger.turnover.sum()/years) if years>0 else np.nan,
        total_cost=float(ledger.trading_cost.sum()),xirr=rate['rate'],xirr_status=rate['status'],
        sharpe=None,sharpe_status='no_verified_risk_free_series',active_tilt_months=int(ledger.signal_active.sum()),
        cost_bps=cost_bps,max_tilt=max_tilt if strategy=='limited_tilt_new_money' else 0.,simulation_kind='monthly_index_proxy')
    return ledger,flows,metrics
