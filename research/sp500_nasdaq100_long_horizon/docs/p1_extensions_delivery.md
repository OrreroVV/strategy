# P1估值、经验区间与集成交付

日期：2026-10-19。范围为P1-03/04的基础算法与诊断、P1-05开发期集成工程。
**真实行情仍为0；工程测试和合成结果不能证明市场预测有效。完整P1尚未完成。**

## 实现与接口

- models/valuation.py：当时可得的历史logPE中位数、固定lambda估值变化、历史EPS年化对数增长及log1p股息近似分解。
- uncertainty.py：仅用当时已成熟的同模型/目标/路径/版本OOS残差建立经验80%/95%区间，记录校准日期与截止。
- models/ensemble.py：等权、带均匀权重惩罚的非负和为1优化、向历史均值收缩；少样本显式回退。
- extensions.py：通过独立配置接入绝对收益和相对双路径回测，保留基模型结果，输出状态/审计/独立报告。

rho选择使用过去当时产生的加权预测，不能把当前权重套回历史后称样本外。
所有更新只读过去已成熟开发期结果；配置明确为development_prequential，final_audit会报错。
lambda、参考窗口、eta、历史门槛预先固定，不以本次样本误差调参。

## 数据与输出限制

主合成样本没有完整EPS、股息和估值可得时间，估值诊断返回缺失；不会填造这些列。
另有明确的完整合成临时测试样本验证估值成功路径；它只存在测试输出目录，不进入正式数据。
80%需60条成熟残差/5个非重叠区间，95%需120条/10个。主样本预计不足，允许全部区间NA。
这些门槛是研究设计，不是覆盖保证；覆盖率同时报告分母和区间可用率。
绝对CAGR与相对财富比年化增长分列；不从相对log差虚构两指数CAGR差。
数据kind、输入/协议哈希及run_id随产物保存；不覆盖任何既有运行或原始CSV。

## 复现命令

在研究目录使用已安装解释器：

```powershell
../../.venv/Scripts/python.exe -m pytest -q
../../.venv/Scripts/python.exe -m index_forecast.cli backtest --config config/p1_extensions_synthetic.yaml
```

结果位于outputs/p1_extensions_synthetic_runs的独立目录。
新增SciPy为显式直接依赖以使用已安装的SLSQP约束优化器；本轮未安装新包。
接口依据：[SciPy官方SLSQP文档](https://docs.scipy.org/doc/scipy/reference/optimize.minimize-slsqp.html)，2026-10-19核验。

## 失败与待办

首次命令行扩展回测发现时区混合导致评价失败，失败运行保留在outputs/p1_extensions_synthetic_runs/20261019T064139_4ca4bb12。
已将非重叠区间比较统一到UTC，并新增完整命令行集成测试；不删除失败记录。
未来扰动测试产生极端log值时曾出现expm1溢出警告，已改为保留有限log边界、转换值留空并记录numeric_overflow。
尚未实现估值参数嵌套选择、HAC/区块自助、最终冻结评估、策略/定投现金流、图表及复杂机器学习。
最终测试数量、运行ID及独立产物检查记录见下方追加的实际执行记录，不把设计清单算作已通过测试。

## 最终实际执行记录

- 自动化测试：**78 passed**；包括原有64项、14项新增公式/时间边界/集成测试。
- 验收目录：`outputs/verification/p1_extensions_20261019T064637_3a8e11`，保留pytest文本/XML、命令退出码和artifact_checks.json。
- 扩展运行：`outputs/p1_extensions_synthetic_runs/20261019T064712_9a2809a2`；独立报告extensions_report.md。
- 实际产出468条集成预测、1092条区间状态、112行扩展指标；权重非负且和为1。
- 主样本成熟残差不足，80%/95%边界全部NA，覆盖率NA、可用率0；加权全部显式回退等权，收缩全部显式回退基准。
- 128条估值诊断中78条缺必要字段、50条标签未成熟；估值预测0条，未补造数据。完整合成临时测试另验证成功路径。
- P0和相对P1旧配置重跑成功；去除运行身份字段，预测及误差与此前运行在1e-12相对容差内一致。
- 真实扩展配置validate-data因CSV/manifest缺失返回退出码2，没有自动回退合成数据。
