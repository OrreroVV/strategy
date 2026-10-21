# 数据契约 v1

## 月度CSV（UTF-8，列名可通过 column_mapping 映射）

| 字段 | 单位、规则 | 用途 |
| --- | --- | --- |
| date | YYYY-MM-DD，日历月末，代表最后交易日收盘后；按月唯一 | 预测起点 |
| index_id | SPX / NDX，两个指数必须同时提供 | 联合研究对象 |
| total_return_index | 正有限指数点；美元、税前总收益、分红再投资；NA保留 | 标签、动量和波动率 |
| source | 非空提供方名称 | 溯源 |
| source_series_id | 非空且与manifest series.id一致 | 序列标识 |
| unit | 严格 index_points | 禁止价格/百分比口径混用 |
| quality_flag | 合成为 SYNTHETIC_TEST_ONLY；真实数据保留提供方标记 | 数据性质 |
| price_index | 可选，正有限指数点，不能替代TR | P1辅助描述 |
| cpi | 可选，正有限CPI水平；不得用同比增长率替代 | 仅实际收益标签 |
| trailing_pe | 可选，正有限倍数，每指数历史定义一致 | 仅估值变化标签 |
| release_date / vintage_date | 若在主表提供，必须不晚于date | 总收益观测的可用性声明 |

主表不直接使用宏观、forward EPS/PE、CPI、估值等列作为特征。未经注册的额外列被忽略，防止意外加入未来标签。
不推断比例单位、不自动复权、不静默插补、不删除异常行情。
缺月会诊断；跨缺月动量/波动率无效。终点缺失则标签为NA。
>50%月度变化仅作待核验告警，不自行改写。多个来源的差异需人工确认后制作独立快照。

## 可选外部as-of记录

`observation_date, release_date, vintage_date, value`：UTC时间戳、三个时间缺一即报错。
截止时点同时过滤三个时间，再选最近观测期及该期最新已知版本。
P0仅提供并测试此接口，不将未核实宏观/分析师数据接入模型。
同一字段/观测/版本不得有冲突值，导入方须提供字段级来源与单位。

## 派生字段

| 字段 | 规则 |
| --- | --- |
| momentum_12m | ln(TR[t]/TR[t-12])，包含最近1个月，过去13个观察完整 |
| vol_12m | 过去12个月月度对数收益样本标准差(ddof=1)*sqrt(12) |
| label_end | 日历月份t+H的月末 |
| y | 12/H*ln(TR[t+H]/TR[t])，年化对数收益小数 |
| cagr | expm1(y)，复合年化收益率小数 |
| y_real | y-12/H*ln(CPI[t+H]/CPI[t]) |
| y_relative | y_NDX-y_SPX，正值为NDX领先；两指数当期/终点均须有效 |
| delta_log_pe | ln(trailing_pe[t+H]/trailing_pe[t])，非年化 |

所有标签列禁止作为特征。CPI是事后实际标签，不能据此声称当时可以预测未来通胀。
数据字典未覆盖字段的源定义、币种、修订政策：默认未核验，禁用为模型特征。

## P1新增契约（schema_version=2）

主表增加`decision_at`与`tr_available_at`：均为带时区的时间戳。
当前适配器要求decision_at在date对应的日历月末UTC日期；同一date两指数的decision_at必须一致。
tr_available_at允许晚于decision_at，但这会阻止在当期使用对应价格派生特征。
动量和波动特征可得时间取过去13个所需观察的最晚tr_available_at；缺月或缺时间不插补。
名义标签的label_available_at取起点与终点TR的较晚可得时点，缺失终点则NA。
训练既须label_end<隔离边界，也须label_available_at<本次decision_at，历史feature_available_at<=当时decision_at。

外部`select_asof`长表：record_id、index_id、feature_id、observation_date、release_at、vintage_at、available_at、value、
unit、currency、definition_id、source_id、source_snapshot_sha256、data_kind。
release/vintage/available均须显式时区，available不早于release/vintage；source快照哈希为64位小写十六进制。
输入源表data_kind只能单一real或synthetic；派生性质另由处理记录表达，不允许混合真实/合成来源。
该接口尚未启用为外部模型特征；调用者必须提供匹配的unit/currency/definition_id，不自动推断比例口径。

相对输出target_id=relative_log_return，target_unit=annualized_log_return_difference。
predicted_log_annual_return与predicted_relative_return均为年化对数收益差。
predicted_relative_wealth_cagr=expm1(log差)是财富比的年化增长；不等于两指数CAGR之差。
predicted_cagr_difference=expm1(p_NDX)-expm1(p_SPX)，仅间接路径有定义。
prediction_ledger.jsonl不含真实结果/误差列；真实结果保存在独立的事后评价CSV。
predicted记录的decision_at为模拟时钟，recorded_at为程序实际记录时钟。
所有P1产物记录data_kind/run_id、输入与协议哈希，证据等级目前始终D。

## manifest.json

必需：data_kind(real/synthetic)、provider、url、retrieved_at(含时区的获取时间)、license、currency(USD)、
return_type(gross_total_return)、dividends_reinvested(true)、point_in_time_verified(true)、sha256、timezone、
series（SPX/NDX各自id与definition）。另应记录版本、数据覆盖、修订政策、上线前回溯历史、
字段级来源、CPI基期和PE定义、抽样核验记录。未获取信息明确写“未提供/待核验”，不得把待核验声明设为true绕过门禁。
`point_in_time_verified`针对TR特征历史版本，由提供方/研究者核验；软件不能替代来源真实性核验。
CSV哈希不匹配直接拒绝；真实/合成混标直接拒绝；生产配置默认禁止合成数据。

