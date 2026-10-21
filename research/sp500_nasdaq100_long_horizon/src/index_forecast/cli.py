"""Offline research commands. Every run is immutable and separately identified."""
import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
import platform
from pathlib import Path
import sys
import time
import uuid
import zipfile
import hashlib
import numpy as np
import pandas as pd
import yaml
from .config import load_config
from .data import load_csv, features, sha256, DataError
from .targets import build_targets
from .backtest import run_backtest, evaluate
from .reporting import report, quality_markdown
from .point_in_time import prepare_nominal_dataset
from .models.relative import run_relative_backtest, evaluate_relative
from .prediction_ledger import PredictionLedger
from .feature_registry import schema_hash


def write_json(path, obj):
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str,allow_nan=False),encoding='utf-8')


def sample(root, seed):
    """Deliberately artificial fixture. Not an empirical sample or return forecast."""
    folder = root/'data'/'sample'
    folder.mkdir(parents=True,exist_ok=True)
    csv = folder/'SYNTHETIC_TEST_ONLY.csv'
    manifest = folder/'manifest.json'
    if csv.exists() or manifest.exists(): raise ValueError('Sample already exists; refusing overwrite')
    rng = np.random.default_rng(seed)
    dates = pd.date_range('1980-01-31', '2025-12-31',freq='ME')
    blocks = []
    common = rng.normal(0,.025,len(dates))
    for j,drift in [('SPX',.004),('NDX',.006)]:
        returns = drift+common+rng.normal(0,.012,len(dates))
        blocks.append(pd.DataFrame(dict(date=dates,index_id=j,total_return_index=100*np.exp(np.cumsum(returns)),
            cpi=100*np.exp(np.arange(len(dates))*.002),trailing_pe=20+2*np.sin(np.arange(len(dates))/24),
            source='SYNTHETIC_TEST_ONLY',source_series_id=f'SYNTHETIC_{j}',
            unit='index_points',quality_flag='SYNTHETIC_TEST_ONLY')))
    pd.concat(blocks,ignore_index=True).to_csv(csv,index=False,mode='x')
    write_json(manifest,dict(data_kind='synthetic',provider='SYNTHETIC_TEST_ONLY',
        url='local:deterministic synthetic generator; no market source',
        retrieved_at=datetime.now(timezone.utc).isoformat(),license='Synthetic fixture generated for testing only',
        currency='USD',return_type='gross_total_return',dividends_reinvested=True,point_in_time_verified=True,
        timezone='UTC',seed=seed,sha256=sha256(csv),
        series={j:dict(id=f'SYNTHETIC_{j}',definition='Artificial exponential random walk, not market data') for j in ['SPX','NDX']}))
    return csv


def summarize(ds):
    rows = []
    latest = ds.date.max()
    for (j,h),g in ds.groupby(['index_id','horizon_months']):
        rows.append(dict(index_id=j,horizon_months=int(h),observations=len(g),
            nominal_labels=int(g.y.notna().sum()),missing_nominal_labels=int(g.y.isna().sum()),
            matured_strictly_before_latest=int((g.y.notna() & (g.label_end < latest)).sum()),
            real_labels=int(g.y_real.notna().sum()),valuation_labels=int(g.delta_log_pe.notna().sum()),
            relative_labels=int(g.y_relative.notna().sum())))
    return pd.DataFrame(rows)


