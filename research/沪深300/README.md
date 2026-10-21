# 沪深300长期估值底部研究

本项目把研究方案第六节落地为可复现的数据、模型、回测、图表和月度面板。

## 运行

```powershell
.\.venv\Scripts\python.exe src\run_research.py
```

强制刷新官网数据：

```powershell
.\.venv\Scripts\python.exe src\run_research.py --refresh
```

## 主要文件

- `research_report.md`：结论、模型评价、回测摘要和局限。
- `dashboard.html`：月度监测面板。
- `data/processed/`：清洗后的日度和月度数据。
- `outputs/`：事件研究、汇总、参数、敏感性表和图。

## 复现说明

脚本从中证指数官网接口读取 000300、H00300、N11001；2011—2014年国债收益率读取中债历史曲线，2015年以后读取中国人民银行年度统计表。网络失败时保留已缓存原始文件。模型上限固定为2026-09-30，并以月度统计表最新已发布月末作为实际联合模型截止日。
