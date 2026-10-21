from pathlib import Path
import math
import pandas as pd
import yaml


def load_config(path):
    path = Path(path).resolve()
    c = yaml.safe_load(path.read_text(encoding='utf-8'))
    root = path.parent.parent
    version = c.get('schema_version',1)
    if type(version) is not int or version not in [1,2]: raise ValueError('Unsupported schema_version')
    if 'relative' in c:
        if version!=2: raise ValueError('Relative backtest requires schema_version=2')
        if type(c['relative'].get('enabled')) is not bool: raise ValueError('relative.enabled must be boolean')
    if 'extensions' in c:
        e=c['extensions']
        if version!=2 or type(e.get('enabled')) is not bool:raise ValueError('P1 extensions require v2 and boolean enabled')
        if e['enabled']:
            if e.get('phase')!='development_prequential':raise ValueError('Extensions support development_prequential only; final audit not implemented')
            for key in ['min_residuals_80','min_disjoint_80','min_residuals_95','min_disjoint_95']:
                if type(e['intervals'][key]) is not int or e['intervals'][key]<=0:raise ValueError('Invalid interval history threshold')
            for key in ['min_history','min_disjoint']:
                if type(e['ensemble'][key]) is not int or e['ensemble'][key]<=0:raise ValueError('Invalid ensemble history threshold')
            if not math.isfinite(e['ensemble']['eta']) or e['ensemble']['eta']<0 or not e['ensemble']['rhos'] or any(type(x) not in [int,float] or not 0<=x<=1 for x in e['ensemble']['rhos']):raise ValueError('Invalid ensemble eta/rho')
            if type(e['valuation']['lambda_value']) not in [int,float] or not 0<=e['valuation']['lambda_value']<=1:raise ValueError('Invalid valuation lambda')
            for key in ['reference_window','min_pe','eps_window','min_eps_months']:
                if type(e['valuation'][key]) is not int or e['valuation'][key]<=0:raise ValueError('Invalid valuation window')
    horizons = c['targets']['horizons']
    if not horizons or len(horizons) != len(set(horizons)) or any(type(h) is not int or h <= 0 for h in horizons):
        raise ValueError('Unique positive month horizons required')
    v = c['validation']
    for key in ['min_train', 'step_months']:
        if type(v[key]) is not int or v[key] < 1: raise ValueError(f'Invalid {key}')
    if type(v['embargo_months']) is not int or v['embargo_months'] < 0: raise ValueError('Invalid embargo')
    if v.get('window_months') is not None and (type(v['window_months']) is not int or v['window_months'] <= 0):
        raise ValueError('Invalid rolling window')
    if not pd.Timestamp(v['holdout_start']).is_month_end: raise ValueError('holdout_start must be month end')
    names = c['models']['names']
    if not names or len(names) != len(set(names)) or 'historical_mean' not in names:
        raise ValueError('Unique model list including historical_mean required')
    if set(names)-{'historical_mean','ols','ridge','elastic_net'}: raise ValueError('Only P0 models supported')
    if c['models']['ridge_alpha'] <= 0 or c['models']['elastic_alpha'] <= 0:
        raise ValueError('Regularization alpha must be positive')
    if not 0 < c['models']['elastic_l1_ratio'] <= 1: raise ValueError('Invalid l1_ratio')
    if type(c['data']['allow_synthetic']) is not bool: raise ValueError('allow_synthetic must be boolean')
    if 'portfolio' in c:
        s=c['portfolio']
        if version!=2 or type(s.get('enabled')) is not bool:raise ValueError('Portfolio requires v2 and boolean enabled')
        if s['enabled']:
            if not c.get('extensions',{}).get('enabled') or not c.get('relative',{}).get('enabled'):
                raise ValueError('Portfolio requires relative and extensions modules')
            if s.get('simulation_kind')!='monthly_index_proxy':raise ValueError('Only monthly_index_proxy is implemented')
            for key in ['initial_capital','monthly_contribution']:
                if type(s[key]) not in [int,float] or not math.isfinite(s[key]) or s[key]<=0:raise ValueError('Positive funding required for both scenario groups')
            for key,upper in [('cost_bps',10000),('tilt_limits',1)]:
                values=s[key]
                if not values or len(values)!=len(set(values)) or any(type(x) not in [int,float] or not math.isfinite(x) or x<0 or x>=upper for x in values):raise ValueError('Invalid cost/tilt scenarios')
            if s['plot_cost_bps'] not in s['cost_bps'] or not any(math.isclose(s['plot_tilt_limit'],x) for x in s['tilt_limits']):raise ValueError('Plot scenario must be included')
            if not 0<=s['strategic_ndx']<=1 or type(s['max_signal_age_months']) is not int or s['max_signal_age_months']<1:raise ValueError('Invalid strategic target/signal age')
            if not s['review_months'] or any(type(x) is not int or not 1<=x<=12 for x in s['review_months']):raise ValueError('Invalid quarterly review months')
            if s['signal_horizon_months'] not in horizons or s['signal_model'] not in set(names)|{'ensemble_equal','ensemble_weighted','ensemble_shrink'}:raise ValueError('Unknown signal horizon/model')
            if not pd.Timestamp(s['start']).is_month_end or s.get('end') and (not pd.Timestamp(s['end']).is_month_end or pd.Timestamp(s['end'])<pd.Timestamp(s['start'])):raise ValueError('Invalid strategy span')
    if 'plots' in c:
        s=c['plots']
        if type(s.get('enabled')) is not bool:raise ValueError('plots.enabled must be boolean')
        if s['enabled']:
            if s['horizon_months'] not in horizons or s['model_name'] not in names:raise ValueError('Unknown plot horizon/model')
            if c.get('portfolio',{}).get('enabled') and (s['cost_bps']!=c['portfolio']['plot_cost_bps'] or s['tilt_limit']!=c['portfolio']['plot_tilt_limit']):raise ValueError('Chart scenario must match portfolio display scenario')
    return c, root