def execute(command, config_path):
    started = time.perf_counter()
    config, root = load_config(config_path)
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'_'+uuid.uuid4().hex[:8]
    out = (root/config['reporting']['output_dir']/run_id).resolve()
    # Results must stay in the research project even when config is edited.
    if not out.is_relative_to(root): raise ValueError('output_dir must remain inside research project')
    out.mkdir(parents=True,exist_ok=False)
    (out/'config_snapshot.yaml').write_text(yaml.safe_dump(config,allow_unicode=True),encoding='utf-8')
    source_root = Path(__file__).resolve().parents[2]
    code_files = sorted((source_root/'src').rglob('*.py'))
    with zipfile.ZipFile(out/'source_snapshot.zip','x',compression=zipfile.ZIP_DEFLATED) as archive:
        for path in (code_files + sorted((source_root/'tests').glob('*.py')) + [source_root/'pyproject.toml']
                     + sorted((source_root/'docs').glob('*.md')) + sorted((source_root/'docs').glob('*.yaml'))):
            archive.write(path,path.relative_to(source_root))
    metadata = dict(run_id=run_id,command=command,status='started',config_path=str(Path(config_path)),
        started_at=datetime.now(timezone.utc).isoformat(),python=sys.version,platform=platform.platform(),
        code_version='workspace_not_a_git_repository',
        code_sha256={str(p.relative_to(source_root)):sha256(p) for p in code_files},
        versions={k:importlib.metadata.version(k) for k in ['numpy','pandas','scipy','scikit-learn','matplotlib','PyYAML']},
        seed=config['project']['seed'])
    try:
        dc = config['data']
        p,q,manifest = load_csv(root/dc['csv'],root/dc['manifest'],dc['allow_synthetic'],dc.get('column_mapping'))
        write_json(out/'source_manifest.json',manifest)
        write_json(out/'data_quality.json',q)
        (out/'data_quality_report.md').write_text(quality_markdown(q),encoding='utf-8')
        metadata['data_kind'] = manifest['data_kind']
        metadata['input_sha256'] = manifest['sha256']
        relative_enabled = config.get('relative',{}).get('enabled',False)
        extensions_enabled = config.get('extensions',{}).get('enabled',False)
        portfolio_enabled = config.get('portfolio',{}).get('enabled',False)
        prepared_nominal = (prepare_nominal_dataset(p,config['targets']['horizons'],manifest['data_kind'])
                            if relative_enabled or extensions_enabled else None)
        if relative_enabled or extensions_enabled:
            metadata['clock_policy'] = prepared_nominal.clock_policy.iloc[0]
        if portfolio_enabled:
            from .strategy_reporting import prepare_proxy_prices
            prepare_proxy_prices(p,config['portfolio'],manifest['data_kind'])
        if command == 'validate-data':
            metadata['status'] = 'validated'
        else:
            if relative_enabled or extensions_enabled:
                ds = prepared_nominal
            else:
                ds = features(p).merge(build_targets(p,config['targets']['horizons']),on=['date','index_id'],validate='one_to_many')
            ds['data_kind'] = manifest['data_kind']
            ds['run_id'] = run_id
            ds.to_csv(out/'dataset.csv',index=False)
            summary = summarize(ds)
            summary['data_kind'] = manifest['data_kind']
            summary['run_id'] = run_id
            summary.to_csv(out/'target_summary.csv',index=False)
            if command == 'build-dataset':
                metadata['status'] = 'dataset_built'
            else:
                forecasts,audits,skips = run_backtest(ds,config['validation'],config['models'])
                forecasts['run_id'] = run_id
                forecasts['data_kind'] = manifest['data_kind']
                metrics = evaluate(forecasts)
                metrics['data_kind'] = manifest['data_kind']
                metrics['run_id'] = run_id
                for audit in audits:
                    audit['data_kind'] = manifest['data_kind']
                    audit['run_id'] = run_id
                forecasts.to_csv(out/'forecasts.csv',index=False)
                metrics.to_csv(out/'backtest_metrics.csv',index=False)
                skips.to_csv(out/'skipped_origins.csv',index=False)
                write_json(out/'model_parameters.json',audits)
                relative_forecasts = None
                if relative_enabled:
                    relative_forecasts = _save_relative_run(ds,config,manifest,metadata,out,source_root)
                if extensions_enabled:
                    from .extensions import save_extensions
                    interval_predictions=save_extensions(p,ds,forecasts,relative_forecasts,config,manifest,metadata,out,write_json)
                portfolio_ledger=None
                if portfolio_enabled:
                    from .strategy_reporting import save_portfolio_run
                    portfolio_ledger,_=save_portfolio_run(p,interval_predictions,config,manifest,metadata,out,write_json)
                if config.get('plots',{}).get('enabled',False):
                    from .plots import render_research_figures
                    interval_stats=pd.read_csv(out/'interval_metrics.csv') if extensions_enabled else None
                    charts=render_research_figures(out,p,ds,forecasts,relative_forecasts,interval_stats,portfolio_ledger,
                        config['plots'],manifest,run_id,write_json)
                    metadata['rendered_figures']=sum(entry['status']=='rendered' for entry in charts)
                metadata['status'] = 'backtest_completed' if not forecasts.empty else 'no_eligible_oos_origins'
                (out/'report.md').write_text(report(config,q,manifest,summary,metrics,forecasts,skips,metadata),encoding='utf-8')
                if forecasts.empty: raise DataError('No eligible OOS origins; see target_summary and skipped_origins')
    except Exception as exc:
        metadata['status'] = 'failed'
        metadata['error'] = f'{type(exc).__name__}: {exc}'
        if isinstance(exc,DataError) and not (out/'data_quality.json').exists():
            write_json(out/'data_quality.json',exc.quality)
            (out/'data_quality_report.md').write_text(quality_markdown(exc.quality),encoding='utf-8')
        (out/'failure.md').write_text('# 运行未成功\n\n'+metadata['error']+'\n\n未生成真实市场预测。',encoding='utf-8')
        raise
    finally:
        metadata['elapsed_seconds'] = time.perf_counter()-started
        metadata['finished_at'] = datetime.now(timezone.utc).isoformat()
        write_json(out/'run_metadata.json',metadata)
        (out/'run.log').write_text(json.dumps(metadata,ensure_ascii=False,default=str)+'\n',encoding='utf-8')
        print(f'{metadata["status"]}: {out}')
    return out


