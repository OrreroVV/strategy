# P1 / P2 后续设计 v1

设计日期：2026-10-19。状态：**设计完成，新增算法尚未实现或验收**。
上句记录设计v1时的状态；后续实施进展以[实施清单](implementation_backlog.yaml)与[p1_foundation_delivery.md](p1_foundation_delivery.md)为准，不能把设计稿中的拟议阈值视为已验证结果。
承接用户原始实现规格与P0研究计划；本文件中的阈值、搜索网格、费用均为拟议研究参数，不是真实观测或已验证的最优参数。
真实行情覆盖仍为0，不生成收益预测、统计显著性或策略业绩。
配套文件：[验证协议](validation_protocol.md)、[实施清单](implementation_backlog.yaml)。

## 1. 范围与执行顺序

| 顺序 | 交付 | 工程上可先开展 | 真实验证的依赖 |
| --- | --- | --- | --- |
| P1-01 | 字段级来源、特征注册表、预测日志与时间切分接口 | 是，合成测试 | 真实总收益与历史可得性证据 |
| P1-02 | 相对收益直接/间接模型 | 是，仅工程验证 | 两指数共同TR样本 |
| P1-03 | 收益分解与估值收缩 | 接口及公式测试可先做 | 历史时点PE、EPS、股息及口径 |
| P1-04 | 预测区间、依赖稳健的不确定性评价 | 是，允许不足时返回NA | 已成熟的真实样本外残差 |
| P1-05 | 等权、非负权重、向均值收缩集成 | 是 | 真实开发期OOF预测矩阵 |
| P1-06 | 持有/组合/定投/有限倾斜模拟 | 是，合成现金流测试 | 可执行时点、成本、真实OOS信号 |
| P1-07 | 图表、报告、状态与证据等级 | 是 | 每张图对应通过验收的模块和运行 |
| P2-01 | 有限网格Random Forest、消融 | P1工程验收后 | 数据质量与样本量门槛 |
| P2-02 | 可选XGBoost | 不作为强制交付 | RF评估完成、依赖及增量价值理由 |
| P2-03 | 状态模型、动态集成、人民币QDII层 | 保留扩展设计 | 各自额外数据与独立研究计划 |

工程验收和真实研究验收分开记录。合成测试通过不改变真实验证状态；数据不足的模块返回具体原因，不填假值。

## 2. 对现有P0的最小改动

保留现有命令、配置和P0历史报告；新能力通过schema_version=2及独立配置启用。
不把设计参数直接合并进config/default.yaml：当前配置解析器只支持P0，必须先扩展解析器和测试。

| 现有位置 | 拟议增量 | 兼容约束 |
| --- | --- | --- |
| data.py / FEATURES | 新增feature_registry.py、point_in_time.py | P0的两项因果特征语义不变 |
| targets.py | 增加target_id、target_unit及标签可得时间 | 保留P0标签数值与日历月份规则 |
| backtest.py | 抽取splits.py、prediction_ledger.py和evaluation.py | 原P0路径继续通过全部回归测试 |
| models/ | 新增baseline、relative、valuation、ensemble模块 | 统一fit/predict/export_metadata；不支持区间时明确返回状态 |
| uncertainty.py | 残差筛选、校准、区块统计 | 不从训练拟合残差冒充OOS误差 |
| portfolio.py | 独立现金流、执行、成本账本 | 不向模型传入未来收益 |
| reporting.py | 按模块状态渲染图表和限制 | 缺数据展示缺口而非空白成功图 |
| cli.py | 分离backtest、forecast-latest、report | 旧train/report别名保留说明；新report只读取已保存运行，不隐式重训 |

源码、配置、数据、预测日志和协议均记录哈希；所有运行留在本研究独立目录。

## 3. 数据契约v2与可得性

新增长表 `feature_observations`：

| 字段 | 约束 |
| --- | --- |
| index_id / feature_id | 字段级注册，不允许任意CSV列自动入模 |
| observation_date | 经济所属期，不能代表公布时间 |
| release_at / vintage_at | 带时区的实际发布时间和该版本可用时间 |
| available_at | max(release_at,vintage_at,供应商已知延迟)，延迟规则单独保存 |
| value / unit / currency | 比例统一为小数；无币种填明确的not_applicable |
| source_id / source_snapshot_sha256 | 可追溯原始快照及字段定义 |
| revision_policy / definition_id | PE/EPS/股息定义的版本；不跨定义静默拼接 |
| data_kind / quality_flag | real、derived、synthetic分开；derived继承上游性质 |

