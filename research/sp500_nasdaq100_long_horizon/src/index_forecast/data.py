"""Local CSV contract, quality diagnostics, causal price-only features and as-of API."""
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd

FEATURES = ['momentum_12m', 'vol_12m']
REQUIRED = ['date', 'index_id', 'total_return_index', 'source', 'source_series_id', 'unit', 'quality_flag']


class DataError(ValueError):
    def __init__(self, message, quality=None):
        super().__init__(message)
        self.quality = quality or {'errors': [message]}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_panel(frame):
    q = {'rows': len(frame), 'errors': [], 'warnings': [], 'series': {}}
    missing = set(REQUIRED)-set(frame.columns)
    if missing:
        raise DataError(f'Missing required fields: {sorted(missing)}', q | {'errors': [f'Missing fields: {sorted(missing)}']})
    p = frame.copy()
    p['date'] = pd.to_datetime(p.date, errors='coerce')
    if p.empty: q['errors'].append('No available data rows')
    if p.date.isna().any(): q['errors'].append('Invalid/missing date')
    if p.duplicated(['index_id','date']).any(): q['errors'].append('Duplicate index/date')
    if set(p.index_id) != {'SPX','NDX'}: q['errors'].append('Both SPX and NDX required; other index IDs prohibited')
    for col in ['source', 'source_series_id', 'quality_flag']:
        if p[col].isna().any() or p[col].astype(str).str.strip().eq('').any():
            q['errors'].append(f'Missing metadata: {col}')
    if not p.unit.eq('index_points').all(): q['errors'].append('Illegal unit; expected index_points')
    for col in ['total_return_index', 'price_index', 'cpi', 'trailing_pe']:
        if col not in p: continue
        raw = p[col]
        p[col] = pd.to_numeric(raw, errors='coerce')
        if (raw.notna() & p[col].isna()).any(): q['errors'].append(f'Non-numeric {col}')
        v = p[col].dropna()
        if ((v <= 0) | ~np.isfinite(v)).any(): q['errors'].append(f'Invalid positive finite level: {col}')
    if p.total_return_index.isna().any():
        q['warnings'].append('Missing total return observations retained; affected targets/features unavailable')
    for col in ['release_date', 'vintage_date']:
        if col in p:
            dates = pd.to_datetime(p[col], errors='coerce')
            if dates.isna().any() or (dates > p.date).any():
                q['errors'].append(f'{col} invalid or later than observation cutoff; use separate as-of table')
    if not p.date.isna().any():
        p['_month'] = p.date.dt.to_period('M')
        if p.duplicated(['index_id','_month']).any(): q['errors'].append('Multiple observations in same index/month')
        # Explicit contract: observation date is calendar month end, after final trading close.
        if not p.date.dt.is_month_end.all(): q['errors'].append('date must be calendar month-end observation date')
        if not p.date.eq(p.date.dt.normalize()).all(): q['errors'].append('date must be date-only; intraday timestamps require normalization')
        sets = []
        for j, g in p.groupby('index_id', sort=True):
            span = pd.period_range(g._month.min(), g._month.max(), freq='M')
            sets.append(set(g.date))
            series = dict(start=str(g.date.min().date()), end=str(g.date.max().date()), rows=len(g),
                          missing_months=len(span)-g._month.nunique(), fields={})
            for col in p.columns:
                if col == '_month': continue
                valid = g.loc[g[col].notna(), 'date']
                series['fields'][col] = dict(missing_rate=float(g[col].isna().mean()),
                    start=str(valid.min().date()) if len(valid) else None,
                    end=str(valid.max().date()) if len(valid) else None)
            q['series'][str(j)] = series
            if series['missing_months']: q['warnings'].append(f'{j}: calendar gaps, no filling')
            moves = g.sort_values('date').total_return_index.pct_change(fill_method=None).abs()
            series['absolute_monthly_move_over_50pct'] = int((moves > .5).sum())
            if (moves > .5).any(): q['warnings'].append(f'{j}: >50% move requires source review; retained')
        common = sorted(set.intersection(*sets)) if sets else []
        q['common_dates'] = dict(count=len(common), start=str(common[0].date()) if common else None,
                                 end=str(common[-1].date()) if common else None)
        q['unmatched_dates_by_index'] = {j: int(len(g)-len(common)) for j,g in p.groupby('index_id')}
        p = p.drop(columns='_month')
    if q['errors']: raise DataError('; '.join(q['errors']), q)
    return p.sort_values(['index_id','date']).reset_index(drop=True), q


