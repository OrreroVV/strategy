import numpy as np
import pandas as pd
from index_forecast.models.ensemble import build_ensembles, simplex_weights
from test_uncertainty import predictions


def test_simplex_solution_and_equal_fallback():
    x=np.array([[.1,.2],[.2,.1],[.1,.3]])
    w=simplex_weights(x,np.array([.15,.15,.2]),.01)
    assert np.all(w>=0) and abs(w.sum()-1)<1e-10
    p=predictions(180)
    p2=p.copy()
    p['model_name']='historical_mean'
    p2['predicted_log_annual_return']=.05
    data=pd.concat([p,p2],ignore_index=True)
    out,audit=build_ensembles(data,['historical_mean','ridge'],dict(min_history=60,min_disjoint=5,eta=.01,rhos=[0,.5,1]))
    first=out[out.forecast_date==out.forecast_date.min()]
    assert first[first.model_name=='ensemble_equal'].predicted_log_annual_return.iloc[0]==.045
    assert first[first.model_name=='ensemble_weighted'].ensemble_status.iloc[0]=='equal_weight_fallback'
    assert first[first.model_name=='ensemble_shrink'].predicted_log_annual_return.iloc[0]==.04
    assert audit and out[out.model_name=='ensemble_weighted'].ensemble_status.eq('fitted').any()


def test_ensemble_future_outcomes_do_not_change_past_weights():
    p=predictions(100)
    p['model_name']='historical_mean'
    p2=p.copy();p2['model_name']='ridge';p2['predicted_log_annual_return']=.05
    base=pd.concat([p,p2],ignore_index=True)
    cfg=dict(min_history=20,min_disjoint=5,eta=.01,rhos=[0,.5,1])
    a,_=build_ensembles(base,['historical_mean','ridge'],cfg)
    changed=base.copy();cutoff=p.decision_at.iloc[60]
    changed.loc[changed.label_available_at>=cutoff,'actual_log_annual_return']=999
    b,_=build_ensembles(changed,['historical_mean','ridge'],cfg)
    columns=['forecast_date','model_name','predicted_log_annual_return','weights_json','rho']
    pd.testing.assert_frame_equal(a.loc[a.decision_at<=cutoff,columns],b.loc[b.decision_at<=cutoff,columns])


def test_missing_candidate_is_not_renormalized():
    p=predictions(5);p['model_name']='historical_mean'
    out,_=build_ensembles(p,['historical_mean','ridge'],dict(min_history=60,min_disjoint=5,eta=.01,rhos=[0,1]))
    assert out.predicted_log_annual_return.isna().all()
    assert set(out.ensemble_status)=={'missing_base_models'}


def test_optimizer_prefers_perfect_component_when_unpenalized():
    y=np.array([.1,.2,.3,.4])
    x=np.column_stack([y,y+.5])
    w=simplex_weights(x,y,0.)
    assert w[0]>.999999
