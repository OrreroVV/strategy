"""Approximate dividend/EPS/valuation decomposition using only available fields."""
import numpy as np
import pandas as pd
from ..point_in_time import utc_timestamp

REQUIRED=['date','trailing_pe','eps_ttm','dividend_yield','pe_available_at','eps_available_at',
          'dividend_available_at','pe_definition_id','eps_definition_id']


def valuation_forecast(history,decision_at,horizon_months,lambda_value=1.,reference_window=120,
                       min_pe=60,eps_window=60,min_eps_months=36):
    missing=sorted(set(REQUIRED)-set(history))
    if missing:return dict(status='missing_fields',reason=','.join(missing))
    if type(horizon_months) is not int or horizon_months<=0 or not 0<=lambda_value<=1:
        raise ValueError('Invalid valuation horizon/lambda')
    if any(type(x) is not int or x<=0 for x in [reference_window,min_pe,eps_window,min_eps_months]):
        raise ValueError('Positive calendar windows/counts required')
    t=utc_timestamp(decision_at);month=t.tz_localize(None).to_period('M')
    p=history.copy();p['date']=pd.to_datetime(p.date)
    if p.date.dt.to_period('M').duplicated().any() or not p.date.dt.is_month_end.all():
        raise ValueError('Unique calendar month-end valuation observations required')
    p=p[p.date.dt.to_period('M')<=month].sort_values('date')
    for name in ['pe_available_at','eps_available_at','dividend_available_at']:
        p[name]=pd.to_datetime([utc_timestamp(v,name) if pd.notna(v) else pd.NaT for v in p[name]],utc=True)
    pe=p[(p.pe_available_at<=t)&(p.date.dt.to_period('M')>month-reference_window)]
    eps=p[(p.eps_available_at<=t)&(p.date.dt.to_period('M')>=month-eps_window)]
    dy=p[(p.dividend_available_at<=t)&(p.date.dt.to_period('M')==month)]
    if len(pe)<min_pe or not pe.date.dt.to_period('M').eq(month).any():return dict(status='insufficient_pe_history')
    if pe.pe_definition_id.isna().any() or pe.pe_definition_id.nunique()!=1 or eps.eps_definition_id.isna().any() or eps.eps_definition_id.nunique()!=1:
        return dict(status='definition_change')
    pe_values=pd.to_numeric(pe.trailing_pe,errors='coerce')
    if not np.isfinite(pe_values).all() or (pe_values<=0).any():return dict(status='invalid_pe')
    eps_values=pd.to_numeric(eps.eps_ttm,errors='coerce')
    if not np.isfinite(eps_values).all() or (eps_values<=0).any():return dict(status='invalid_eps')
    if len(eps)<min_eps_months:return dict(status='insufficient_eps_history')
    old=eps[eps.date.dt.to_period('M')==month-eps_window]
    current=eps[eps.date.dt.to_period('M')==month]
    if old.empty or current.empty:return dict(status='missing_eps_endpoint')
    if dy.empty:return dict(status='missing_current_dividend')
    yield_value=float(pd.to_numeric(dy.iloc[-1].dividend_yield,errors='coerce'))
    if not np.isfinite(yield_value) or not 0<=yield_value<=1:return dict(status='invalid_dividend_yield_ratio')
    v=float(np.log(float(pe.iloc[-1].trailing_pe)));reference=float(np.median(np.log(pe_values)))
    terminal=lambda_value*v+(1-lambda_value)*reference
    dividend=float(np.log1p(yield_value));growth=float(12/eps_window*np.log(float(current.iloc[-1].eps_ttm)/float(old.iloc[-1].eps_ttm)))
    valuation=float((terminal-v)/(horizon_months/12))
    return dict(status='available',predicted_log_annual_return=dividend+growth+valuation,
        dividend_log=dividend,eps_growth_log=growth,valuation_log=valuation,
        reference_log_pe=reference,current_log_pe=v,terminal_log_pe=terminal,lambda_value=float(lambda_value),
        reference_count=len(pe),eps_count=len(eps),parameter_status='fixed_unvalidated_no_inner_selection',
        pe_definition_id=str(pe.iloc[-1].pe_definition_id),eps_definition_id=str(eps.iloc[-1].eps_definition_id),
        max_pe_available_at=str(pe.pe_available_at.max()),max_eps_available_at=str(eps.eps_available_at.max()),
        dividend_available_at=str(dy.iloc[-1].dividend_available_at))
