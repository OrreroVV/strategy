# 数据字典

| 字段 | 含义 | 单位/口径 |
| --- | --- | --- |
| price_close | 沪深300价格指数月末收盘 | 指数点 |
| stock_tr_close | 沪深300全收益指数月末收盘 | 含分红再投资 |
| bond_tr_close | 中证全债指数月末收盘 | 债券总回报基准 |
| pe_ttm | 沪深300滚动市盈率 | 中证官网口径 |
| yield_10y_pct | 10年期国债收益率 | 百分数，如2.5表示2.5% |
| earnings_index | price_close / pe_ttm | 指数等价盈利 |
| earnings_norm_36m | 指数等价盈利36个月滚动中位数 | 同指数点单位 |
| erp | 1/PE - 国债收益率 | 小数 |
| pe_pct_5y / erp_pct_5y | 相对此前60个月的实时百分位 | 0—1，只用过去数据 |
| pe_pct_10y / erp_pct_10y | 相对此前120个月的实时百分位 | 0—1，只用过去数据 |
| pe_cond_qXX | 条件分位数回归估计的PE | 倍数 |
| boundary_qXX | 标准化盈利 × 条件PE | 指数点 |
| gap_qXX | 实际点位 / 动态边界 - 1 | 小数 |
| S1_low_pe | 5年PE百分位≤10% | 布尔 |
| S2_high_erp | 5年ERP百分位≥90% | 布尔 |
| S3_below_dynamic_q10 | 点位低于条件10%边界 | 布尔 |
| S4_quality_adjusted | S2或S3且标准化盈利同比未低于-10% | 布尔 |
| MVP_combo | S1与S2同时触发 | 布尔；不是完整S5 |

注意：免费官方历史接口没有完整PB、公告日ROE与股息率序列，因此这些字段没有被推测或填补。
