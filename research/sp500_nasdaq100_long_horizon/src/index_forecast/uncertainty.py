"""Empirical prequential error intervals; no conformal or independence guarantee."""
import numpy as np
import pandas as pd
from .point_in_time import utc_timestamp

GROUP_KEYS=['index_id','target_id','horizon_months','model_name','prediction_path','selection_version']


def finite_expm1(value):
    if not np.isfinite(value) or value>np.log(np.finfo(float).max):return np.nan
    with np.errstate(over='ignore',invalid='ignore'):
        converted=float(np.expm1(value))
    return converted if np.isfinite(converted) else np.nan


def validate_predictions(frame):
    required=GROUP_KEYS+['forecast_date','decision_at','label_end','label_available_at','data_kind','output_type',
                        'predicted_log_annual_return','actual_log_annual_return']
    if set(required)-set(frame): raise ValueError('Incomplete OOS prediction provenance')
    p=frame.copy()
    if p.empty:return p
    if p.data_kind.nunique()!=1 or not p.data_kind.isin(['real','synthetic']).all():
        raise ValueError('Mixed/invalid prediction data_kind')
    if p[GROUP_KEYS+['forecast_date']].isna().any().any():raise ValueError('Missing prediction identity')
    if p.duplicated(GROUP_KEYS+['forecast_date']).any():raise ValueError('Duplicate prediction identity')
    p['forecast_date']=pd.to_datetime(p.forecast_date,utc=True).dt.tz_localize(None)
    p['label_end']=pd.to_datetime(p.label_end,utc=True)
    for col in ['decision_at','label_available_at']:
        p[col]=pd.to_datetime([utc_timestamp(x,col) if pd.notna(x) else pd.NaT for x in p[col]],utc=True)
    if p.decision_at.isna().any():raise ValueError('Missing decision_at')
    if (p.label_end<pd.to_datetime(p.forecast_date,utc=True)).any():raise ValueError('Inverted label interval')
    for col in ['predicted_log_annual_return','actual_log_annual_return']:
        p[col]=pd.to_numeric(p[col],errors='raise')
        if np.isinf(p[col]).any():raise ValueError('Infinite forecast/outcome')
    if 'output_type' in p and not p.output_type.eq('historical_oos').all():
        raise ValueError('Only historical OOS errors may calibrate intervals')
    return p


def mature_history(history,decision_at):
    if history.empty:return history.copy()
    t=utc_timestamp(decision_at)
    p=history.copy()
    for col in ['decision_at','label_available_at','label_end']:
        p[col]=pd.to_datetime(p[col],utc=True)
    mask=(p.decision_at<t)&(p.label_available_at<t)&(p.label_end<t.normalize())
    if 'predicted_log_annual_return' in p:mask &= np.isfinite(p.predicted_log_annual_return)
    if 'actual_log_annual_return' in p:mask &= np.isfinite(p.actual_log_annual_return)
    return p.loc[mask].sort_values('forecast_date')


def disjoint_count(frame):
    last=None;count=0
    for row in frame.sort_values('forecast_date').itertuples():
        start=pd.Timestamp(row.forecast_date)
        start=start.tz_localize('UTC') if start.tzinfo is None else start.tz_convert('UTC')
        end=pd.Timestamp(row.label_end)
        end=end.tz_localize('UTC') if end.tzinfo is None else end.tz_convert('UTC')
        if last is None or start>last:count+=1;last=end
    return count


def calibrate_intervals(predictions,settings):
    p=validate_predictions(predictions)
    records=[];audits=[]
    for _,g in p.groupby(GROUP_KEYS,sort=True):
        for _,row in g.sort_values('forecast_date').iterrows():
            past=mature_history(g,row.decision_at)
            n=len(past);blocks=disjoint_count(past)
            record=row.to_dict()
            for level,quantiles in [(80,(.10,.90)),(95,(.025,.975))]:
                ok=(n>=settings[f'min_residuals_{level}'] and blocks>=settings[f'min_disjoint_{level}']
                    and np.isfinite(row.predicted_log_annual_return))
                record[f'interval_status_{level}']='available' if ok else 'insufficient_history'
                record[f'interval_transform_status_{level}']='unavailable'
                for unit in ['log','cagr','relative_wealth_cagr']:
                    for side in ['lower','upper']:record[f'{side}_{level}_{unit}']=np.nan
                if ok:
                    errors=(past.actual_log_annual_return-past.predicted_log_annual_return).to_numpy()
                    lower,upper=row.predicted_log_annual_return+np.quantile(errors,quantiles,method='linear')
                    record[f'lower_{level}_log']=float(lower);record[f'upper_{level}_log']=float(upper)
                    unit='relative_wealth_cagr' if row.target_id=='relative_log_return' else 'cagr'
                    record[f'lower_{level}_{unit}']=finite_expm1(lower)
                    record[f'upper_{level}_{unit}']=finite_expm1(upper)
                    record[f'interval_transform_status_{level}']='available' if np.isfinite(finite_expm1(upper)) else 'numeric_overflow'
            record['n_calibration']=n;record['disjoint_calibration_windows']=blocks
            records.append(record)
            audits.append({k:str(row[k]) for k in GROUP_KEYS+['forecast_date','decision_at']}|dict(
                n_calibration=n,disjoint_windows=blocks,
                calibration_forecast_dates=[str(x) for x in past.forecast_date],
                max_label_available_at=str(past.label_available_at.max()) if n else None,
                max_label_end=str(past.label_end.max()) if n else None,
                method='past_matured_oos_error_quantiles_no_coverage_guarantee'))
    if not records:
        empty=p.copy()
        for level in [80,95]:
            empty[f'interval_status_{level}']=pd.Series(dtype=str)
            for unit in ['log','cagr','relative_wealth_cagr']:
                for side in ['lower','upper']:empty[f'{side}_{level}_{unit}']=pd.Series(dtype=float)
        return empty,audits
    return pd.DataFrame(records),audits


def interval_metrics(intervals):
    rows=[]
    for identity,g in intervals.groupby(GROUP_KEYS,sort=True):
        row=dict(zip(GROUP_KEYS,identity));row['n_forecasts']=len(g)
        for level in [80,95]:
            good=g[g[f'lower_{level}_log'].notna() & g.actual_log_annual_return.notna()]
            n=len(good)
            row[f'n_intervals_{level}']=n
            row[f'availability_{level}']=n/len(g)
            row[f'coverage_{level}']=float(((good.actual_log_annual_return>=good[f'lower_{level}_log']) &
                (good.actual_log_annual_return<=good[f'upper_{level}_log'])).mean()) if n else np.nan
            row[f'mean_width_{level}_log']=float((good[f'upper_{level}_log']-good[f'lower_{level}_log']).mean()) if n else np.nan
        rows.append(row)
    return pd.DataFrame(rows,columns=GROUP_KEYS+['n_forecasts']+
        [f'{k}_{level}'+('_log' if k=='mean_width' else '') for level in [80,95] for k in ['n_intervals','availability','coverage','mean_width']])
