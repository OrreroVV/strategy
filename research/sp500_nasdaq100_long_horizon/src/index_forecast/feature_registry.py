"""Versioned, closed feature schemas; CSV column names never register themselves."""
import hashlib
import json
from types import MappingProxyType

FEATURE_SETS = MappingProxyType({
    'absolute_v1': ('momentum_12m', 'vol_12m'),
    'relative_v1': ('momentum_12m_difference', 'vol_12m_difference'),
})
DEFINITIONS = MappingProxyType({
    'momentum_12m': 'ln(TR[t]/TR[t-12]); complete 13-month trailing window; include latest month',
    'vol_12m': 'std(last 12 monthly log returns,ddof=1)*sqrt(12)',
    'momentum_12m_difference': 'NDX momentum_12m minus SPX momentum_12m; common dates',
    'vol_12m_difference': 'NDX vol_12m minus SPX vol_12m; common dates',
})


def feature_set(name):
    if name not in FEATURE_SETS:
        raise ValueError(f'Unregistered feature set: {name}')
    return FEATURE_SETS[name]


def schema_hash(name):
    content = dict(version=name, features=[dict(name=f, definition=DEFINITIONS[f]) for f in feature_set(name)])
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
