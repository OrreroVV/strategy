"""Field-level as-of records and explicit nominal-return availability clocks."""
import re
import numpy as np
import pandas as pd
from .data import DataError, features
from .targets import build_targets


def utc_timestamp(value, field='timestamp', require_timezone=True):
    try:
        ts = pd.Timestamp(value)
    except (ValueError, TypeError) as exc:
        raise DataError(f'Invalid {field}: {value}') from exc
    if pd.isna(ts) or (require_timezone and ts.tzinfo is None):
        raise DataError(f'{field} requires an explicit timezone timestamp')
    return ts.tz_localize('UTC') if ts.tzinfo is None else ts.tz_convert('UTC')


def select_asof(records, index_id, feature_id, decision_at, specification):
    """Return a provenance-bearing raw record, or None. External features remain opt-in."""
    required = ['record_id','index_id','feature_id','observation_date','release_at','vintage_at',
                'available_at','value','unit','currency','definition_id','source_id',
                'source_snapshot_sha256','data_kind']
    missing = set(required)-set(records.columns)
    if missing: raise DataError(f'Missing field-level provenance columns: {sorted(missing)}')
    p = records.copy()
    if p.empty: return None
    for col in required:
        if p[col].isna().any(): raise DataError(f'Missing as-of metadata/value: {col}')
    if p.record_id.duplicated().any(): raise DataError('Duplicate record_id')
    if p.data_kind.nunique() != 1 or not p.data_kind.isin(['real','synthetic']).all():
        raise DataError('Mixed or invalid source data_kind')
    if not p.source_snapshot_sha256.astype(str).map(lambda x: bool(re.fullmatch('[0-9a-f]{64}',x))).all():
        raise DataError('Invalid source snapshot SHA-256')
    for col in ['record_id','index_id','feature_id','unit','currency','definition_id','source_id']:
        if p[col].astype(str).str.strip().eq('').any(): raise DataError(f'Empty {col}')
    p['value'] = pd.to_numeric(p.value,errors='coerce')
    if not np.isfinite(p.value).all(): raise DataError('Nonfinite as-of value')
    for col in ['release_at','vintage_at','available_at']:
        p[col] = pd.to_datetime([utc_timestamp(x,col) for x in p[col]],utc=True)
    p['observation_date'] = pd.to_datetime(p.observation_date,errors='coerce',utc=True)
    if p.observation_date.isna().any(): raise DataError('Invalid observation_date')
    earliest = p[['release_at','vintage_at']].max(axis=1)
    if (p.available_at < earliest).any(): raise DataError('available_at precedes release/vintage')
    if p.duplicated(['index_id','feature_id','observation_date','release_at','vintage_at']).any():
        raise DataError('Conflicting as-of vintage key')
    p = p[(p.index_id==index_id) & (p.feature_id==feature_id)]
    for col in ['unit','currency','definition_id']:
        if col not in specification or not p[col].eq(specification[col]).all():
            raise DataError(f'Field definition mismatch: {col}')
    cutoff = utc_timestamp(decision_at,'decision_at')
    p = p[(p.available_at<=cutoff)&(p.observation_date<=cutoff)]
    if p.empty: return None
    return p.sort_values(['observation_date','vintage_at','release_at']).iloc[-1].to_dict()


def prepare_nominal_dataset(panel, horizons, data_kind):
    """Price-only data. Real records must declare actual decision and TR availability."""
    if data_kind not in ['real','synthetic']: raise DataError('Invalid dataset data_kind')
    p = panel.copy()
    have_clock = [col in p for col in ['decision_at','tr_available_at']]
    if not all(have_clock):
        if data_kind != 'synthetic' or any(have_clock):
            raise DataError('Explicit decision_at/tr_available_at timestamps required for real/P1 input')
        p['decision_at'] = pd.to_datetime(p.date,utc=True)+pd.Timedelta(hours=23,minutes=59,seconds=59)
        p['tr_available_at'] = p.decision_at
        clock_policy = 'synthetic_month_end_235959_utc'
    else:
        for col in ['decision_at','tr_available_at']:
            p[col] = pd.to_datetime([utc_timestamp(x,col) for x in p[col]],utc=True)
        clock_policy = 'explicit_source_timestamps'
    p['date'] = pd.to_datetime(p.date)
    if data_kind=='real' and ('quality_flag' in p and p.quality_flag.eq('SYNTHETIC_TEST_ONLY').any()
                             or 'source' in p and p.source.eq('SYNTHETIC_TEST_ONLY').any()):
        raise DataError('Synthetic source cannot be marked real')
    if p.duplicated(['date','index_id']).any(): raise DataError('Duplicate nominal input key')
    decision_dates = p.decision_at.dt.tz_convert('UTC').dt.tz_localize(None).dt.normalize()
    if not decision_dates.eq(p.date).all():
        raise DataError('P1 nominal decision_at must fall on its UTC calendar month-end date')
    if (p.groupby('date').decision_at.nunique() > 1).any():
        raise DataError('Two indices require the same decision_at for each monthly cohort')
    availability = []
    for j,g in p.groupby('index_id',sort=True):
        g = g.sort_values('date').set_index('date')
        months = pd.date_range(g.index.min(),g.index.max(),freq='ME')
        times = g.tr_available_at.reindex(months)
        # All 13 observations feed both price-derived features; retain delayed-source timing.
        window = pd.concat([times.shift(k) for k in range(13)],axis=1)
        latest = window.max(axis=1)
        latest = latest.where(window.notna().all(axis=1))
        for h in horizons:
            lookup = pd.Series(g.tr_available_at.to_numpy(),index=g.index.to_period('M'))
            future = lookup.reindex(g.index.to_period('M')+h)
            future.index = g.index
            label_time = pd.concat([g.tr_available_at,future],axis=1).max(axis=1)
            label_time = label_time.where(future.notna() & g.total_return_index.notna())
            availability.append(pd.DataFrame(dict(date=g.index,index_id=j,horizon_months=h,
                decision_at=g.decision_at.to_numpy(),feature_available_at=latest.reindex(g.index).to_numpy(),
                label_available_at=label_time.to_numpy())))
    ds = features(p).merge(build_targets(p,horizons),on=['date','index_id'],validate='one_to_many')
    ds = ds.merge(pd.concat(availability,ignore_index=True),on=['date','index_id','horizon_months'],validate='one_to_one')
    ds.loc[ds.y.isna(),'label_available_at'] = pd.NaT
    ds['clock_policy'] = clock_policy
    ds['data_kind'] = data_kind
    ds['target_id'] = 'nominal_log_return'
    return ds
