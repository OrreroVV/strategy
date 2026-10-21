import json
import pandas as pd


def md_table(frame):
    if frame.empty: return '不可用：没有符合条件的样本。'
    def clean(x):
        if isinstance(x,float): return 'NA' if pd.isna(x) else f'{x:.6f}'
        return str(x).replace('|','/').replace('\n',' ')
    return '\n'.join(['| '+' | '.join(frame.columns)+' |',
        '| '+' | '.join(['---']*len(frame.columns))+' |']+
        ['| '+' | '.join(clean(x) for x in row)+' |' for row in frame.itertuples(index=False,name=None)])


def quality_markdown(q):
    return '# 数据质量诊断\n\n自动检查结果；不等同于对数据提供方的独立审计。\n\n```json\n'+json.dumps(q,ensure_ascii=False,indent=2,default=str)+'\n```\n'


def report(config, quality, manifest, summary, metrics, forecasts, skips, metadata):
    synthetic = manifest['data_kind'] == 'synthetic'
    relative_enabled = config.get('relative',{}).get('enabled',False)
    extension_note = '本次P1估值/区间/集成的独立结果与不可用原因见 extensions_report.md。' if config.get('extensions',{}).get('enabled',False) else '本配置未启用P1估值/区间/集成扩展。'
    portfolio_note = '本次月度指数代理策略模拟见strategy_report.md；不属于可交易产品实际回测。' if config.get('portfolio',{}).get('enabled',False) else '本次未启用策略模拟。'
    chart_note = '本次研究图表见figures_report.md；缺失图表及原因见chart_manifest.json。' if config.get('plots',{}).get('enabled',False) else '本次未启用图表。'
    label = 'SYNTHETIC_TEST_ONLY — 仅为合成数据工程验证，无真实市场结论' if synthetic else '真实数据历史样本外研究 — 数据来源声明仍须人工核验'
    return f'''# 标普500与纳斯达克100长期预测：P0运行报告

**{label}**

## 1. 执行摘要
运行 `{metadata['run_id']}`：{metadata['status']}。产出 {len(forecasts)} 条历史样本外模型预测。
本次没有生成当前市场预测；所有指标均是本次输入数据的实际计算结果。
{extension_note}
{portfolio_note} {chart_note}
{'真实行情覆盖：0。合成输出不得用于投资结论、模型有效性评级或市场预测。' if synthetic else '数据来源和实际覆盖见下一节；指标不代表确定的未来效果。'}

## 2. 数据范围、来源、频率和缺失情况
月度、美元、分红再投资 gross total return；观察日期为日历月末，代表最后交易日收盘后信息。
提供方：{manifest['provider']}；来源：{manifest['url']}；获取时间：{manifest['retrieved_at']}。
许可声明：{manifest['license']}。原始CSV SHA-256：`{manifest['sha256']}`。
数据质量详细结果见 `data_quality_report.md`、`data_quality.json`，包含各字段覆盖、缺失率、缺月、异常变动与共同日期。
缺失观察不填补，缺失特征行从四个模型共同训练样本中剔除；被跳过预测另存 `skipped_origins.csv`（{len(skips)}条）。

## 3. 收益口径与目标变量
年化对数收益 y=12/H*ln(TR[t+H]/TR[t])；CAGR=exp(y)-1；本次期限{config['targets']['horizons']}月。
实际历史标签减去同期限CPI年化对数增长；相对标签=NDX-SPX；估值变化=ln(PE[t+H]/PE[t])。
未来CPI、PE仅用作标签。缺失字段/终点保留NA。按日历月份配对，不以行号跨越缺月。

## 4. 历史收益与估值描述、样本量
`dataset.csv` 保存每个标签与因果特征；`target_summary.csv` 保存可用/缺失和最新时点前已成熟标签数。
以下为重叠标签数量，不能解释为独立周期数量：

{md_table(summary.drop(columns=['data_kind','run_id'],errors='ignore'))}

估值历史分布未纳入P0；不能由合成估值推断市场贵贱。

## 5. 收益分解
本文件不列收益分解。{extension_note} 未因缺少真实EPS、股息或估值而补造分解结果。

## 6. 基准与7. 计量模型
历史平均基准使用同一训练窗口内成熟年化对数收益标签的均值。
OLS/Ridge/Elastic Net仅用过去12个月对数动量和月对数收益标准差*sqrt(12)。
每次拟合仅在共同训练样本内拟合StandardScaler；不插补、不做全样本特征选择。
正则化参数预先固定：Ridge alpha={config['models']['ridge_alpha']}；Elastic Net alpha={config['models']['elastic_alpha']}，l1_ratio={config['models']['elastic_l1_ratio']}。
未做超参数搜索；不得根据下表调整后再称同一评估期为独立测试。
系数、标准化均值/尺度、训练起止及完整训练日期保存在 `model_parameters.json`。

## 8. 机器学习与9. 集成模型
Random Forest/XGBoost未执行。{extension_note}

## 10. 直接与间接相对收益
{'本次已运行P1双路径模块；共同样本指标、单位区别与审计记录详见 relative_report.md 和 relative_*.csv。' if relative_enabled else '本配置仅执行P0；已实现历史相对标签，相对双路径须通过schema_version=2配置另行启用。'}

## 11. 严格时间序列样本外结果
预测起点从 {config['validation']['holdout_start']} 起，步长 {config['validation']['step_months']} 月；最少 {config['validation']['min_train']} 个成熟且特征完整训练标签。
标签终点严格早于预测日减 {config['validation']['embargo_months']} 月；排除所有与当前预测区间重叠的训练标签。
训练窗口：{'扩展窗口' if config['validation'].get('window_months') is None else str(config['validation']['window_months'])+'月滚动窗口'}。
此前评估标签只有成熟后才可进入后续训练；这是预先定义的在线更新。
下表RMSE/MAE以年化对数收益小数计；方向命中率只作辅助。样本外R²=1-SSE模型/SSE同期历史均值，负值如实保留。

{md_table(metrics.drop(columns=['data_kind','run_id'],errors='ignore'))}

逐期实际值、预测值、误差保存于 `forecasts.csv`，output_type=historical_oos；无样本内拟合表现混入。
disjoint_outcome_windows为贪心选取互不重叠结果区间数，仍不意味着独立市场状态。

## 12. 预测区间与概率校准
本文件的P0基模型CSV区间列留空。{extension_note} 不输出概率。
没有将模型分歧当作统计区间，也未执行HAC/区块自助置信推断，不报告显著性。
所有输出证据评级D；尤其7/10年样本外证据有限，区间估计证据有限。

## 13. 策略与交易成本
{portfolio_note} 夏普在无核验无风险利率时保留NA。美元指数收益不能当作人民币QDII收益。

## 14. 数据泄漏检查
运行时逐起点断言 max_training_label_end < forecast_date-embargo；审计记录保存在 model_parameters.json。
特征注册白名单阻止标签列进入模型；CLI从原始TR重新构建因果特征。
外部宏观特征未启用；as-of接口同时检查observation/release/vintage，不允许用当前修订值回填。
自动化测试结果单独见 outputs/verification；本报告只记录实际回测运行，不将未执行测试声称为通过。

## 15. 稳健性与敏感性
P0测试包含未来扰动不变性与复现性；这些是工程测试，不是经济稳健性证据。
替代来源、市场阶段、特征消融、滚动窗口敏感性尚未完成，不做稳健有效性结论。

## 16. 限制与未完成事项
真实总收益历史、历史时点估值/盈利预期及宏观版本尚需取得并独立核验。
来源manifest中的point_in_time_verified是数据提交者声明，程序无法自动证明历史没有事后修订。
指数上线前回溯值与实时指数值应在导入前核实、披露；成分股特征未使用。
未提供系数置信区间、真实产品交易或QDII收益。策略/图表是否运行见本报告开头及相应独立报告，其他模块是否启用见扩展说明。
月度重叠标签具有高度序列依赖，不以标签数夸大证据；研究预测相关性不能作因果结论。

## 17. 当前预测
未生成。合成样本永不支持当前真实市场预测，P0只做已成熟历史样本外评估。

## 18. 复现与元数据
命令：`python -m index_forecast.cli backtest --config {metadata['config_path']}`。
环境安装与测试命令见README；本次配置、依赖、Python/平台、代码哈希、耗时及来源见 config_snapshot.yaml、run_metadata.json。
所有运行独立目录保存，不覆盖已有结果；下载与训练分离，无隐式网络下载或付费调用。
'''
