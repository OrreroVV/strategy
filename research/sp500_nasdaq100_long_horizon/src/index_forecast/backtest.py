"""Expanding/rolling origin evaluation with strict target maturity and fixed parameters."""
import warnings
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression, Ridge, ElasticNet
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.exceptions import ConvergenceWarning
from .data import FEATURES
from .feature_registry import feature_set
from .splits import eligible_training_rows

FORECAST_COLUMNS = ['forecast_date','index_id','horizon_months','model_name',
    'predicted_log_annual_return','predicted_cagr','actual_log_annual_return','actual_cagr','error',
    'label_end','training_start','training_end','n_train','max_training_label_end','data_vintage_cutoff',
    'output_type','evidence_grade','lower_80','upper_80','lower_95','upper_95']
METRIC_COLUMNS = ['index_id','horizon_months','model_name','n_oos','rmse','mae',
    'direction_accuracy','oos_r2','disjoint_outcome_windows','first_forecast','last_forecast']


def training_rows(ds, origin, embargo_months=0, window_months=None):
    if 'label_available_at' in ds:
        return eligible_training_rows(ds,origin,FEATURES,embargo_months=embargo_months,
            window_months=window_months,require_availability=True)
    cutoff = (pd.Timestamp(origin).to_period('M')-embargo_months).to_timestamp('M')
    p = ds[(ds.date < origin) & (ds.label_end < cutoff) & ds.y.notna()]
    if window_months is not None:
        p = p[p.date >= (pd.Timestamp(origin).to_period('M')-window_months).to_timestamp('M')]
    return p.dropna(subset=FEATURES).sort_values('date')


def fit_predict(name, x, y, test, config, *, feature_set_id='absolute_v1'):
    registered = list(feature_set(feature_set_id))
    if list(x.columns) != registered or list(test.columns) != registered:
        raise ValueError('Only registered causal feature columns accepted')
    if len(x) == 0 or not np.isfinite(x.to_numpy()).all() or not np.isfinite(y).all():
        raise ValueError('No valid finite training data')
    if not np.isfinite(test.to_numpy()).all(): raise ValueError('Missing forecast features')
    if name == 'historical_mean':
        mean = float(np.mean(y))
        return np.repeat(mean,len(test)), {'mean_matured_log_annual_return':mean,
            'equivalent_mean_monthly_log_return':mean/12,'cagr':float(np.expm1(mean))}
    constructors = dict(ols=lambda:LinearRegression(), ridge=lambda:Ridge(alpha=config['ridge_alpha']),
        elastic_net=lambda:ElasticNet(alpha=config['elastic_alpha'],l1_ratio=config['elastic_l1_ratio'],
                                     max_iter=20000,tol=1e-8,selection='cyclic'))
    if name not in constructors: raise ValueError(f'Unsupported model: {name}')
    model = make_pipeline(StandardScaler(), constructors[name]())
    with warnings.catch_warnings():
        warnings.simplefilter('error', ConvergenceWarning)
        model.fit(x,y)
    scaler, reg = model.steps[0][1], model.steps[1][1]
    result = model.predict(test)
    if not np.isfinite(result).all(): raise ValueError('Nonfinite model prediction')
    return result, dict(scaler_mean=scaler.mean_.tolist(),scaler_scale=scaler.scale_.tolist(),
        standardized_coefficients=np.asarray(reg.coef_).tolist(),intercept=float(reg.intercept_),
        params=reg.get_params())


