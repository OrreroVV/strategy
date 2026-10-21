# 数据来源与实际取得状态

核验日期：2026-10-19（Asia/Shanghai）。这里记录页面访问情况，不代表已获得完整历史数据库或再分发许可。
工作区已有沪深300数据；没有发现本研究所需的两个美国指数同口径总收益历史CSV。
真实数据实际覆盖：**0条**。未下载真实行情，未调用付费服务、使用凭据或购买数据。

| 来源 | 本次访问核验 | 密钥/授权/限制 | 本项目状态 |
| --- | --- | --- | --- |
| [S&P DJI S&P 500](https://www.spglobal.com/spdji/en/indices/equity/sp-500/) | 官方指数页面可读 | 页面含登录入口；完整历史总收益访问权限/许可尚未核验，不能假定免费 | TR序列ID、覆盖、历史版本、授权待提供；禁止以价格指数替代 |
| [Nasdaq XNDX](https://indexes.nasdaq.com/Index/Overview/XNDX) | 官方页面明确 NASDAQ-100 Total Return、USD | 页面提供数据订阅/entitlements入口；完整历史接口授权未核验；官方提示部分指数上线前为回溯历史 | XNDX定义可核实；尚未取得历史文件与上线前样本边界 |
| [Shiller Yale](https://www.econ.yale.edu/~shiller/data.htm) | 本次网页工具返回 Internal Error，未读取数据 | 本次无法核验许可/自动下载限制，密钥要求未核验 | 不可用；不能把Shiller市场数据当NDX历史 |
| [FRED API key](https://fred.stlouisfed.org/docs/api/api_key.html) | 官方说明可读，所有Web Services请求需要API key | [FRED条款](https://fred.stlouisfed.org/legal/)可读，第三方系列可能有额外授权限制 | 未获取密钥/未发起数据调用；各系列频率、单位、发布日期待核验 |
| [ALFRED](https://alfred.stlouisfed.org/) | 官方入口可读 | FRED/ALFRED Web Services遵循API密钥要求；具体历史版本覆盖需逐序列核查 | 未下载vintage；P0不使用宏观特征 |
| 历史分析师EPS/Forward PE | 未选定供应商，未访问 | 访问凭据、费用和历史版本许可均未核验 | 禁用，禁止当前值回填 |
| 历史成分/权重 | 未取得 | 授权和退市覆盖待核验 | 禁用，无当前成分重建历史 |
| QDII、FX、基金费用 | P0不涉及 | 未核验 | 未接入 |

## 当前测试样本

`data/sample/SYNTHETIC_TEST_ONLY.csv`由本项目 make-sample 生成，非市场数据。
SPX/NDX只是接口测试ID，随机游走/CPI/PE全是明确标记的合成值。
生成器、随机种子、生成时间、SHA-256与字段定义见相邻manifest；日期1980-01至2025-12不代表真实可取得历史覆盖。
它只能验证软件运行，不能验证经济假设、选模型或提供投资预测。

## 真实CSV接入步骤

1. 从有权使用的数据源取得两个指数gross total return、USD的月末快照；保留原始下载文件，不覆盖。
2. 检查指数上线日、回溯样本、分红再投资、毛/净总收益、修订政策、时区和授权；记录字段级元数据。
3. 可复现转换至独立CSV；若已是标准格式直接导入；日期规范化为日历月末，注明原始最后交易日映射。
4. 用新的数据目录保存CSV与manifest；记录原始URL/序列、获取时间、覆盖、版本、许可、SHA-256及抽样核验。
5. 复制config/default.yaml至该项目config目录的新配置，指向快照，保持allow_synthetic=false。
6. 运行validate-data先检查诊断，再build-dataset/backtest。不要用质量失败的数据训练。

没有可核验数据时保持缺口报告，不以SPY/QQQ基金复权价格或NDX价格指数冒充官方总收益指数。