另存observation_date、实际最后交易日、close_at、decision_at、execution_at。
日历月末只作主键；decision_at代表实际收盘并获得数据后，execution_at必须严格晚于decision_at。
无法确定同日先后顺序时，将执行推迟到下一可证明的交易时点。

as-of按每个feature_id和index_id过滤available_at<=decision_at，选择最近已公布观测及其当时最新版本。
冲突版本、单位变化、来源切换、缺失发布时间均报错或禁用对应特征；不能把主表的单个release_date当作整行全部字段的可得时间。
只有事后CPI/估值时可构造明确标记的事后标签，不能据此开启实时估值特征。
实际收益标签的label_available_at还须考虑终点CPI发布时间；价格标签则考虑终点TR可得时间。
无历史vintage的宏观修订值默认禁用，单纯滞后不能消除修订泄漏。情景分析另标scenario，不混入真实OOS。

特征注册记录公式、输入、窗口、跳过月数、有效起点、可得时间、允许的target_id。
估值分位数只用截至decision_at的历史窗口，先实现扩展窗口经验百分位；同值规则固定为<=当前值的历史占比。
Forward EPS/PE须有历史时间戳；成分权重须为历史成分与权重，数据缺口时禁用。

## 4. 模型接口与通用缺失策略

拟议接口：fit(training_frame, fit_context)、predict(feature_frame)、export_metadata()。
区间通过独立校准器处理，不要求每个基模型自行实现有理论保证的predict_interval。
fit_context包含target_id、H、decision_at、feature_schema_hash、训练行ID、所有信息截止时间。
输入不得包含目标列；调用层与模型层双重检查特征白名单及时间来源。
默认完整案例；若试验中启用中位数插补，只在内层训练中拟合并增加缺失指示，作为另一个预注册实验比较。
不在预测失败后悄悄换模型：返回status/reason；任何预定回退须记录fallback_from和fallback_to。

## 5. P1相对收益双路径

直接目标：y_rel=y_NDX-y_SPX，单位为年化对数收益差。
先训练历史均值、OLS、Ridge、Elastic Net；第一版特征是两指数momentum_12m、vol_12m的差。
历史时点估值/盈利数据可靠后，以独立feature_set_id扩展估值差、盈利增长差与股息差。
间接路径：分别对两指数训练相同模型，再令p_rel=p_NDX-p_SPX。

比较时固定共同预测日、共同有效训练起点、相同期限与成熟度规则；两边预处理仍分别在各自训练矩阵拟合。
同时报告全可用样本与共同样本，记录各路径覆盖率、被排除行及原因。
主比较使用共同样本的RMSE/MAE、相对历史均值OOS R²、正负方向准确率。
保存每次两路径的预测差及符号冲突；不得按每期已知结果挑选更好的路径。

**不得把expm1(y_rel)当作两指数CAGR之差。**
expm1(y_rel)对应两指数财富比的年化相对增长；CAGR差应另算expm1(p_NDX)-expm1(p_SPX)。
直接路径不能在没有联合绝对预测时唯一还原CAGR差，因此该字段留空。
间接区间使用同一预测起点的配对误差e_NDX-e_SPX校准，保留相关性；不能简单相减两个边际区间后宣称达到80%覆盖。

## 6. P1收益分解与估值收缩

解释模型近似：p_log≈log1p(DY_t)+g_EPS_hat+(v_terminal_hat-v_t)/(H/12)。
DY为小数，g_EPS_hat是年化对数每股盈利增长，v=ln(同口径正PE)。
该式是近似解释，不是会计恒等式；若EPS预期是算术增速，先明确期限并转换，不能把12个月预期重复当作多年已知增长。
不再叠加回购收益，以避免和每股EPS重复计量。回购拆解须另建一致口径模型。

EPS增长基线仅使用当时已公布历史EPS，窗口60个月，至少36个有效月且两端EPS为正；不足则该模型不可用。
Forward预期作为独立分支，须给出多年外推假设与敏感性，禁止静默补齐。
历史分解只作事后描述；终点EPS和PE不能用于预测分解。

