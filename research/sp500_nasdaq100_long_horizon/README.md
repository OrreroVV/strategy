# 标普500 / 纳斯达克100长期收益研究（P0）

实现36/60/84/120个月历史总收益标签、CSV校验、时间序列样本外历史平均基准、OLS/Ridge/Elastic Net和Markdown报告。
**目前真实行情覆盖为0；合成样本仅验证工程流程，不构成市场预测或实证模型结论。**
研究设计见 [docs/research_plan.md](docs/research_plan.md)，数据字段与来源见 [docs/data_dictionary.md](docs/data_dictionary.md)、[docs/data_sources.md](docs/data_sources.md)。
P1/P2设计见[模型与系统设计](docs/p1_p2_design.md)、[验证与验收协议](docs/validation_protocol.md)、[实施依赖清单](docs/implementation_backlog.yaml)。P1现已接入字段级as-of、相对双路径、固定参数估值分解、经验区间、开发期集成、月度指数代理策略账本及静态研究图表。实施清单不能作为CLI运行配置；完整真实研究尚未验收。
现有沪深300研究和原始数据未修改；工作区根目录不是Git仓库，运行通过源码快照及SHA-256追溯。

## 环境与安装

Python>=3.11；本次复现为Windows/Python3.12。全部命令在本研究目录执行。
使用已有环境可运行 `../../.venv/Scripts/python.exe`；新机器建议独立环境：

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -e '.[test]'
./.venv/Scripts/python.exe -m pytest -q
```

下述 `python` 指已安装本项目的解释器。依赖使用numpy/pandas、scikit-learn、SciPy（约束优化/XIRR求根）、Matplotlib（可导出静态研究图，环境原已安装，现显式列为直接依赖）、PyYAML（配置）、pytest（测试）。
可替代实现是手写数值优化，但会增加数值验证成本，因此P0采用scikit-learn；无树模型/GPU/大型训练依赖。
实测版本见outputs/verification/environment.txt和各次run_metadata.json；pyproject.toml给兼容版本范围。

## 已验证的执行顺序

```powershell
# 先运行单元/集成测试
python -m pytest -q

# 仅首次生成合成CSV，已存在时明确拒绝覆盖
python -m index_forecast.cli make-sample --config config/synthetic.yaml

# 完全离线验证，不下载数据
python -m index_forecast.cli validate-data --config config/synthetic.yaml
python -m index_forecast.cli build-dataset --config config/synthetic.yaml
python -m index_forecast.cli backtest --config config/synthetic.yaml

