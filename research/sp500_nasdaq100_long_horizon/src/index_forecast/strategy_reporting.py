"""Cost/funding scenarios for a paper index-proxy book; never broker execution."""
import hashlib
import json
import numpy as np
import pandas as pd
from .portfolio import STRATEGIES,signals_from_intervals,simulate_portfolio
from .point_in_time import utc_timestamp
from .reporting import md_table


def prepare_proxy_prices(panel,settings,data_kind):
    p=panel[['date','index_id','total_return_index']].copy()
    p['date']=pd.to_datetime(p.date)
    start=pd.Timestamp(settings['start']);end=pd.Timestamp(settings['end']) if settings.get('end') else p.date.max()
    p=p[p.date.between(start,end)]
    if p.empty or p.duplicated(['date','index_id']).any():raise ValueError('Empty/duplicate proxy prices')
    wide=p.pivot(index='date',columns='index_id',values='total_return_index').reindex(columns=['SPX','NDX'])
    expected=pd.date_range(start,end,freq='ME')
    if not wide.index.equals(expected.rename('date')) or not np.isfinite(wide.to_numpy()).all() or (wide<=0).any().any():
        raise ValueError('Complete paired calendar prices required for configured strategy span; no filling')
    if data_kind=='real' and 'tr_available_at' not in panel:raise ValueError('Real proxy prices require explicit availability')
    if 'tr_available_at' in panel:
        current=panel[pd.to_datetime(panel.date).between(start,end)]
        for row in current.itertuples():
            execution=pd.Timestamp(row.date,tz='UTC')+pd.Timedelta(hours=23,minutes=59,seconds=59)
            if utc_timestamp(row.tr_available_at)>execution:raise ValueError('Proxy quote unavailable at simulated execution')
    return wide.reset_index()