估值收缩：v_terminal_hat=lambda_H*v_t+(1-lambda_H)*v_ref(t)。
v_ref取当时有效logPE历史中位数；参考窗口候选120/240个月，最少60个正PE观测。
lambda候选0、0.25、0.5、0.75、1；仅在内层成熟标签验证选择，平分时偏向更强持续性并固定规则。
无足够内层验证时只输出预先固定lambda=1的“无估值变化”基线，不把它包装成已调参收缩模型。
PE<=0、EPS跨零、PE定义变更均返回不可用；不通过极端截断隐藏公式失效。
单独报告股息、EPS增长、估值三项和近似残差；用真实数据验证近似误差后再讨论解释力。

## 7. P1区间和证据

第一版使用当时已成熟的prequential OOS误差e=y-p的经验分位数：
80%区间=[p+q0.10(e),p+q0.90(e)]；95%区间=[p+q0.025(e),p+q0.975(e)]。
残差与模型、期限、特征版本和固定选择程序绑定，不能把另一模型的误差直接移植。
校准集不是当前训练拟合误差；来源预测在生成时同样经过严格purge。
用过去残差建立的区间仅为经验估计，不宣称有交换性条件下的conformal有限样本覆盖保证。
对绝对收益区间以expm1单调转换为CAGR区间，字段显式区分log和CAGR单位。

拟议门槛：80%至少60条已成熟OOS残差、至少5个非重叠结果区间；95%至少120条、至少10个。
以上是保守研究门槛，不是统计定理，也不意味着独立市场周期。未达门槛输出NA和原因。
7/10年很可能达不到，允许其长期保持NA，不能降低门槛只为补齐报告。
覆盖率、区间宽度、覆盖随时间变化在后续成熟样本上评价；校准样本覆盖不作独立验证成绩。
区块重抽样评价误差差值与覆盖率不确定性；具体时间边界见验证协议。

证据标签：D=合成、质量失败、缺OOS/不确定性证据；C=基本数据合格但窗口/模型敏感或样本不足；
B=预先规定多个窗口对基准有稳定改善且区间有独立评价；A需多个来源/市场状态复核并经人工审查。
“有稳定改善”按开发期协议判定，不能由最终测试反向优化规则。无自动A评级，全部理由存reason_codes。
只有B/A才允许实验性的模型配置倾斜；未达到条件保持战略权重。

## 8. P1集成

统一候选集合、共同OOF日期与预测目标；每个期限独立处理。
等权集成先实现；验证加权求解 min_w mean((y-Pw)^2)+eta*||w-w_equal||²，w>=0且sum(w)=1。
eta预先固定0.01（年化对数收益为目标单位），另作0/0.1敏感性；不对最终测试择优。
权重仅从开发期内层OOF矩阵拟合；最少60条和5个非重叠结果窗口，否则显式回退到等权。
稳健集成：p_robust=rho*p_ensemble+(1-rho)*p_mean；rho候选0、0.25、0.5、0.75、1，内层选择。
不足时rho=0，标记baseline_fallback。不能把回退输出冒充集成取得的改善。
候选模型缺失时，不自动按剩余模型重新归一化；按预先定义的缺失策略记录整期不可用或显式回退。
区间对最终集成的历史OOS误差重新校准，不对基模型区间端点加权后声称覆盖。

## 9. P1策略与现金流

先输出信号日志，再由独立账本执行：signal_generated_at < execution_at。
信号只来自真实可用OOS预测，标签y不出现在策略输入schema中。
第一版是“指数代理组合模拟”；总收益指数不可直接成交，不将结果描述为可直接实现的基金业绩。
若需真实执行回测，应接入相应可交易产品并单独记录跟踪差、费用、税费与流动性。

基准组：SPX持有、NDX持有、50/50年度再平衡、相同日期固定金额定投、有限配置倾斜。
一次性投入组与定投组分别比较；相同组用相同起始资金、外部现金流、现金利息和执行规则。
默认战略NDX权重0.5；每次偏离战略权重上限5个百分点，并比较2/10个百分点。
倾斜方向来自指定的单一期限（预先固定60月）相对预测；仅当80%相对区间不含0且证据B/A时启用。
P1默认只用新增资金向目标权重靠拢，不因信号卖出；无新增资金则不调仓。
季度评估信号；不允许多期限当期择优。无区间、路径冲突或证据不足则维持战略规则。