def _save_relative_run(ds,config,manifest,metadata,out,source_root):
    forecasts,audits,coverage = run_relative_backtest(ds,config['validation'],config['models'])
    metrics,comparison = evaluate_relative(forecasts)
    protocol_path = source_root/'docs'/'validation_protocol.md'
    protocol_text = protocol_path.read_text(encoding='utf-8')
    protocol_object = dict(config=config,validation_protocol_sha256=sha256(protocol_path),
        absolute_schema_hash=schema_hash('absolute_v1'),relative_schema_hash=schema_hash('relative_v1'),
        selection='fixed_parameters_no_tuning',cohort='paired_common_training_and_forecast_dates')
    protocol_hash = hashlib.sha256(json.dumps(protocol_object,sort_keys=True,default=str).encode()).hexdigest()
    metadata['relative_protocol_hash'] = protocol_hash
    (out/'validation_protocol_snapshot.md').write_text(protocol_text,encoding='utf-8')
    write_json(out/'relative_protocol.json',protocol_object|{'protocol_hash':protocol_hash})
    ledger = PredictionLedger(out/'prediction_ledger.jsonl',metadata['run_id'],manifest['data_kind'])
    ledger_fields = ['forecast_date','decision_at','index_id','target_id','target_unit','horizon_months','model_name',
        'prediction_path','predicted_log_annual_return','training_start','training_end','max_training_label_end',
        'max_training_label_available_at','max_training_feature_available_at','current_feature_available_at',
        'feature_schema_hash','output_type']
    ids=[]
    for _,row in forecasts.iterrows():
        record = {key:row[key] for key in ledger_fields}
        record['horizon_months'] = int(record['horizon_months'])
        record.update(protocol_hash=protocol_hash,input_sha256=manifest['sha256'])
        ids.append(ledger.append(record)['prediction_id'])
    forecasts['prediction_id'] = ids
    for frame in [forecasts,metrics,comparison,coverage]:
        frame['data_kind'] = manifest['data_kind']
        frame['run_id'] = metadata['run_id']
        frame['protocol_hash'] = protocol_hash
        frame['input_sha256'] = manifest['sha256']
    for audit in audits:
        audit.update(data_kind=manifest['data_kind'],run_id=metadata['run_id'],protocol_hash=protocol_hash)
    forecasts.to_csv(out/'relative_forecasts.csv',index=False)
    metrics.to_csv(out/'relative_metrics.csv',index=False)
    comparison.to_csv(out/'relative_comparison.csv',index=False)
    coverage.to_csv(out/'cohort_coverage.csv',index=False)
    write_json(out/'relative_model_parameters.json',audits)
    metadata['relative_status'] = 'completed' if not forecasts.empty else 'no_eligible_common_origins'
    from .reporting import md_table
    core = metrics.drop(columns=['data_kind','run_id','protocol_hash','input_sha256'],errors='ignore')
    text = f'''# P1 相对收益双路径工程报告

**{'SYNTHETIC_TEST_ONLY：合成数据工程验证，无真实市场结论' if manifest['data_kind']=='synthetic' else '真实历史样本外研究；来源与时间戳仍需独立核验'}**

运行：{metadata['run_id']}；相对模块状态：{metadata['relative_status']}。
此文件列固定参数历史均值、OLS、Ridge、Elastic Net基模型；无基模型超参数搜索、概率或当前预测。
{'本次已启用区间/集成扩展，详见extensions_report.md；此文件不重复其结果。' if config.get('extensions',{}).get('enabled',False) else '本次未启用区间/集成扩展。'}
直接路径使用NDX-SPX的12月动量/波动差；间接路径用同一训练行分别拟合两指数再相减。
两路径均严格按标签终点和公布可得时间筛选，在各自训练矩阵内标准化。
主比较只使用共同训练/预测日；完整覆盖与跳过原因见cohort_coverage.csv。

## 样本外指标

{md_table(core)}

## 单位与冲突

目标为年化对数收益差；predicted_relative_wealth_cagr=expm1(log差)，不是两指数CAGR之差。
predicted_cagr_difference仅间接路径有值，直接路径留空；逐期路径分歧见relative_comparison.csv。
路径符号冲突数：{int(comparison.direction_conflict.sum()) if not comparison.empty else 0}（按模型/期限/起点计，不是独立市场周期数）。

## 时间与来源审计

prediction_ledger.jsonl创建后只追加，拒绝覆盖、重复ID、未来训练标签/特征及真实结果列。
decision_at是历史模拟决策时点；recorded_at才是本次程序实际写入时间，不能混为当年实际发布的预测。
协议哈希：{protocol_hash}；输入哈希：{manifest['sha256']}。
合成时间戳来自明确的月末23:59:59 UTC假设；真实P1数据必须提供decision_at和tr_available_at。
当前适配器要求decision_at处于日历月末UTC日期；尚未实现实际最后交易日/执行日映射。
字段级外部as-of接口已可测试，宏观和盈利特征尚未接入模型；未知发布时间不按0延迟补齐。

## 状态与限制

全部证据D；7/10年样本外证据有限。此文件不列区间/估值/集成/策略；分别见已启用的extensions_report.md、strategy_report.md。HAC/区块推断未实现。
真实行情覆盖{'为0' if manifest['data_kind']=='synthetic' else '按data_quality_report.md记录'}。
工程通过不表示模型有真实预测增益。P1后续模块及嵌套调参、最终冻结审计尚待实现。
复现：python -m index_forecast.cli backtest --config config/p1_synthetic.yaml（仅适用于本项目合成配置）。
'''
    (out/'relative_report.md').write_text(text,encoding='utf-8')
    return forecasts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['make-sample','validate-data','build-dataset','train','backtest','report'])
    parser.add_argument('--config',default='config/default.yaml')
    args = parser.parse_args(argv)
    try:
        if args.command == 'make-sample':
            c,root = load_config(args.config)
            if not c['data']['allow_synthetic']: raise ValueError('make-sample requires explicit synthetic config')
            print(f'SYNTHETIC_TEST_ONLY: {sample(root,c["project"]["seed"])}')
        else:
            execute(args.command,args.config)
    except (ValueError,FileNotFoundError,KeyError) as exc:
        print(f'ERROR: {exc}',file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
