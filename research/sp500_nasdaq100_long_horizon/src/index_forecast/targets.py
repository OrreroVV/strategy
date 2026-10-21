"""Derived historical outcomes, never model inputs. Exact calendar-month joins."""
import numpy as np
import pandas as pd


def build_targets(panel, horizons):
    parts = []
    for j,g in panel.groupby('index_id',sort=True):
        g = g.sort_values('date').set_index('date')
        month = g.index.to_period('M')
        for h in horizons:
            if not isinstance(h,int) or h <= 0: raise ValueError('Positive integer month horizon required')
            endpoint = month+h
            def pair(col):
                if col not in g: return np.full(len(g), np.nan), np.full(len(g), np.nan)
                series = pd.Series(g[col].to_numpy(),index=month)
                return series.to_numpy(dtype=float), series.reindex(endpoint).to_numpy(dtype=float)
            start,end = pair('total_return_index')
            y = 12/h*np.log(end/start)
            c0,c1 = pair('cpi')
            pe0,pe1 = pair('trailing_pe')
            parts.append(pd.DataFrame(dict(date=g.index,index_id=j,horizon_months=h,
                label_end=endpoint.to_timestamp('M'), y=y,cagr=np.expm1(y),
                y_real=y-12/h*np.log(c1/c0),delta_log_pe=np.log(pe1/pe0))))
    out = pd.concat(parts,ignore_index=True)
    wide = out.pivot(index=['date','horizon_months'],columns='index_id',values='y')
    rel = (wide.get('NDX', np.nan)-wide.get('SPX', np.nan)).rename('y_relative').reset_index()
    return out.merge(rel,on=['date','horizon_months'],how='left',validate='many_to_one')