成本分项：买卖费用、滑点、融资/现金利息、产品费用及汇率层。
尚无真实报价时可用单边0/5/20/50bp做明确标记的成本情景，不能说是实际成本；现金利率缺失时默认0并披露。
成本采用成交额乘单边费率；记录成交前后净值，费用不作为外部现金流。
换手=当期买入额+卖出额除以交易前净资产；不再乘0.5，报告写明此双边成交额定义。
外部申购和提取从时间加权收益中剔除，另计算资金加权XIRR。
XIRR以实际天数/365：sum(CF_i/(1+r)^(days_i/365))=0，投入为负、期末清算为正，r>-1。
无变号、无根或多根时明确返回不可唯一确定，不能输出默认0%；数值求根需满足区间条件。
报告TWR CAGR、波动、最大回撤、恢复期、下行波动、成本、换手和XIRR；未恢复回撤标记右删失。
无风险利率不可得则夏普留空，不以现金情景0利率冒充真实无风险利率来源。

## 10. P2有限复杂度

RF先用已安装scikit-learn，不新增依赖。拟议固定200棵树，max_depth=[2,3]、min_samples_leaf=[24,60]、
max_features=[0.5,1.0]，共8组；bootstrap=false、oob_score=false，random_state固定，n_jobs=1。
禁止用随机OOB误差替代时间序列验证。每次选择至少3个合格内层时间窗口，最少120个有效成熟训练标签。
内层误差接近（相对差小于1%）时按预定顺序选更浅树、更大叶；记录全部候选、失败和耗时。
特征消融按估值/盈利/宏观/趋势风险/集中度预先分组；只有真实可得的组才进入实验，不因缺组伪造“全特征模型”。
比较同一共同样本下OLS/Ridge/Elastic Net/历史均值，并保留各模型自然覆盖样本作为补充。
RF未在开发期多个窗口改善，不升级为默认预测器，最终测试仍报告预先列入的候选而不隐藏失败。

XGBoost、状态识别、动态集成分别建立实验ID；第一版不接LSTM/Transformer。
XGBoost无强制安装计划，必须先明确相对RF的研究理由、依赖版本和有限搜索上限。
QDII层另开本研究子模块配置：USD/CNY按同一时点换算，基金净值已扣管理费时禁止重复扣费，
指数代理与基金实际净值分别评价；申购限额、溢价、估值日/披露日、停牌和节假日不可忽略。

## 11. 输出契约与报告

预测记录新增target_id、prediction_path、target_unit、decision_at、label_available_at、
feature_schema_hash、protocol_hash、selection_version、status/reason、model_run_id。
log/CAGR区间分别命名lower_80_log/lower_80_cagr等，避免复用P0未定义单位的空区间列。
概率预测未单独校准时不得从点预测或80%区间凭空生成概率。
新增calibration_audit、ensemble_weights、fold_manifest、cohort_coverage、strategy_ledger、cashflows与experiment_registry。
所有CSV/JSON/图表携带data_kind、run_id与来源哈希；合成来源沿派生链传递。

图表按有效模块生成：TR/价格对照、分期限历史标签分布、事后实际收益、历史时点估值分位数、
收益分解与近似残差、OOS实际/预测、滚动误差、相对双路径/区间、覆盖率/宽度、策略净值/回撤/换手。
标注样本范围、期限、单位、真实/合成、历史OOS/当前预测；未实现模块只显示状态说明。

forecast-latest与历史评估分离：不要求当前未来标签成熟，但训练/校准/选择信息须成熟并可用。
只有真实数据质量、可得性、数据新鲜度、模型运行及协议检查通过才可发布最新预测。
合成模式只允许输出synthetic_demo_forecast，禁止伪装current_market_forecast。

## 12. 验收与参考

实施顺序与测试映射见清单；每项先公式/时间边界测试，再合成集成测试，再真实数据验收。
本轮设计未安装新依赖、未实现以上算法、未修改历史回测结果；P0回归测试在设计前复跑为36 passed。

2026-10-19核验的官方接口依据：

- [scikit-learn RandomForestRegressor](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.RandomForestRegressor.html)：参数接口依据，网格由本研究提出。
- [scikit-learn TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html)：时间顺序切分接口参考；本项目仍按标签终点及可得时间另做purge，不能只靠gap行数。
- [statsmodels cov_hac](https://www.statsmodels.org/stable/generated/statsmodels.stats.sandwich_covariance.cov_hac.html)：HAC接口参考；推断适用性另由协议审查。
- [SciPy brentq](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.brentq.html)：括区间求根接口参考，不能自动保证XIRR有唯一经济解释。