def load_csv(csv_path, manifest_path, allow_synthetic=False, mapping=None):
    csv_path, manifest_path = Path(csv_path), Path(manifest_path)
    if not csv_path.is_file() or not manifest_path.is_file():
        raise DataError('Data unavailable: CSV and source manifest required; no synthetic fallback')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    required = ['data_kind','provider','url','retrieved_at','license','currency', 'return_type',
                'dividends_reinvested','point_in_time_verified','sha256','timezone','series']
    if any(k not in manifest for k in required): raise DataError('Incomplete source manifest')
    if manifest['data_kind'] not in ['real','synthetic']: raise DataError('Unknown data_kind')
    synthetic = manifest['data_kind'] == 'synthetic'
    if synthetic and not allow_synthetic: raise DataError('SYNTHETIC_TEST_ONLY blocked by production config')
    if manifest['currency'] != 'USD' or manifest['return_type'] != 'gross_total_return' or manifest['dividends_reinvested'] is not True:
        raise DataError('Require USD gross_total_return with reinvested dividends; no price/ETF substitutions')
    if manifest['point_in_time_verified'] is not True: raise DataError('Point-in-time price history not verified')
    if pd.isna(pd.to_datetime(manifest['retrieved_at'], errors='coerce', utc=True)):
        raise DataError('Invalid acquisition timestamp')
    for field in ['provider','url','license','timezone']:
        if not isinstance(manifest[field],str) or not manifest[field].strip(): raise DataError(f'Missing {field}')
    if manifest['sha256'] != sha256(csv_path): raise DataError('CSV SHA-256 mismatch')
    p = pd.read_csv(csv_path).rename(columns=mapping or {})
    p, quality = validate_panel(p)
    marks = p.quality_flag.eq('SYNTHETIC_TEST_ONLY') | p.source.eq('SYNTHETIC_TEST_ONLY')
    if (synthetic and not marks.all()) or (not synthetic and marks.any()):
        raise DataError('Mixed or mislabeled synthetic/real data')
    for j,g in p.groupby('index_id'):
        meta = manifest['series'].get(j, {})
        if not meta.get('id') or not meta.get('definition'):
            raise DataError(f'Missing verified series definition for {j}')
        if not g.source_series_id.eq(meta['id']).all(): raise DataError(f'Series ID mismatch: {j}')
    quality['data_kind'] = manifest['data_kind']
    quality['sha256'] = manifest['sha256']
    return p, quality, manifest


def features(panel):
    """Calendar-aligned trailing features; no macro/revised/future labels accepted."""
    parts = []
    for j,g in panel.groupby('index_id', sort=True):
        g = g.sort_values('date').set_index('date')
        monthly = pd.date_range(g.index.min(), g.index.max(), freq='ME')
        tr = g.total_return_index.reindex(monthly)
        r = np.log(tr/tr.shift(1))
        f = pd.DataFrame({'momentum_12m': np.log(tr/tr.shift(12)),
                          'vol_12m': r.rolling(12,min_periods=12).std(ddof=1)*np.sqrt(12)},index=monthly)
        # A momentum window crossing a missing observation is conservatively unavailable.
        f.loc[tr.rolling(13,min_periods=13).count() < 13,'momentum_12m'] = np.nan
        f = f.reindex(g.index).reset_index()
        f['index_id'] = j
        parts.append(f)
    return pd.concat(parts,ignore_index=True)


def asof_value(records, cutoff):
    """Latest observation and its latest vintage actually released by cutoff (UTC)."""
    p = records.copy()
    cutoff = pd.to_datetime(cutoff, utc=True)
    for col in ['observation_date','release_date','vintage_date']:
        p[col] = pd.to_datetime(p[col], utc=True, errors='coerce')
        if p[col].isna().any(): raise DataError(f'Missing/invalid {col} in as-of records')
    if p.duplicated(['observation_date','release_date','vintage_date']).any():
        raise DataError('Duplicate/conflicting as-of vintage key')
    p = p[(p.observation_date <= cutoff) & (p.release_date <= cutoff) & (p.vintage_date <= cutoff)]
    if p.empty: return np.nan
    return float(p.sort_values(['observation_date','vintage_date','release_date']).iloc[-1].value)
