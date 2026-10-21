"""Opt-in P1 development modules. Existing P0/P1 base forecasts stay untouched."""
import hashlib
import json
import numpy as np
import pandas as pd
from .backtest import evaluate
from .uncertainty import validate_predictions, calibrate_intervals, interval_metrics
from .models.ensemble import build_ensembles
from .models.valuation import valuation_forecast
from .reporting import md_table


def valuation_provenance_status(manifest):
    if manifest['data_kind']=='synthetic':return 'verified_for_synthetic_test_only'
    if manifest.get('valuation_fields_verified') is not True:return 'unverified_field_provenance'
    specs=manifest.get('valuation_fields',{})
    for field,unit,currency in [('trailing_pe','multiple','not_applicable'),
                                ('eps_ttm','USD_per_index_share','USD'),
                                ('dividend_yield','ratio','not_applicable')]:
        meta=specs.get(field,{})
        if (meta.get('unit')!=unit or meta.get('currency')!=currency or meta.get('point_in_time_verified') is not True
            or any(not isinstance(meta.get(key),str) or not meta[key].strip() for key in ['provider','url','definition_id'])):
            return 'unverified_field_provenance'
    return 'verified_by_supplied_manifest_not_independent_audit'


def extended_base(absolute,relative,ds):
    clocks=ds[['date','index_id','horizon_months','decision_at','label_available_at']]
    absolute=absolute.merge(clocks,left_on=['forecast_date','index_id','horizon_months'],
        right_on=['date','index_id','horizon_months'],validate='many_to_one').drop(columns='date')
    absolute['target_id']='nominal_log_return';absolute['target_unit']='annualized_log_return'
    absolute['prediction_path']='absolute';absolute['selection_version']='fixed_absolute_v1'
    frames=[absolute]
    if relative is not None and not relative.empty:
        r=relative.copy()
        r['selection_version']='fixed_relative_v1'
        if 'label_available_at' not in r:
            paired=ds.groupby(['date','horizon_months']).label_available_at.max().reset_index()
            r=r.merge(paired,left_on=['forecast_date','horizon_months'],right_on=['date','horizon_months'],validate='many_to_one').drop(columns='date')
        frames.append(r)
    return validate_predictions(pd.concat(frames,ignore_index=True))