## P1估值/区间/集成扩展契约

估值额外字段：eps_ttm（正的同口径指数EPS）、dividend_yield（0到1小数）、pe_available_at、eps_available_at、
dividend_available_at（含时区）、pe_definition_id、eps_definition_id，连同已有trailing_pe。
available_at必须包含发布与历史版本/供应商延迟，不能把今天下载的修订值配上最初发布日期。
PE/EPS定义不得跨版本拼接，EPS窗口出现零负值时模型不可用；要求精确的60个月EPS端点，禁止按行号跨缺月。
真实manifest还需valuation_fields_verified=true，并在valuation_fields中对trailing_pe/eps_ttm/dividend_yield逐一记录：
provider、url、definition_id、point_in_time_verified、unit、currency。
当前单位分别为multiple/not_applicable、USD_per_index_share/USD、ratio/not_applicable；供应商其他单位必须有可复现转换和口径说明。
PE/EPS行定义必须匹配manifest声明。上述核验声明不能替代研究者查证真实供应商的定义和历史版本。

区间输入必须明确historical_oos，按index_id、target_id、H、model_name、prediction_path、selection_version分组。
lower/upper_80/95_log为年化对数目标单位；_cagr只用于绝对收益；_relative_wealth_cagr只用于相对目标。
interval_status记录样本可用性，interval_transform_status另记录转换溢出；不可用边界为NA，不用0代替。
calibration_audit记录使用的历史日期、成熟标签最晚可得时间及非重叠区间数。
interval_metrics同时给区间数量、可用率、覆盖率及平均log宽度；无区间时覆盖率和宽度NA，可用率0。

集成权重为非负、总和1；weights_json明确所有候选，不隐式剔除失败候选。
ensemble_status可为equal_weight、fitted、equal_weight_fallback、baseline_fallback或missing_base_models。
rho为加权集成占比，eta为向等权惩罚强度，均属研究参数；所有选择仅在development_prequential运行。
基模绝对/相对点预测文件保持原样；新集成与区间另表保存，不把基模型CAGR差复制为集成CAGR差。
valuation_diagnostics记录缺失/不适用原因；valuation_forecasts只保存可计算且历史结果已成熟的预测。
本扩展未将估值分解纳入趋势模型集成，避免把不同特征覆盖样本直接混合比较。

## 月度指数代理账本

原始策略价格来自标准TR主表，要求所配置起止月两个指数完整，不前向填缺月；真实源还须有tr_available_at。
date是日历月末，execution_at是该月23:59:59 UTC的代理标记时刻，不承诺对应交易日可成交。
信号只保留signal_id、forecast_date、decision_at、双路径点预测、直接路径80%log区间、证据和冲突标记。
保存的strategy_signals.csv另附溯源元信息；重放API时须显式选SIGNAL_COLUMNS，不能把含真实结果的评价表直接当信号。
模拟器要求decision_at<execution_at，季度采用此前已知且不超过3个月的信号；过期/冲突/区间缺失/低证据均保持战略规则。

strategy_ledger每行记录date、scenario_id、funding_kind、cost_bps、max_tilt及：

| 字段 | 定义 |
| --- | --- |
| nav_before_flow | 本月按新价格估值的旧持仓和现金，尚未加入本月现金流 |
| external_flow | 投资者本月投入（正数）；在投资者现金流表中符号相反 |
| spx/ndx_units | 分数指数代理单位，不是实际基金份额 |
| spx/ndx_price | 本月总收益指数代理报价，非基金实际成交价 |
| spx/ndx_value | 单位乘当月TR代理价格 |
| spx/ndx_trade | 本月成交美元额，买入正、卖出负 |
| trade_notional | 买卖绝对成交额之和 |
| trading_cost | trade_notional*单边综合成本bp/10000 |
| nav | 两资产价值+现金，等于nav_before_flow+external_flow-trading_cost |
| period_twr | 旧资金价格收益因子乘入金后费用因子减1；首期只包含初次交易费用 |
| unit_nav | 从1出发累计period_twr，剔除外部入金，不等于累计账户金额 |
| drawdown | unit_nav除以历史峰值（含初始1）减1，月末观察口径 |
| turnover | trade_notional/交易前含本月入金的总资产，双边定义 |
| target_ndx | 新资金或年度再平衡的目标NDX比例，非保证达到的全账户比例 |
| signal_active / reason | 是否启用倾斜及拒绝/回退原因 |

strategy_cashflows采用投资者符号：投入负数，期末持仓标记价值正数；末期不实际出售、不另扣出售费。
TWR CAGR以实际天数/365.25，XIRR以实际天数/365；潜在多根不输出唯一收益率。
夏普无已核验无风险利率时NA；0现金利息是情景，不能混作无风险基准。
最长恢复期只计已完成恢复；未恢复另标unrecovered_at_end和最长观测天数，不把删失当完成。
所有账本、图表、源表和汇总继承data_kind/run_id/输入及协议哈希，合成情景不能变成真实市场研究结论。