def run_backtest(ds, validation, models):
    records, audits, skips = [], [], []
    holdout = pd.Timestamp(validation['holdout_start'])
    for (j,h), g in ds.groupby(['index_id','horizon_months'],sort=True):
        g = g.sort_values('date')
        candidates = g[(g.date >= holdout) & g.y.notna()]
        for _, row in candidates.iterrows():
            origin = row.date
            # Calendar cadence is anchored to the configured holdout, not surviving row positions.
            if (origin.to_period('M').ordinal-holdout.to_period('M').ordinal) % validation['step_months']: continue
            decision = row.get('decision_at',origin)
            train = training_rows(g,decision,validation['embargo_months'],validation.get('window_months'))
            reason = None
            if row[FEATURES].isna().any(): reason = 'missing_features'
            elif 'feature_available_at' in row and (pd.isna(row.feature_available_at) or row.feature_available_at>decision):
                reason = 'unavailable_features_at_decision'
            elif len(train) < validation['min_train']: reason = 'insufficient_matured_training_labels'
            if reason:
                skips.append(dict(index_id=j,horizon_months=int(h),forecast_date=origin,reason=reason,n_train=len(train)))
                continue
            cutoff = (origin.to_period('M')-validation['embargo_months']).to_timestamp('M')
            if not (train.label_end < cutoff).all(): raise ValueError('Leakage: immature or overlapping training labels')
            x = train[FEATURES]
            test = g.loc[g.date == origin,FEATURES]
            for name in models['names']:
                pred,meta = fit_predict(name,x,train.y.to_numpy(),test,models)
                p = float(pred[0])
                records.append(dict(forecast_date=origin,index_id=j,horizon_months=int(h),model_name=name,
                    predicted_log_annual_return=p,predicted_cagr=float(np.expm1(p)),actual_log_annual_return=float(row.y),
                    actual_cagr=float(row.cagr),error=p-float(row.y),label_end=row.label_end,
                    training_start=train.date.min(),training_end=train.date.max(),n_train=len(train),
                    max_training_label_end=train.label_end.max(),data_vintage_cutoff=origin,
                    output_type='historical_oos',evidence_grade='D',
                    lower_80=np.nan,upper_80=np.nan,lower_95=np.nan,upper_95=np.nan))
                audits.append(dict(index_id=j,horizon_months=int(h),forecast_date=str(origin),model_name=name,
                    training_dates=[str(d) for d in train.date],max_training_label_end=str(train.label_end.max()),
                    preprocessing_fit_end=str(train.date.max()), metadata=meta))
    return (pd.DataFrame(records,columns=FORECAST_COLUMNS), audits,
            pd.DataFrame(skips,columns=['index_id','horizon_months','forecast_date','reason','n_train']))


def evaluate(predictions):
    if predictions.empty: return pd.DataFrame(columns=METRIC_COLUMNS)
    keys = ['forecast_date','index_id','horizon_months']
    base = predictions[predictions.model_name == 'historical_mean'][keys+['predicted_log_annual_return']]
    merged = predictions.merge(base.rename(columns={'predicted_log_annual_return':'baseline'}),on=keys,validate='many_to_one')
    rows = []
    for (j,h,m),g in merged.groupby(['index_id','horizon_months','model_name'],sort=True):
        err = g.predicted_log_annual_return-g.actual_log_annual_return
        baseline_error = g.baseline-g.actual_log_annual_return
        denominator = float(np.square(baseline_error).sum())
        # Count disjoint realized outcome windows; still not independent economic regimes.
        end, disjoint = None, 0
        for _,r in g.sort_values('forecast_date').iterrows():
            if end is None or pd.to_datetime(r.forecast_date,utc=True) > end:
                disjoint += 1
                end = pd.to_datetime(r.label_end,utc=True)
        rows.append(dict(index_id=j,horizon_months=int(h),model_name=m,n_oos=len(g),
            rmse=float(np.sqrt(np.mean(err**2))),mae=float(np.mean(np.abs(err))),
            direction_accuracy=float(np.mean(np.sign(g.predicted_log_annual_return)==np.sign(g.actual_log_annual_return))),
            oos_r2=1-float(np.square(err).sum())/denominator if denominator > 0 else np.nan,
            disjoint_outcome_windows=disjoint,first_forecast=g.forecast_date.min(),last_forecast=g.forecast_date.max()))
    return pd.DataFrame(rows)