def save_portfolio_run(panel,intervals,config,manifest,metadata,out,write_json):
    settings=config['portfolio']
    prices=prepare_proxy_prices(panel,settings,manifest['data_kind'])
    signals=signals_from_intervals(intervals,settings['signal_model'],settings['signal_horizon_months'])
    policy=dict(settings=settings,input_sha256=manifest['sha256'],extensions_protocol_hash=metadata['extensions_protocol_hash'],
        simulation_kind='monthly_index_proxy',execution='next eligible UTC calendar month-end strictly after signal',
        external_flows='at close before trades; fees internal after deposits',cash_interest='zero scenario, not risk-free rate',
        terminal_value='mark-to-market, not an executed sale',version='portfolio_v1')
    policy_hash=hashlib.sha256(json.dumps(policy,sort_keys=True,default=str).encode()).hexdigest()
    write_json(out/'portfolio_policy.json',policy|{'policy_hash':policy_hash})
    def save(frame,name):
        f=frame.copy();f['run_id']=metadata['run_id'];f['data_kind']=manifest['data_kind']
        f['input_sha256']=manifest['sha256'];f['portfolio_policy_hash']=policy_hash
        f.to_csv(out/name,index=False)
    save(signals,'strategy_signals.csv')
    ledgers=[];cashflows=[];summaries=[]
    for funding_kind,initial,contribution in [('lump_sum',settings['initial_capital'],0.),('dca',0.,settings['monthly_contribution'])]:
        for cost in settings['cost_bps']:
            for strategy in STRATEGIES:
                tilts=settings['tilt_limits'] if strategy=='limited_tilt_new_money' else [0.]
                for tilt in tilts:
                    identifier=f'{funding_kind}__{strategy}__cost{cost:g}__tilt{tilt:g}'
                    ledger,flows,summary=simulate_portfolio(prices,signals,strategy,initial_capital=initial,
                        monthly_contribution=contribution,cost_bps=cost,strategic_ndx=settings['strategic_ndx'],
                        max_tilt=tilt,max_signal_age_months=settings['max_signal_age_months'],review_months=settings['review_months'])
                    for frame in [ledger,flows]:
                        frame['scenario_id']=identifier;frame['funding_kind']=funding_kind
                        frame['cost_bps']=cost;frame['max_tilt']=tilt
                    summary.update(scenario_id=identifier,funding_kind=funding_kind)
                    ledgers.append(ledger);cashflows.append(flows);summaries.append(summary)
    ledger=pd.concat(ledgers,ignore_index=True);flows=pd.concat(cashflows,ignore_index=True);summary=pd.DataFrame(summaries)
    save(ledger,'strategy_ledger.csv');save(flows,'strategy_cashflows.csv');save(summary,'strategy_metrics.csv')
    metadata['portfolio_status']='index_proxy_simulation_completed'
    metadata['portfolio_policy_hash']=policy_hash;metadata['portfolio_scenarios']=len(summary)
    display=summary[(summary.cost_bps==settings['plot_cost_bps']) &
        ((summary.strategy!='limited_tilt_new_money')|np.isclose(summary.max_tilt,settings['plot_tilt_limit']))]
    display=display[['funding_kind','strategy','cost_bps','max_tilt','twr_cagr','xirr','max_drawdown','total_cost','active_tilt_months']]
    report=f'''# 策略与现金流工程报告

**{'SYNTHETIC_TEST_ONLY — 真实行情覆盖0' if manifest['data_kind']=='synthetic' else '真实指数数据的纸面代理模拟，非可交易产品实盘回测'}**

运行{metadata['run_id']}，{prices.date.min().date()}至{prices.date.max().date()}，美元gross total return月度指数代理。
本次{len(summary)}个预先规定的资金/成本/策略情景；情景参数不能当作个性化配置建议。
来源和数据许可见source_manifest.json；输入SHA-256为{manifest['sha256']}。

## 可比情景

一次性资金和固定金额定投分组比较，每组用同样的价格、现金流、执行延迟和成本。
SPX、NDX固定持有、50/50年度再平衡、战略比例新增资金、有限倾斜新增资金均保留。
单边综合成本{settings['cost_bps']}bp是研究情景，不是实际费用报价；0成本是独立反事实，不能由有成本收益简单加回费用得到。
有限倾斜只影响新增资金，不因模型信号卖出。偏离战略NDX权重上限为{settings['tilt_limits']}，按{settings['review_months']}月份评估。
信号固定取{settings['signal_model']}的{settings['signal_horizon_months']}月相对双路径；证据A/B、80%区间不含0、路径一致且不超过{settings['max_signal_age_months']}个月才允许倾斜。
没有从真实结果列生成信号，信号表使用封闭白名单；本次活跃倾斜月数合计{int(ledger.signal_active.sum())}，不能将没有启用的倾斜解释为模型增益。

## {settings['plot_cost_bps']}bp情景摘要（收益率均为小数）

{md_table(display)}

完整各成本及2/5/10个百分点敏感性见strategy_metrics.csv；不按最终业绩挑选情景。

## 执行与会计

信号决策时钟必须严格早于执行。只有月度数据，因此最早在下一个月末收盘代理价成交，不使用信号当月收盘价假定已成交。
每月先对旧持仓按当期价估值，再记外部入金，再执行交易与内部费用；不允许负现金、负头寸或填补价格缺月。
仅支持无杠杆、两指数、分数单位的代理账本；总收益指数不可直接成交，无真实产品流动性/税费/限购模拟。
TWR剔除外部现金流，初次买入费用纳入初始费用因子；波动率用其后月度收益，年化sqrt(12)。
CAGR用实际天数/365.25，XIRR用实际天数/365，期末为持仓标记价值而非实际卖出，未再扣期末清算费。
账户金额增长不能代替TWR；XIRR单列。多次变号时保守标记potential_multiple_roots，不捏造唯一收益率。
换手为双边成交额/交易前含当期入金资产，年化包含初次建仓。现金利息设0是情景，不是无风险利率来源，夏普留空。
最大回撤基于剔除入金后的单位净值；最长已完成恢复期与尚未恢复的右删失状态分开报告。

## 审计与限制

strategy_ledger.csv逐笔月度估值/流入/成本/持仓/目标/信号原因；strategy_cashflows.csv为投资者符号现金流。
portfolio_policy.json保存执行与会计假设，协议哈希{policy_hash}。原始数据和旧实验未覆盖。
全部证据D，当前合成运行只验证账本工程；没有真实策略有效性、人民币QDII收益或确定收益结论。
复现：python -m index_forecast.cli backtest --config {metadata['config_path']}。
'''
    (out/'strategy_report.md').write_text(report,encoding='utf-8')
    return ledger,summary