def save_extensions(panel,ds,absolute,relative,config,manifest,metadata,out,write_json):
    settings=config['extensions']
    base=extended_base(absolute,relative,ds)
    protocol=dict(settings=settings,validation=config['validation'],models=config['models'],
        phase='development_prequential',source_protocol_hash=metadata.get('relative_protocol_hash'),
        input_sha256=manifest['sha256'],version='p1_extensions_v1')
    protocol_hash=hashlib.sha256(json.dumps(protocol,sort_keys=True,default=str).encode()).hexdigest()
    write_json(out/'extensions_protocol.json',protocol|{'protocol_hash':protocol_hash})
    def save(frame,name):
        frame=frame.copy()
        frame['run_id']=metadata['run_id'];frame['data_kind']=manifest['data_kind']
        frame['input_sha256']=manifest['sha256'];frame['extensions_protocol_hash']=protocol_hash
        frame.to_csv(out/name,index=False)
    save(base,'extended_base_predictions.csv')
    ensemble,audits=build_ensembles(base,config['models']['names'],settings['ensemble'])
    for row in audits:row.update(run_id=metadata['run_id'],data_kind=manifest['data_kind'],extensions_protocol_hash=protocol_hash)
    write_json(out/'ensemble_audit.json',audits)
    save(ensemble,'ensemble_forecasts.csv')
    combined=pd.concat([base,ensemble],ignore_index=True)
    metrics=[]
    for (target,path),g in combined.groupby(['target_id','prediction_path']):
        m=evaluate(g[g.predicted_log_annual_return.notna()])
        m['target_id']=target;m['prediction_path']=path;metrics.append(m)
    metrics=pd.concat(metrics,ignore_index=True) if metrics else pd.DataFrame()
    save(metrics,'extensions_metrics.csv')
    intervals,interval_audit=calibrate_intervals(combined,settings['intervals'])
    save(intervals,'prediction_intervals.csv')
    coverage=interval_metrics(intervals)
    save(coverage,'interval_metrics.csv')
    for row in interval_audit:row.update(run_id=metadata['run_id'],data_kind=manifest['data_kind'],extensions_protocol_hash=protocol_hash)
    write_json(out/'calibration_audit.json',interval_audit)
    diagnostics=[];valuation_records=[]
    holdout=pd.Timestamp(config['validation']['holdout_start'])
    valuation_settings=settings['valuation']
    for _,row in ds[ds.date>=holdout].sort_values(['index_id','horizon_months','date']).iterrows():
        if (row.date.to_period('M').ordinal-holdout.to_period('M').ordinal)%config['validation']['step_months']:continue
        header=dict(forecast_date=row.date,index_id=row.index_id,horizon_months=int(row.horizon_months))
        if pd.isna(row.y):result=dict(status='unmatured_or_missing_label')
        elif valuation_provenance_status(manifest)=='unverified_field_provenance':
            result=dict(status='unverified_field_provenance')
        else:
            result=valuation_forecast(panel[panel.index_id==row.index_id],row.decision_at,int(row.horizon_months),**valuation_settings)
            if result['status']=='available' and manifest['data_kind']=='real':
                specs=manifest['valuation_fields']
                if (result['pe_definition_id']!=specs['trailing_pe']['definition_id'] or
                    result['eps_definition_id']!=specs['eps_ttm']['definition_id']):
                    result=dict(status='manifest_definition_mismatch')
        diagnostics.append(header|result)
        if result['status']=='available':
            valuation_records.append(header|result|dict(actual_log_annual_return=float(row.y),
                error=result['predicted_log_annual_return']-float(row.y),output_type='historical_oos',evidence_grade='D'))
    diagnostics=pd.DataFrame(diagnostics)
    valuation=pd.DataFrame(valuation_records) if valuation_records else pd.DataFrame(columns=
        ['forecast_date','index_id','horizon_months','status','predicted_log_annual_return','actual_log_annual_return','error'])
    save(diagnostics,'valuation_diagnostics.csv');save(valuation,'valuation_forecasts.csv')
    metadata['extensions_status']='completed_with_explicit_availability_statuses'
    metadata['extensions_protocol_hash']=protocol_hash
    metadata['ensemble_rows']=len(ensemble);metadata['valuation_forecast_rows']=len(valuation)
    status_counts=ensemble.groupby(['model_name','ensemble_status']).size().rename('count').reset_index()
    interval_counts=intervals.groupby(['interval_status_80','interval_status_95']).size().rename('count').reset_index()
    valuation_counts=diagnostics.groupby('status').size().rename('count').reset_index() if not diagnostics.empty else pd.DataFrame()
    text=f'''# P1估值、区间与集成工程报告

**{'SYNTHETIC_TEST_ONLY：合成工程验证；真实行情覆盖0' if manifest['data_kind']=='synthetic' else '真实历史研究；来源、版本与许可仍须独立核验'}**

运行：{metadata['run_id']}。阶段固定development_prequential；不是冻结的最终测试，也没有当前市场预测。
保留全部原基准与双路径结果，新增集成{len(ensemble)}条、区间状态记录{len(intervals)}条、可计算估值预测{len(valuation)}条。

## 集成与回退

{md_table(status_counts)}

等权、非负权重及向历史均值收缩三种方法全部保留。候选包含历史均值与三线性模型。
权重仅使用当时已成熟的历史基模型OOS预测；eta={settings['ensemble']['eta']}为预先固定研究参数。
rho仅比较历史当时产生、现在已成熟的加权集成预测与基准，不把当前拟合权重套回过去当作OOS。
加权/收缩至少{settings['ensemble']['min_history']}条历史记录和{settings['ensemble']['min_disjoint']}个非重叠结果区间；不足分别显式回退等权/历史均值。
回退不代表优化集成得到增益；遗漏候选时不按剩余模型重新归一化。
共同样本误差见extensions_metrics.csv，逐期权重与历史截止见ensemble_audit.json。

## 经验预测区间

{md_table(interval_counts)}

校准仅用同模型/目标/期限/路径/选择版本的已成熟OOS误差分位数，实际标签可得时间必须早于决策。
80%门槛{settings['intervals']['min_residuals_80']}条/{settings['intervals']['min_disjoint_80']}个非重叠区间；95%门槛{settings['intervals']['min_residuals_95']}条/{settings['intervals']['min_disjoint_95']}个。
不足时区间留空，不降低门槛填表。log区间与CAGR/相对财富比区间分列，非有限转换单独标记。
经验区间不保证名义覆盖；没有把模型分歧或均值置信区间当单次收益预测区间。
覆盖率、可用率、宽度在interval_metrics.csv报告，保留所有预测作为可用率分母。

## 估值与收益分解

{md_table(valuation_counts)}

近似公式：log1p(DY)+历史EPS年化对数增长+(终端logPE-当前logPE)/(H/12)。
lambda={valuation_settings['lambda_value']}预先固定，未调参验证；lambda=1表示无估值变化基线。
PE参考仅取当时已知历史中位数，EPS使用精确日历端点；负EPS、定义变化、缺字段/时间戳均明确不可用。
现有合成主样本没有完整EPS、股息及估值时钟，不能据此补造分解结果；公式成功路径另由明确合成单元测试验证。

## 限制与复现

全部证据D。7/10年证据与区间估计证据有限；未实现HAC、区块自助、估值参数内层选择、最终冻结审计或真实产品交易。
{'本次另启用月度指数代理策略模拟，见strategy_report.md；不属于可执行产品实盘回测。' if config.get('portfolio',{}).get('enabled',False) else '本次未启用策略模块。'}
加权与rho选择属于预先声明的开发期在线更新，只使用过去已成熟结果，不能称为完全未触及的最终测试。
原始CSV未覆盖，来源/配置/源码/协议均保存快照或哈希，协议哈希{protocol_hash}。
复现：python -m index_forecast.cli backtest --config {metadata['config_path']}。
测试日志与交付说明见docs/p1_extensions_delivery.md，运行环境见run_metadata.json。
'''
    (out/'extensions_report.md').write_text(text,encoding='utf-8')
    return intervals
