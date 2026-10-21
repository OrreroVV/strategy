import pandas as pd
import pytest
from index_forecast.point_in_time import select_asof, prepare_nominal_dataset
from index_forecast.splits import eligible_training_rows
from index_forecast.feature_registry import feature_set, schema_hash


def observations():
    return pd.DataFrame([
        dict(record_id='initial',index_id='SPX',feature_id='ust_10y',observation_date='2000-01-31',
             release_at='2000-02-03T14:00:00Z',vintage_at='2000-02-03T14:00:00Z',
             available_at='2000-02-03T15:00:00Z',value=.05,unit='ratio',currency='not_applicable',
             definition_id='ust_v1',source_id='SYNTHETIC_TEST_ONLY',source_snapshot_sha256='a'*64,data_kind='synthetic'),
        dict(record_id='revision',index_id='SPX',feature_id='ust_10y',observation_date='2000-01-31',
             release_at='2000-02-03T14:00:00Z',vintage_at='2000-03-03T14:00:00Z',
             available_at='2000-03-03T15:00:00Z',value=.99,unit='ratio',currency='not_applicable',
             definition_id='ust_v1',source_id='SYNTHETIC_TEST_ONLY',source_snapshot_sha256='b'*64,data_kind='synthetic')])


def test_pit_release_vintage_and_vendor_delay():
    p = observations()
    spec = dict(unit='ratio',currency='not_applicable',definition_id='ust_v1')
    assert select_asof(p,'SPX','ust_10y','2000-02-03T14:30:00Z',spec) is None
    assert select_asof(p,'SPX','ust_10y','2000-02-28T00:00:00Z',spec)['record_id']=='initial'
    assert select_asof(p,'SPX','ust_10y','2000-03-04T00:00:00Z',spec)['value']==.99


@pytest.mark.parametrize('column,value', [('unit','percent'),('definition_id','other'),
    ('available_at','2000-02-03T12:00:00Z'),('release_at','2000-02-03'),
    ('source_snapshot_sha256','not-a-hash')])
def test_pit_rejects_bad_metadata(column,value):
    p = observations()
    p.loc[0,column]=value
    with pytest.raises(ValueError):
        select_asof(p,'SPX','ust_10y','2000-04-01T00:00:00Z',dict(unit='ratio',currency='not_applicable',definition_id='ust_v1'))


def test_pit_duplicate_and_mixed_data_rejected():
    p = observations()
    spec = dict(unit='ratio',currency='not_applicable',definition_id='ust_v1')
    with pytest.raises(ValueError):select_asof(pd.concat([p,p.iloc[:1]]),'SPX','ust_10y','2001-01-01T00:00:00Z',spec)
    p.loc[1,'data_kind']='real'
    with pytest.raises(ValueError):select_asof(p,'SPX','ust_10y','2001-01-01T00:00:00Z',spec)


def test_late_label_release_excluded():
    p = pd.DataFrame(dict(date=pd.to_datetime(['1990-01-31','1990-02-28']),
        label_end=pd.to_datetime(['1993-01-31','1993-02-28']),
        label_available_at=['2000-02-01T00:00:00Z','1993-03-01T00:00:00Z'],
        feature_available_at=['1990-01-31T00:00:00Z','1990-02-28T00:00:00Z'],
        decision_at=['1990-01-31T23:00:00Z','1990-02-28T23:00:00Z'],y=[1.,2.],x=[1.,2.]))
    out=eligible_training_rows(p,'2000-01-31T23:59:59Z',['x'],require_availability=True)
    assert out.y.tolist()==[2.]


def test_real_nominal_requires_explicit_timestamps(panel):
    with pytest.raises(ValueError,match='timestamp'):
        prepare_nominal_dataset(panel,[36],'real')


def test_registered_features_and_synthetic_clock(panel):
    assert feature_set('absolute_v1')==('momentum_12m','vol_12m')
    assert len(schema_hash('relative_v1'))==64
    with pytest.raises(ValueError): feature_set('y_relative')
    ds=prepare_nominal_dataset(panel,[36],'synthetic')
    assert set(ds.clock_policy)=={'synthetic_month_end_235959_utc'}
    assert ds.label_available_at.notna().sum()==(480-36)*2


def test_delayed_feature_not_used_as_historical_feature(panel):
    p=panel.copy()
    p['decision_at']=p.date.dt.strftime('%Y-%m-%dT23:59:59Z')
    p['tr_available_at']=p.date.dt.strftime('%Y-%m-%dT22:00:00Z')
    p.loc[(p.index_id=='SPX') & (p.date==pd.Timestamp('1990-01-31')),'tr_available_at']='2001-01-01T00:00:00Z'
    ds=prepare_nominal_dataset(p,[36],'synthetic')
    spx=ds[ds.index_id=='SPX']
    train=eligible_training_rows(spx,'2000-01-31T23:59:59Z',feature_set('absolute_v1'),require_availability=True)
    assert not train.date.between('1990-01-31','1991-01-31').any()
