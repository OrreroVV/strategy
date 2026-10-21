# P1基础接口与相对双路径交付

日期：2026-10-19。完成范围：P1-01的基础可得性/审计接口，以及P1-02固定参数相对收益双路径。
这不是整个P1完成；真实市场数据仍为0，所有新运行均为合成工程验证。

## 已实现

- feature_registry.py：版本化的绝对/相对趋势特征白名单与定义哈希。
- point_in_time.py：字段级release/vintage/available时间、单位与定义校验，返回带原记录ID的as-of结果。
- splits.py：按日历标签终点purge，并检查标签实际可得时间及历史特征是否在当时可得。
- prediction_ledger.py：新建文件拒绝覆盖、同预测身份拒绝重复、信号字段白名单、时间边界校验。
- models/relative.py：历史均值、OLS、Ridge、Elastic Net的直接/间接相对模型，固定参数、共同训练与预测起点。
- CLI schema_version=2：独立配置、相对结果/指标/比较/覆盖损失、训练参数、预测日志和协议快照。

相对主目标为年化对数收益差，不混同CAGR差。
间接模型的两个绝对预测来自同一共同训练样本；直接路径不能唯一确定两指数CAGR差，该字段保持空值。
缺失或未来数据不被补成真实观测；每个候选预测日起点的跳过状态单独保留。

## 运行入口

在研究目录，用已安装本项目的解释器执行：

```powershell
../../.venv/Scripts/python.exe -m pytest -q
../../.venv/Scripts/python.exe -m index_forecast.cli validate-data --config config/p1_synthetic.yaml
../../.venv/Scripts/python.exe -m index_forecast.cli backtest --config config/p1_synthetic.yaml
```

测试数据复用data/sample/SYNTHETIC_TEST_ONLY.csv，不覆盖raw或以前运行。
结果进入outputs/p1_synthetic_runs的独立运行目录；真实入口为config/p1_real.yaml，缺数据必须报错。
原P0配置仍支持，其回归验证必须继续通过。
本轮未增加依赖；继续使用现有pandas/numpy/scikit-learn/PyYAML/pytest。

## 验证范围

新增测试覆盖发布时间与供应商延迟、未来vintage、字段单位/定义冲突、缺时区、延迟标签、延迟历史价格、
相对双路径共同样本、未来扰动不变性、缺失一侧、缺少成熟训练数据、CAGR单位、非配对评价拒绝、
预测日志重复/覆盖/未来信息/未注册字段拒绝，以及v2 CLI和协议哈希集成。
最终实际执行数量、退出码、运行目录和产物复核以本文件末尾验证记录及outputs/verification内对应记录为准。
设计中的测试矩阵不是已执行测试数量，未实现模块不计为完成。

## 明确限制

P1-01仍未实现嵌套调参、最终冻结审计、真实交易日执行映射、外部宏观/盈利特征入模。
当前模型参数固定，因此没有以最终测试或未来数据调参。
select_asof可供独立接口调用，但不能据此声称已经取得真实vintage或核验供应商的历史版本。
真实P1主表须提供decision_at/tr_available_at且来自可核验数据源；不能从缺失时间戳推断同日可用。
当前decision_at保守限制为UTC日历月末当日；合成样本才允许自动构造23:59:59 UTC模拟时钟。
decision_at是历史模拟决策时点，recorded_at是本次程序写入时点，记录不是当年实际发布的预测。
全部输出证据D；7/10年证据有限，未提供区间、概率、统计显著性、真实模型增益或投资收益。
估值分解/收缩、预测区间、集成、策略、图表、RF/XGBoost均未在本轮实现。

## 本次最终执行记录

- 自动化测试：**64 passed**；原P0的36项均保留并通过。
- 验证日志：`outputs/verification/p1_foundation_20261019T022223_c72f00`。
- P1最终运行：`outputs/p1_synthetic_runs/20261019T022240_2623a6d2`，报告为relative_report.md。
- 产出312条相对预测、32行指标、156条逐期双路径比较；64个候选起点中39个可评价，其余原因保存在cohort_coverage.csv。
- 两路径训练日期一致、日志不含真实结果、标签/特征时间边界、源码快照和输入哈希均经独立脚本复核。
- P0旧配置重跑成功；与原P0运行比较，去除运行ID后预测及误差数值在1e-12相对容差内一致。
- config/p1_real.yaml的validate-data因真实CSV/manifest缺失返回退出码2，无合成回退。
