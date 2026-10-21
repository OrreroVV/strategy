"""Development-only causal ensembles. Missing candidates never silently disappear."""
import json
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from ..uncertainty import validate_predictions, mature_history, disjoint_count, finite_expm1


def simplex_weights(x,y,eta):
    x=np.asarray(x,dtype=float);y=np.asarray(y,dtype=float)
    if x.ndim!=2 or y.ndim!=1 or not x.shape[1] or len(x)!=len(y) or not len(y) or not np.isfinite(eta) or eta<0 or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError('Invalid ensemble fit matrix')
    equal=np.full(x.shape[1],1/x.shape[1])
    def loss(w):return float(np.mean((x@w-y)**2)+eta*np.sum((w-equal)**2))
    def gradient(w):return 2*x.T@(x@w-y)/len(y)+2*eta*(w-equal)
    result=minimize(loss,equal,jac=gradient,method='SLSQP',bounds=[(0,1)]*len(equal),
                    constraints=[{'type':'eq','fun':lambda w:w.sum()-1,'jac':lambda w:np.ones_like(w)}],
                    options=dict(ftol=1e-12,maxiter=1000))
    if not result.success:raise ValueError(f'Ensemble optimizer failed: {result.message}')
    if abs(result.x.sum()-1)>1e-7 or np.min(result.x)<-1e-7:raise ValueError('Ensemble optimizer violated simplex constraints')
    w=np.maximum(result.x,0);w/=w.sum()
    return w


def build_ensembles(predictions,candidates,settings):
    p=validate_predictions(predictions)
    if not candidates or len(candidates)!=len(set(candidates)) or 'historical_mean' not in candidates:
        raise ValueError('Unique candidates including historical_mean required')
    if any(name.startswith('ensemble_') for name in candidates):raise ValueError('Recursive ensembles forbidden')
    if not settings['rhos'] or any(not 0<=rho<=1 for rho in settings['rhos']):raise ValueError('Invalid shrink grid')
    records=[];audits=[]
    group=['index_id','target_id','horizon_months','prediction_path','selection_version']
    for _,g in p[p.model_name.isin(candidates)].groupby(group,sort=True):
        complete=[];weighted_history=[]
        for date,current in g.groupby('forecast_date',sort=True):
            row=current.iloc[0].to_dict()
            for col in ['actual_log_annual_return','label_end','label_available_at','decision_at']:
                if current[col].nunique(dropna=False)!=1:raise ValueError(f'Base model cohort disagreement: {col}')
            indexed=current.set_index('model_name')
            good=all(name in indexed.index and np.isfinite(indexed.loc[name,'predicted_log_annual_return']) for name in candidates)
            past=mature_history(pd.DataFrame(complete),row['decision_at'])
            shrink_past=mature_history(pd.DataFrame(weighted_history),row['decision_at'])
            sufficient=len(past)>=settings['min_history'] and disjoint_count(past)>=settings['min_disjoint']
            shrink_ok=len(shrink_past)>=settings['min_history'] and disjoint_count(shrink_past)>=settings['min_disjoint']
            equal=np.full(len(candidates),1/len(candidates));w=equal.copy();rho=0.;rho_scores={}
            if good and sufficient:
                w=simplex_weights(np.stack(past.vector),past.actual_log_annual_return.to_numpy(),settings['eta'])
            if good and shrink_ok:
                for choice in sorted(settings['rhos']):
                    pred=choice*shrink_past.weighted_prediction+(1-choice)*shrink_past.baseline_prediction
                    rho_scores[str(choice)]=float(np.mean((pred-shrink_past.actual_log_annual_return)**2))
                # Equal validation loss chooses the smaller rho, i.e. more baseline shrinkage.
                rho=min(sorted(settings['rhos']),key=lambda x:rho_scores[str(x)])
            vector=indexed.predicted_log_annual_return.reindex(candidates).to_numpy() if good else np.full(len(candidates),np.nan)
            baseline_vector=np.zeros(len(candidates));baseline_vector[candidates.index('historical_mean')]=1
            definitions=[('ensemble_equal',equal,1.,'equal_weight'),
                ('ensemble_weighted',w,1.,'fitted' if sufficient else 'equal_weight_fallback'),
                ('ensemble_shrink',rho*w+(1-rho)*baseline_vector,rho,'fitted' if shrink_ok else 'baseline_fallback')]
            for name,weights,shrink,status in definitions:
                result=row.copy()
                # These refer to component-model predictions, not the ensemble: never propagate them.
                for key in ['prediction_id','predicted_cagr_difference','predicted_spx_log_return',
                            'predicted_ndx_log_return','predicted_relative_wealth_cagr','predicted_relative_return','error']:
                    result.pop(key,None)
                prediction=float(vector@weights) if good else np.nan
                result.update(model_name=name,predicted_log_annual_return=prediction,
                    ensemble_status=status if good else 'missing_base_models',rho=shrink,
                    weights_json=json.dumps(dict(zip(candidates,map(float,weights))),sort_keys=True),
                    n_weight_history=len(past),n_shrink_history=len(shrink_past),
                    selection_version=row['selection_version']+'__ensemble_prequential_v1',evidence_grade='D')
                if row['target_id']=='nominal_log_return':result['predicted_cagr']=finite_expm1(prediction)
                else:result['predicted_relative_wealth_cagr']=finite_expm1(prediction)
                records.append(result)
                audits.append(dict(forecast_date=str(date),decision_at=str(row['decision_at']),model_name=name,
                    index_id=row['index_id'],horizon_months=int(row['horizon_months']),prediction_path=row['prediction_path'],
                    status=result['ensemble_status'],weights=dict(zip(candidates,map(float,weights))),rho=shrink,
                    weight_history_dates=[str(x) for x in past.forecast_date] if len(past) else [],
                    shrink_history_dates=[str(x) for x in shrink_past.forecast_date] if len(shrink_past) else [],
                    max_weight_label_available_at=str(past.label_available_at.max()) if len(past) else None,
                    max_shrink_label_available_at=str(shrink_past.label_available_at.max()) if len(shrink_past) else None,
                    rho_scores=rho_scores))
            if good:
                history=dict(forecast_date=date,decision_at=row['decision_at'],label_end=row['label_end'],
                    label_available_at=row['label_available_at'],actual_log_annual_return=row['actual_log_annual_return'])
                complete.append(history|dict(vector=vector))
                weighted_history.append(history|dict(weighted_prediction=float(vector@w),
                    baseline_prediction=float(vector@baseline_vector)))
    if not records:
        empty=p.iloc[:0].copy()
        empty['ensemble_status']=pd.Series(dtype=str)
        return empty,audits
    return pd.DataFrame(records),audits
