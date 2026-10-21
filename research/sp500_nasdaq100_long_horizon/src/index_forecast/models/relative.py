"""Paired direct/indirect relative-return forecasts with auditable common cohorts."""
import numpy as np
import pandas as pd
from ..backtest import fit_predict, evaluate
from ..data import FEATURES, DataError
from ..feature_registry import feature_set, schema_hash
from ..splits import eligible_training_rows

KEYS = ['forecast_date','horizon_months','model_name']
FORECAST_COLUMNS = ['forecast_date','decision_at','index_id','target_id','target_unit','horizon_months',
    'model_name','prediction_path','predicted_log_annual_return','predicted_relative_return',
    'predicted_relative_wealth_cagr','predicted_cagr_difference','predicted_spx_log_return',
    'predicted_ndx_log_return','actual_log_annual_return','error','label_end',
    'training_start','training_end','n_train','max_training_label_end','max_training_label_available_at',
    'max_training_feature_available_at','current_feature_available_at','feature_schema_hash',
    'data_vintage_cutoff','output_type','evidence_grade','clock_policy']
COVERAGE_COLUMNS = ['forecast_date','horizon_months','status','reason','n_spx_available_train',
    'n_ndx_available_train','n_common_train','spx_current_features_available','ndx_current_features_available']


def paired_dataset(ds):
    keys = ['date','horizon_months']
    if ds.duplicated(keys+['index_id']).any(): raise DataError('Duplicate paired dataset key')
    if set(ds.index_id)-{'SPX','NDX'}: raise DataError('Unexpected relative input index')
    sides = []
    for j,suffix in [('SPX','spx'),('NDX','ndx')]:
        g = ds[ds.index_id==j].copy()
        sides.append(g.rename(columns={col:f'{col}_{suffix}' for col in g if col not in keys}))
    p = sides[0].merge(sides[1],on=keys,how='outer',validate='one_to_one').sort_values(keys)
    for col in ['decision_at','label_end']:
        a,b = p[f'{col}_spx'],p[f'{col}_ndx']
        if ((a.notna() & b.notna()) & (a!=b)).any(): raise DataError(f'Paired {col} mismatch')
        p[col] = a.combine_first(b)
    for col in ['feature_available_at','label_available_at']:
        a,b = p[f'{col}_spx'],p[f'{col}_ndx']
        p[col] = p[[f'{col}_spx',f'{col}_ndx']].max(axis=1).where(a.notna() & b.notna())
    p['y'] = p.y_ndx-p.y_spx
    for name in FEATURES:
        p[f'{name}_difference'] = p[f'{name}_ndx']-p[f'{name}_spx']
    return p.reset_index(drop=True)


def _current_available(row,side):
    if pd.isna(row[f'feature_available_at_{side}']) or pd.isna(row.decision_at): return False
    values = np.asarray([row[f'{c}_{side}'] for c in FEATURES],dtype=float)
    return bool(np.isfinite(values).all() and row[f'feature_available_at_{side}']<=row.decision_at)


