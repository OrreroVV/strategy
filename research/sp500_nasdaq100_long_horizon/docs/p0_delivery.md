# P0交付与验证记录

日期：2026-10-19，Asia/Shanghai。完成范围为P0工程框架；不是完整实证研究或当前市场预测。
已完整阅读用户提供的实现规格说明，并检查根目录AGENTS、目录结构、现有数据与依赖。
根目录Git检查结果为“not a git repository”；已有沪深300研究未修改。

## 实际执行结果

- 最终自动化测试：**36 passed**，详见 `outputs/verification/pytest.txt`、`pytest.xml`。
- 首次测试在实现模块前运行，预期为模块缺失；随后修正一处测试数组断言和一处源码快照路径问题，再扩展测试并全部通过。
- `make-sample`：创建1104条明确标注SYNTHETIC_TEST_ONLY的合成月度观察，1980-01至2025-12，每指数552条。
- `validate-data --config config/synthetic.yaml`：通过。
- `build-dataset --config config/synthetic.yaml`：执行成功，构建四期限标签与因果特征。
- 最终 `backtest --config config/synthetic.yaml`：312条合成历史样本外模型预测、32行指标，四种模型、两个指数、四个期限。
- 最终运行目录：`outputs/synthetic_runs/20261019T020821_69a6b78e/`，Markdown报告为该目录的report.md。
- `validate-data --config config/default.yaml`：因真实CSV及manifest缺失明确失败，非零退出码；没有隐式合成回退。
- 失败记录：`outputs/runs/20261019T020658_72b4334f/`，保留failure.md及运行元数据。
- 独立产物复核：`outputs/verification/artifact_checks.json`，核实标签成熟度、四模型共同预测日、源码快照哈希、合成标记及原始测试输入未被改写。
- 环境已安装本项目；新增scikit-learn/PyYAML/pytest及其所需依赖，实测版本记录在 `outputs/verification/environment.txt`。

## P0实现检查

- [x] 独立研究目录、预先研究计划、配置、数据字典与来源核验记录。
- [x] CSV导入、字段映射、来源manifest与SHA-256、真实/合成隔离。
- [x] 字段类型、单位、日期唯一、缺失、缺月、异常变动、共同样本诊断。
- [x] 36/60/84/120个月名义年化对数收益、CAGR、实际收益、相对收益及估值变化历史标签。
- [x] 日历月精确配对；终点缺失时保留NA。
- [x] 扩展/滚动时间序列窗口、严格标签成熟度、purge及可配置额外embargo。
- [x] 历史平均、OLS、Ridge、Elastic Net，同一训练与评估样本。
- [x] 仅在训练窗口拟合标准化，固定参数，无全样本调参。
- [x] 未来数据扰动、时间边界、as-of发布/版本、禁止标签列、复现性与CLI集成测试。
- [x] RMSE、MAE、方向命中率、相对同期基准OOS R²、逐期误差、标签及非重叠区间数量。
- [x] Markdown报告、训练明细、系数、参数、配置/来源/源码快照、日志和失败记录。

## 真实数据与未完成事项

**真实行情实际覆盖：0。没有真实回测表现或当前市场预测。**
合成数据上的指标只证明流程运行，不能支持任何模型具有经济预测能力的结论。
还需取得并核验SPX/NDX同口径USD gross total return历史与许可；接入方式见README与data_sources。
真实CPI/估值与历史发布版本尚未取得；当前相关字段都是合成测试值。

P1收益分解、估值收缩、相对预测直接/间接路径、预测区间、集成、策略与图表未实现。
P2复杂机器学习未实施。未执行真实经济稳健性或HAC/区块自助推断，不报告显著性。
规格的“最终第一版研究框架”全部验收项尚未满足；本次完成的是用户优先要求的P0工程范围。
