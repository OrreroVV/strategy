import json
import pytest
from index_forecast.prediction_ledger import PredictionLedger


def record():
    return dict(forecast_date='2000-01-31',decision_at='2000-01-31T23:59:59Z',index_id='REL',
        target_id='relative_log_return',target_unit='annualized_log_return_difference',
        horizon_months=36,model_name='ridge',prediction_path='direct',predicted_log_annual_return=.03,
        training_start='1980-01-31',training_end='1996-12-31',
        max_training_label_end='1999-12-31',max_training_label_available_at='1999-12-31T23:59:59Z',
        max_training_feature_available_at='1996-12-31T23:59:59Z',
        current_feature_available_at='2000-01-31T23:00:00Z',feature_schema_hash='a'*64,
        protocol_hash='b'*64,input_sha256='c'*64,output_type='historical_oos')


def test_ledger_append_only_duplicate_and_reopen(tmp_path):
    path=tmp_path/'predictions.jsonl'
    ledger=PredictionLedger(path,'test_run','synthetic')
    entry=ledger.append(record())
    assert entry['data_kind']=='synthetic' and entry['prediction_id']
    assert json.loads(path.read_text())['prediction_id']==entry['prediction_id']
    with pytest.raises(ValueError,match='Duplicate'): ledger.append(record())
    with pytest.raises(ValueError,match='Duplicate'):
        ledger.append(record()|{'decision_at':'2000-02-01T07:59:59+08:00'})
    with pytest.raises(FileExistsError): PredictionLedger(path,'test_run','synthetic')


@pytest.mark.parametrize('field,value', [('max_training_label_available_at','2000-02-01T00:00:00Z'),
    ('max_training_label_end','2000-01-31'),('current_feature_available_at','2000-02-01T00:00:00Z'),
    ('predicted_log_annual_return',float('nan')),('actual_log_annual_return',.1),('feature_schema_hash','bad'),
    ('actual_relative_return',.1),('forecast_date','1999-12-31')])
def test_ledger_rejects_leakage(tmp_path,field,value):
    ledger=PredictionLedger(tmp_path/'predictions.jsonl','test_run','synthetic')
    with pytest.raises(ValueError):ledger.append(record()|{field:value})