# 真实数据缺失时此命令明确失败并保存诊断，不回退合成数据
python -m index_forecast.cli validate-data --config config/default.yaml
```

合成数据生成后可跳过make-sample重复后续命令，既有结果不会覆盖。
`train`、`report`与`backtest`均重新执行同一严格样本外流程，产生独立目录；不输出样本内表现或当前预测。
`validate-data`不训练；`build-dataset`只构建特征和标签。
CLI失败返回非零退出码。配置路径的父目录的父目录作为项目根，配置文件应放在本研究config目录。
输出目录强制限制在本研究内；真实CSV路径可指向外部本地只读快照。

## 真实数据入口

生产配置指向 `data/raw/monthly.csv` 与 `data/raw/manifest.json`，目前均缺失。
先依照来源文档获取并核实USD gross total return，再准备标准CSV与哈希manifest。
不要把合成manifest改名当作真实数据，也不要把未经核实的point_in_time_verified设为true。
字段映射由data.column_mapping配置（源列名:标准列名）。不隐式访问API、购买数据或读取凭据。
输入原始文件只读，代码从不重写raw数据。

## P1相对收益与可得性审计

先运行测试，再用独立schema_version=2配置执行：

```powershell
python -m pytest -q
python -m index_forecast.cli validate-data --config config/p1_synthetic.yaml
python -m index_forecast.cli backtest --config config/p1_synthetic.yaml
```

复用明确标记的既有合成CSV，不重新生成或覆盖原始样本。结果进入 `outputs/p1_synthetic_runs/<run_id>/`。
新增relative_forecasts.csv、relative_metrics.csv、relative_comparison.csv、cohort_coverage.csv、
relative_model_parameters.json、relative_report.md、prediction_ledger.jsonl和协议快照/哈希。
日志中decision_at是历史模拟决策时点，recorded_at是本次真实写入时点，不能把模拟预测称为当年实际发布的预测。

直接路径预测NDX-SPX的年化对数收益差，使用两指数过去12月动量和波动率之差；间接路径分别拟合后相减。
两路径的训练/评价日期严格一致；各指数自然可用训练数量及共同数量、缺失和未成熟起点均单独记录。
`predicted_relative_wealth_cagr`是财富比年化增长，不是CAGR差；`predicted_cagr_difference`只对间接路径计算，直接路径留空。
没有区间或概率，所有证据等级D。负OOS R²和路径冲突均保留。

P1真实数据入口为config/p1_real.yaml，仍默认禁止合成数据。除P0字段外需提供带时区的decision_at、tr_available_at，
不能仅靠manifest中的“已核验”声明推断时间戳。validate-data会同时检查这些时钟。
当前决策时间适配器保守限定为日历月末UTC日期；尚不支持最后交易日/实际执行日映射，也不进行交易回测。
合成配置缺时间戳时明确采用月末23:59:59 UTC，仅用于工程验证；真实配置绝不生成该假定。
若某历史TR或其派生特征在当时decision_at之后才可得，对应训练行/预测起点不可用；标签还需通过终点与实际可得时间双重筛选。
外部字段的select_asof接口校验逐字段unit/currency/definition及release/vintage/available时间，返回含原始记录ID的结果；
该接口尚未作为宏观/估值特征进入模型。嵌套调参和最终冻结审计尚未实现，现有模型参数预先固定。

## P1估值、区间与集成扩展

```powershell
python -m pytest -q
python -m index_forecast.cli backtest --config config/p1_extensions_synthetic.yaml
```

新增结果进入outputs/p1_extensions_synthetic_runs独立目录；真实数据配置为config/p1_extensions_real.yaml。
扩展只支持development_prequential，明确拒绝final_audit，不能将在线权重更新称作最终冻结测试。
集成包括等权、非负权重和向均值收缩；权重使用过去成熟OOF结果，rho使用过去实际生成的加权集成预测。
缺少60条/5个非重叠区间则加权回退等权、收缩回退历史均值，均记录状态；缺少候选不静默重分配权重。
80%经验区间需60条成熟残差和5个非重叠区间；95%需120条和10个。
样本不足时留空；这些研究门槛不保证统计覆盖，也不能把非重叠区间当作独立经济周期。
区间的log、绝对CAGR、相对财富比年化增长分别命名；数值溢出标记后留空。
估值分解使用当时已公布PE/EPS/股息与历史EPS增长；lambda预先固定，默认1表示不预测估值变化。
真实估值字段另须manifest.valuation_fields_verified及逐字段来源、单位、定义和可得性核验声明；软件不替代独立核验。
当前主样本缺EPS/股息和估值时间戳，因此完整样本运行不会产生估值分解预测；成功路径仅由完整合成测试数据验证。

新增产物：ensemble_forecasts.csv、ensemble_audit.json、prediction_intervals.csv、calibration_audit.json、
interval_metrics.csv、extensions_metrics.csv、valuation_diagnostics.csv、valuation_forecasts.csv及extensions_report.md。
所有派生产物继承synthetic/real、输入/协议哈希和run_id。
扩展详情与当前限制见[交付记录](docs/p1_extensions_delivery.md)。

## 策略、定投现金流与研究图表

```powershell
python -m pytest -q
python -m index_forecast.cli backtest --config config/p1_strategy_synthetic.yaml
```

产物在outputs/p1_strategy_synthetic_runs的新运行目录：strategy_metrics.csv、strategy_ledger.csv、strategy_cashflows.csv、
strategy_signals.csv、portfolio_policy.json、strategy_report.md，以及figures/、chart_manifest.json和figures_report.md。
真实数据入口config/p1_strategy_real.yaml默认禁止合成回退，但目前缺真实CSV/manifest。

账本是月度总收益指数代理，不能直接成交，不代表基金或券商可执行收益。
一次性投入与定投分组，分别比较SPX、NDX、50/50年度再平衡、战略新增资金与有限倾斜新增资金。
成本0/5/20/50bp和倾斜2/5/10个百分点均为预先规定的敏感性情景，不是实际费用或个性化配置。
只有信号严格早于执行时点才可用；月度数据最早用下一月末收盘代理价，季度更新且信号超3个月失效。
默认只影响新增资金，不卖出已有仓位。证据非A/B、路径冲突或区间缺失/含0则保持战略规则。
所有当前模型证据D，因此真实运行的合成主样本不会触发模型倾斜，不能宣称倾斜模型创造收益。

每月先估值旧持仓，再记入金，再交易扣费；CSV逐笔保存资金和持仓守恒。
图表使用剔除外部现金流的TWR单位净值，不把累计账户金额当投资收益；另列实际日期/365的XIRR。
潜在多根或无根的XIRR明确不可用，夏普因缺无风险利率留空；未恢复回撤标记右删失。
总收益指数、分数单位、月末模拟时钟、0现金利息和期末标记价值均为研究假设，未模拟真实产品限额、税费和流动性。

图表标注SYNTHETIC、期间、单位、OOS/历史描述，逐图导出计算源表和SHA-256。
预测区间不可用时只画可用率并明确覆盖率NA，不绘制虚构区间；缺估值/价格对照的图在清单中说明原因。
详细交付与限制见[策略与图表交付](docs/p1_strategy_delivery.md)。

## 输出与解释

每次运行保存到 `outputs/runs/<run_id>/`；合成配置保存到 `outputs/synthetic_runs/<run_id>/`：

- 配置、来源manifest、数据哈希、源码zip快照、环境版本、运行状态与耗时；
- 数据质量JSON/Markdown（字段缺失、覆盖、重复、缺月、单位、异常变动、共同样本）；
- dataset.csv、target_summary.csv；
- forecasts.csv（历史样本外、真实值/预测值/CAGR/误差/训练截止）；
- backtest_metrics.csv（RMSE/MAE/方向命中/OOS R²/非重叠区间数）；
- model_parameters.json（所有起点训练日期、Scaler参数、模型参数/系数）；
- skipped_origins.csv、report.md、run_metadata.json、run.log；失败时failure.md。

基准是相同成熟标签训练行的年化对数收益均值。OLS/Ridge/Elastic Net使用过去12个月动量与波动率，四模型训练/评估样本一致。
训练标签终点严格早于预测日（可另加embargo），按日历月精确对齐，训练内标准化，固定参数，不用测试表现调参。
后续在线更新允许已成熟的过去评估标签进入训练，不能据此声称是完全冻结的最终测试模型。
不同模型R²比较只对相同预测日；零基准误差时R²为NA，不捏造0或显著性。
测试未来价格扰动不影响过去特征/预测；改变未来真实结果会改变事后误差，这是正常的。

## 状态与限制

P0已实现，可通过合成样本验证流程。真实市场研究尚未运行：没有两个指数经过核验的真实总收益历史。
真实CPI/估值/盈利预期、历史版本和许可未取得。相关目标可在字段缺失时保留NA，不伪造。
P1：相对双路径、基础可得性审计、固定参数估值、经验区间、开发期集成、月度指数代理策略与8类研究图已实现并可合成验证；估值参数内层选择、HAC/区块推断、最终冻结审计和真实产品交易仍待实施。
P2：Random Forest/XGBoost等尚未实施。
不输出HAC/区块自助显著性；不将重叠月度标签数当作独立周期；7/10年证据有限。
所有现有输出证据评级D；不支持投资策略效果或当前市场预测。详见每次报告“限制”部分。
