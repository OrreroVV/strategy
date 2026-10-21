"""Calendar purge plus label publication and historical feature availability."""
import numpy as np
import pandas as pd
from .point_in_time import utc_timestamp


def eligible_training_rows(frame, origin, feature_names, target_col='y', embargo_months=0,
                           window_months=None, require_availability=False):
    if type(embargo_months) is not int or embargo_months < 0: raise ValueError('Invalid embargo')
    if window_months is not None and (type(window_months) is not int or window_months<=0):
        raise ValueError('Invalid window_months')
    decision = utc_timestamp(origin,require_timezone=False)
    origin_day = decision.tz_localize(None).normalize()
    cutoff = (origin_day.to_period('M')-embargo_months).to_timestamp('M')
    p = frame.copy()
    for col in ['date','label_end']:
        p[col] = pd.to_datetime(p[col],errors='raise',utc=True).dt.tz_localize(None)
    mask = (p.date < origin_day)&(p.label_end < cutoff)&np.isfinite(p[target_col])
    if window_months is not None:
        mask &= p.date >= (origin_day.to_period('M')-window_months).to_timestamp('M')
    columns = ['label_available_at','feature_available_at','decision_at']
    if require_availability and any(c not in p for c in columns):
        raise ValueError('Explicit label/feature availability and decision_at required')
    if any(c in p for c in columns):
        if not all(c in p for c in columns): raise ValueError('Incomplete availability metadata')
        for col in columns:
            if isinstance(p[col].dtype,pd.DatetimeTZDtype):
                p[col] = p[col].dt.tz_convert('UTC')
            else:
                p[col] = pd.to_datetime([utc_timestamp(x,col) if pd.notna(x) else pd.NaT for x in p[col]],utc=True)
        mask &= (p.label_available_at < decision)&(p.feature_available_at <= p.decision_at)
        mask &= (p.feature_available_at < decision)&(p.decision_at < decision)
    mask &= np.isfinite(p[list(feature_names)].to_numpy(dtype=float)).all(axis=1)
    return p.loc[mask].sort_values('date').reset_index(drop=True)