def run_relative_backtest(ds,validation,models):
    """No tuning or intervals: fixed P0 linear models, two common-cohort paths."""
    p = paired_dataset(ds)
    records,audits,coverage = [],[],[]
    holdout = pd.Timestamp(validation['holdout_start'])
    if ds.data_kind.nunique()!=1: raise DataError('Mixed data_kind in relative dataset')
    if ds.clock_policy.nunique()!=1: raise DataError('Mixed clock policies')
    joint_features = [f'{name}_{s}' for s in ['spx','ndx'] for name in FEATURES]
    for h,g in p.groupby('horizon_months',sort=True):
        for _,row in g[g.date>=holdout].iterrows():
            origin = row.date
            if (origin.to_period('M').ordinal-holdout.to_period('M').ordinal)%validation['step_months']: continue
            decision = row.decision_at
            train = eligible_training_rows(g,decision,joint_features,
                embargo_months=validation['embargo_months'],window_months=validation.get('window_months'),
                require_availability=True)
            natural_counts = []
            for index in ['SPX','NDX']:
                side = ds[(ds.index_id==index)&(ds.horizon_months==h)]
                natural_counts.append(len(eligible_training_rows(side,decision,FEATURES,
                    embargo_months=validation['embargo_months'],window_months=validation.get('window_months'),
                    require_availability=True)))
            spx_ok,ndx_ok = _current_available(row,'spx'),_current_available(row,'ndx')
            reason = ''
            if pd.isna(row.y): reason = 'unmatured_or_missing_paired_label'
            elif not spx_ok or not ndx_ok: reason = 'missing_or_unavailable_paired_features'
            elif len(train)<validation['min_train']: reason = 'insufficient_common_matured_training_labels'
            coverage.append(dict(forecast_date=origin,horizon_months=int(h),status='skipped' if reason else 'predicted',
                reason=reason,n_spx_available_train=natural_counts[0],n_ndx_available_train=natural_counts[1],
                n_common_train=len(train),spx_current_features_available=spx_ok,ndx_current_features_available=ndx_ok))
            if reason: continue
            direct_columns = list(feature_set('relative_v1'))
            common = dict(forecast_date=origin,decision_at=decision,index_id='REL',target_id='relative_log_return',
                target_unit='annualized_log_return_difference',horizon_months=int(h),
                actual_log_annual_return=float(row.y),label_end=row.label_end,
                training_start=train.date.min(),training_end=train.date.max(),n_train=len(train),
                max_training_label_end=train.label_end.max(),max_training_label_available_at=train.label_available_at.max(),
                max_training_feature_available_at=train.feature_available_at.max(),current_feature_available_at=row.feature_available_at,
                data_vintage_cutoff=decision,output_type='historical_oos',evidence_grade='D',clock_policy=ds.clock_policy.iloc[0])
            current = g[g.date==origin]
            for name in models['names']:
                direct,direct_meta = fit_predict(name,train[direct_columns],train.y.to_numpy(),
                    current[direct_columns],models,feature_set_id='relative_v1')
                absolute_predictions,absolute_metadata = {},{}
                for side in ['spx','ndx']:
                    columns = [f'{f}_{side}' for f in FEATURES]
                    rename = {f'{f}_{side}':f for f in FEATURES}
                    prediction,meta = fit_predict(name,train[columns].rename(columns=rename),train[f'y_{side}'].to_numpy(),
                        current[columns].rename(columns=rename),models)
                    absolute_predictions[side] = float(prediction[0])
                    absolute_metadata[side] = meta
                for path,value,meta in [('direct',float(direct[0]),direct_meta),
                    ('indirect',absolute_predictions['ndx']-absolute_predictions['spx'],absolute_metadata)]:
                    record = common | dict(model_name=name,prediction_path=path,
                        predicted_log_annual_return=value,predicted_relative_return=value,
                        predicted_relative_wealth_cagr=float(np.expm1(value)),
                        predicted_cagr_difference=(float(np.expm1(absolute_predictions['ndx'])-np.expm1(absolute_predictions['spx'])) if path=='indirect' else np.nan),
                        predicted_spx_log_return=absolute_predictions['spx'] if path=='indirect' else np.nan,
                        predicted_ndx_log_return=absolute_predictions['ndx'] if path=='indirect' else np.nan,
                        error=value-float(row.y),feature_schema_hash=schema_hash('relative_v1' if path=='direct' else 'absolute_v1'))
                    records.append(record)
                    audits.append(dict(forecast_date=str(origin),decision_at=str(decision),horizon_months=int(h),
                        model_name=name,prediction_path=path,feature_schema_hash=record['feature_schema_hash'],
                        training_dates=[str(d) for d in train.date],n_train=len(train),
                        max_training_label_end=str(train.label_end.max()),
                        max_training_label_available_at=str(train.label_available_at.max()),
                        max_training_feature_available_at=str(train.feature_available_at.max()),metadata=meta))
    return pd.DataFrame(records,columns=FORECAST_COLUMNS),audits,pd.DataFrame(coverage,columns=COVERAGE_COLUMNS)


def evaluate_relative(forecasts):
    metrics=[]
    if forecasts.empty:
        return pd.DataFrame(columns=['index_id','horizon_months','model_name','prediction_path','n_oos','rmse','mae','oos_r2']),pd.DataFrame(columns=KEYS+['direct','indirect','difference','direction_conflict'])
    for path,g in forecasts.groupby('prediction_path',sort=True):
        m=evaluate(g)
        m['prediction_path']=path
        metrics.append(m)
    pivot=forecasts.pivot(index=KEYS,columns='prediction_path',values='predicted_log_annual_return')
    if not {'direct','indirect'}.issubset(pivot.columns) or pivot[['direct','indirect']].isna().any().any():
        raise DataError('Relative path comparison requires fully paired predictions')
    pivot=pivot.reset_index()
    pivot['difference']=pivot.direct-pivot.indirect
    pivot['direction_conflict']=np.sign(pivot.direct)!=np.sign(pivot.indirect)
    pivot.columns.name=None
    return pd.concat(metrics,ignore_index=True),pivot
