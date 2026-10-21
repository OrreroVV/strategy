"""Append-only simulated decision records. Realized targets never enter signal records."""
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from .point_in_time import utc_timestamp


class PredictionLedger:
    def __init__(self,path,run_id,data_kind):
        if data_kind not in ['real','synthetic']: raise ValueError('Invalid ledger data_kind')
        self.path = Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.path.open('x',encoding='utf-8'): pass
        self.run_id, self.data_kind, self.ids = run_id, data_kind, set()

    def append(self,record):
        p = dict(record)
        required = ['forecast_date','decision_at','index_id','target_id','target_unit','horizon_months',
                    'model_name','prediction_path','predicted_log_annual_return','training_start','training_end',
                    'max_training_label_end','max_training_label_available_at',
                    'max_training_feature_available_at','current_feature_available_at',
                    'feature_schema_hash','protocol_hash','input_sha256','output_type']
        if set(required)-p.keys(): raise ValueError('Incomplete prediction audit record')
        if set(p)&{'y','y_relative','actual_log_annual_return','actual_cagr','error'}:
            raise ValueError('Realized target/error forbidden in prediction ledger')
        if set(p)-set(required): raise ValueError('Unregistered prediction ledger fields')
        if not math.isfinite(p['predicted_log_annual_return']): raise ValueError('Nonfinite prediction')
        if type(p['horizon_months']) is not int or p['horizon_months']<=0: raise ValueError('Invalid horizon')
        for key in ['feature_schema_hash','protocol_hash','input_sha256']:
            if not re.fullmatch('[0-9a-f]{64}',p[key]): raise ValueError(f'Invalid {key}')
        decision = utc_timestamp(p['decision_at'])
        forecast = utc_timestamp(p['forecast_date'],require_timezone=False)
        if not forecast.is_month_end or forecast.normalize()!=decision.normalize():
            raise ValueError('Forecast date and decision UTC date must match at month-end')
        for key in ['max_training_label_available_at','max_training_feature_available_at']:
            if utc_timestamp(p[key])>=decision: raise ValueError(f'Leakage: {key}')
        # Calendar equality is excluded even though decision_at is after that day's close.
        day = decision.normalize()
        for key in ['training_start','training_end','max_training_label_end']:
            if utc_timestamp(p[key],require_timezone=False)>=day: raise ValueError(f'Leakage: {key}')
        if utc_timestamp(p['training_start'],require_timezone=False)>utc_timestamp(p['training_end'],require_timezone=False):
            raise ValueError('Inverted training window')
        if utc_timestamp(p['current_feature_available_at'])>decision: raise ValueError('Future forecast feature')
        keys = ['forecast_date','decision_at','index_id','target_id','horizon_months','model_name','prediction_path']
        identity = dict(run_id=self.run_id,**{k:str(p[k]) for k in keys})
        identity['decision_at'] = decision.isoformat()
        identity['forecast_date'] = utc_timestamp(p['forecast_date'],require_timezone=False).normalize().isoformat()
        prediction_id = hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
        if prediction_id in self.ids: raise ValueError('Duplicate prediction identity')
        p.update(prediction_id=prediction_id,run_id=self.run_id,data_kind=self.data_kind,
                 recorded_at=datetime.now(timezone.utc).isoformat())
        line = json.dumps(p,ensure_ascii=False,default=str,allow_nan=False)
        with self.path.open('a',encoding='utf-8') as stream:
            stream.write(line+'\n')
        self.ids.add(prediction_id)
        return p
