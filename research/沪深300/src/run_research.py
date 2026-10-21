from __future__ import annotations

import argparse
import io
import json
import math
import re
import time
import warnings
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import akshare as ak
import matplotlib
import numpy as np
import pandas as pd
import requests
import statsmodels.api as sm
from bs4 import BeautifulSoup
from jinja2 import Template

matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
OUTPUT = ROOT / "outputs"
FIGURES = OUTPUT / "figures"
PBC_BASE = "https://www.pbc.gov.cn"
PBC_STATS = f"{PBC_BASE}/diaochatongjisi/116219/116319/index.html"
LAST_COMPLETE_MONTH = pd.Timestamp("2026-09-30")
START_DATE = "20050101"
END_DATE = "20261016"
RNG = np.random.default_rng(20261016)
RUN_DATE = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()


def ensure_dirs() -> None:
    for path in (RAW, PROCESSED, OUTPUT, FIGURES):
        path.mkdir(parents=True, exist_ok=True)


def http_get(url: str, *, attempts: int = 6, timeout: int = 30) -> bytes:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; CSI300Research/1.0)"}
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response.content
        except Exception as exc:  # network mirrors can be intermittent
            last_exc = exc
            time.sleep(min(2 ** attempt, 12))
    raise RuntimeError(f"Download failed after {attempts} attempts: {url}") from last_exc


def fetch_csindex_series(code: str, cache_name: str, refresh: bool) -> pd.DataFrame:
    cache = RAW / cache_name
    if cache.exists() and not refresh:
        return pd.read_csv(cache, parse_dates=["date"])
    last_exc: Exception | None = None
    for attempt in range(6):
        try:
            raw = ak.stock_zh_index_hist_csindex(
                symbol=code, start_date=START_DATE, end_date=END_DATE
            )
            if raw.empty:
                raise ValueError(f"Empty CSIndex response for {code}")
            out = pd.DataFrame(
                {
                    "date": pd.to_datetime(raw.iloc[:, 0], errors="coerce"),
                    "open": pd.to_numeric(raw.iloc[:, 6], errors="coerce"),
                    "high": pd.to_numeric(raw.iloc[:, 7], errors="coerce"),
                    "low": pd.to_numeric(raw.iloc[:, 8], errors="coerce"),
                    "close": pd.to_numeric(raw.iloc[:, 9], errors="coerce"),
                    "pe_ttm": pd.to_numeric(raw.iloc[:, 15], errors="coerce"),
                }
            )
            out = out.dropna(subset=["date", "close"]).drop_duplicates("date", keep="last")
            out = out[out["date"] >= pd.Timestamp("2005-01-01")].sort_values("date")
            out.to_csv(cache, index=False, encoding="utf-8-sig")
            return out
        except Exception as exc:
            last_exc = exc
            time.sleep(min(2 ** attempt, 10))
    raise RuntimeError(f"Unable to fetch CSIndex series {code}") from last_exc


def find_year_pages() -> dict[int, str]:
    soup = BeautifulSoup(http_get(PBC_STATS), "html.parser")
    pages: dict[int, str] = {}
    for anchor in soup.find_all("a", href=True):
        text = anchor.get_text(" ", strip=True)
        href = anchor["href"]
        if "/diaochatongjisi/116219/116319/" not in href:
            continue
        match = re.search(r"(20(?:1[1-9]|2[0-6]))", text)
        if match:
            pages[int(match.group(1))] = urljoin(PBC_BASE, href)
    return pages


def pbc_yield_xls_url(year_url: str) -> str:
    year_soup = BeautifulSoup(http_get(year_url), "html.parser")
    financial_href = None
    for anchor in year_soup.find_all("a", href=True):
        if "Financial Market Statistics" in anchor.get_text(" ", strip=True):
            financial_href = anchor["href"]
            break
    if financial_href is None:
        raise ValueError(f"Financial Market Statistics link not found: {year_url}")
    financial_url = urljoin(PBC_BASE, financial_href)
    financial_soup = BeautifulSoup(http_get(financial_url), "html.parser")
    marker = financial_soup.find(
        string=lambda value: value and "Statistics of Chinabond Government" in value
    )
    if marker is None:
        raise ValueError(f"Chinabond yield table not found: {financial_url}")
    row = marker.find_parent("tr")
    anchors = row.find_all("a", href=True)
    xls = next((a["href"] for a in anchors if a.get_text(strip=True).lower() == "xml"), None)
    if xls is None:
        xls = next((a["href"] for a in anchors if a["href"].lower().endswith((".xls", ".xlsx"))), None)
    if xls is None:
        raise ValueError(f"Yield spreadsheet not found: {financial_url}")
    return urljoin(PBC_BASE, xls)


def parse_pbc_yield_xls(content: bytes, year: int) -> pd.DataFrame:
    book = pd.ExcelFile(io.BytesIO(content))
    raw = pd.read_excel(book, sheet_name=book.sheet_names[0], header=None)
    header_row = None
    ten_year_col = None
    for row_idx in range(min(12, len(raw))):
        for col_idx, value in enumerate(raw.iloc[row_idx]):
            if "10-Year" in str(value):
                header_row, ten_year_col = row_idx, col_idx
                break
        if ten_year_col is not None:
            break
    if ten_year_col is None:
        # Historical sheets use the stable layout date + 1D/1Y/3Y/5Y/7Y/10Y/30Y.
        ten_year_col = 6
        header_row = 5
    rows: list[tuple[pd.Timestamp, float]] = []
    for _, row in raw.iloc[header_row + 1 :].iterrows():
        label = str(row.iloc[0]).strip()
        if re.fullmatch(r"\d{4}\.1", label):
            # Excel coerces strings such as 2025.10 to the float 2025.1.
            label = f"{label}0"
        if not re.fullmatch(r"\d{4}\.\d{2}", label):
            continue
        value = pd.to_numeric(row.iloc[ten_year_col], errors="coerce")
        if pd.isna(value):
            continue
        period = pd.Period(label.replace(".", "-"), freq="M")
        rows.append((period.to_timestamp("M"), float(value)))
    if not rows:
        raise ValueError(f"No 10Y observations parsed for {year}")
    return pd.DataFrame(rows, columns=["date", "yield_10y_pct"])


def fetch_pbc_yields(refresh: bool) -> pd.DataFrame:
    combined = PROCESSED / "pbc_10y_monthly.csv"
    if combined.exists() and not refresh:
        existing = pd.read_csv(combined, parse_dates=["date"])
        if existing["date"].min() <= pd.Timestamp("2011-01-31"):
            return existing
    pages = find_year_pages()
    frames: list[pd.DataFrame] = []
    failures: dict[int, str] = {}
    for year in range(2015, 2027):
        cache = RAW / f"pbc_yield_{year}.xls"
        try:
            if not cache.exists() or refresh:
                xls_url = pbc_yield_xls_url(pages[year])
                content = http_get(xls_url)
                cache.write_bytes(content)
                (RAW / f"pbc_yield_{year}.url.txt").write_text(xls_url, encoding="utf-8")
            frames.append(parse_pbc_yield_xls(cache.read_bytes(), year))
        except Exception as exc:
            failures[year] = str(exc)
    if not frames:
        raise RuntimeError(f"All PBC yield downloads failed: {failures}")
    out = (
        pd.concat(frames, ignore_index=True)
        .drop_duplicates("date", keep="last")
        .sort_values("date")
    )
    early_frames: list[pd.DataFrame] = []
    for year in range(2011, 2015):
        cache = RAW / f"chinabond_yield_{year}.csv"
        if cache.exists() and not refresh:
            early = pd.read_csv(cache, parse_dates=["date"])
        else:
            last_exc: Exception | None = None
            raw = None
            for attempt in range(6):
                try:
                    raw = ak.bond_china_yield(
                        start_date=f"{year}0101", end_date=f"{year}1231"
                    )
                    break
                except Exception as exc:
                    last_exc = exc
                    time.sleep(min(2 ** attempt, 12))
            if raw is None:
                raise RuntimeError(f"Unable to fetch ChinaBond yields for {year}") from last_exc
            # The endpoint returns government, enterprise and CP/MTN curves.
            # Government bonds have the lowest 10Y yield in this three-curve set.
            early = pd.DataFrame(
                {
                    "date": pd.to_datetime(raw.iloc[:, 1], errors="coerce"),
                    "yield_10y_pct": pd.to_numeric(raw.iloc[:, 8], errors="coerce"),
                }
            ).dropna()
            early = early.loc[early.groupby("date")["yield_10y_pct"].idxmin()].sort_values("date")
            early.to_csv(cache, index=False, encoding="utf-8-sig")
        monthly_early = (
            early.set_index("date")["yield_10y_pct"].resample("ME").last().reset_index()
        )
        early_frames.append(monthly_early)
    out = (
        pd.concat([*early_frames, out], ignore_index=True)
        .drop_duplicates("date", keep="last")
        .sort_values("date")
    )
    out = out[out["date"] <= LAST_COMPLETE_MONTH]
    out.to_csv(combined, index=False, encoding="utf-8-sig")
    (OUTPUT / "pbc_download_failures.json").write_text(
        json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return out


def to_monthly_last(df: pd.DataFrame, prefix: str, keep_pe: bool = False) -> pd.DataFrame:
    temp = df.copy().set_index("date").sort_index()
    columns = {"close": f"{prefix}_close"}
    if keep_pe:
        columns["pe_ttm"] = "pe_ttm"
    monthly = temp[list(columns)].resample("ME").last().rename(columns=columns)
    obs_date = temp.assign(obs_date=temp.index)["obs_date"].resample("ME").last()
    monthly[f"{prefix}_obs_date"] = obs_date
    return monthly


def prior_percentile(series: pd.Series, window: int, min_periods: int) -> pd.Series:
    values = series.to_numpy(dtype=float)
    result = np.full(len(values), np.nan)
    for idx, current in enumerate(values):
        start = max(0, idx - window)
        prior = values[start:idx]
        prior = prior[np.isfinite(prior)]
        if np.isfinite(current) and len(prior) >= min_periods:
            result[idx] = np.mean(prior <= current)
    return pd.Series(result, index=series.index)


def build_monthly(
    price: pd.DataFrame, tri: pd.DataFrame, bond: pd.DataFrame, yields: pd.DataFrame
) -> pd.DataFrame:
    monthly = to_monthly_last(price, "price", keep_pe=True)
    monthly = monthly.join(to_monthly_last(tri, "stock_tr"), how="outer")
    monthly = monthly.join(to_monthly_last(bond, "bond_tr"), how="outer")
    y = yields.set_index("date")["yield_10y_pct"]
    monthly = monthly.join(y, how="left")
    monthly = monthly.loc[:LAST_COMPLETE_MONTH].copy()
    monthly["earnings_index"] = monthly["price_close"] / monthly["pe_ttm"]
    monthly["earnings_norm_36m"] = monthly["earnings_index"].rolling(36, min_periods=24).median()
    monthly["earnings_growth_yoy"] = monthly["earnings_norm_36m"].pct_change(12)
    monthly["earnings_deterioration"] = monthly["earnings_growth_yoy"] < -0.10
    monthly["erp"] = 1.0 / monthly["pe_ttm"] - monthly["yield_10y_pct"] / 100.0
    for q in (0.05, 0.10, 0.15):
        q_label = int(q * 100)
        prior_q = monthly["pe_ttm"].shift(1).expanding(min_periods=12).quantile(q)
        monthly[f"pe_history_q{q_label:02d}"] = prior_q
        monthly[f"history_boundary_q{q_label:02d}"] = monthly["earnings_index"] * prior_q

    for window, minimum in ((60, 36), (120, 60)):
        label = f"{window // 12}y"
        monthly[f"pe_pct_{label}"] = prior_percentile(monthly["pe_ttm"], window, minimum)
        monthly[f"erp_pct_{label}"] = prior_percentile(monthly["erp"], window, minimum)
        monthly[f"pe_q10_{label}"] = (
            monthly["pe_ttm"].shift(1).rolling(window, min_periods=minimum).quantile(0.10)
        )
        monthly[f"erp_q90_{label}"] = (
            monthly["erp"].shift(1).rolling(window, min_periods=minimum).quantile(0.90)
        )

    model = monthly.dropna(
        subset=["pe_ttm", "yield_10y_pct", "earnings_growth_yoy", "earnings_norm_36m"]
    ).copy()
    for tau in (0.05, 0.10, 0.15, 0.50):
        monthly[f"pe_cond_q{int(tau * 100):02d}"] = np.nan
    coef_rows: list[dict[str, float | str]] = []
    for idx in range(60, len(model)):
        train = model.iloc[:idx]
        current = model.iloc[[idx]]
        x_train = sm.add_constant(
            train[["yield_10y_pct", "earnings_growth_yoy"]], has_constant="add"
        )
        x_current = sm.add_constant(
            current[["yield_10y_pct", "earnings_growth_yoy"]], has_constant="add"
        )
        target = np.log(train["pe_ttm"])
        for tau in (0.05, 0.10, 0.15, 0.50):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                fit = sm.QuantReg(target, x_train).fit(q=tau, max_iter=3000, p_tol=1e-7)
            pred = float(np.exp(fit.predict(x_current).iloc[0]))
            col = f"pe_cond_q{int(tau * 100):02d}"
            monthly.loc[current.index[0], col] = pred
            coef_rows.append(
                {
                    "forecast_date": current.index[0].date().isoformat(),
                    "tau": tau,
                    "intercept": fit.params.get("const", np.nan),
                    "beta_yield_10y_pct": fit.params.get("yield_10y_pct", np.nan),
                    "beta_earnings_growth": fit.params.get("earnings_growth_yoy", np.nan),
                    "training_observations": len(train),
                }
            )
    for q in (5, 10, 15, 50):
        monthly[f"boundary_q{q:02d}"] = (
            monthly["earnings_norm_36m"] * monthly[f"pe_cond_q{q:02d}"]
        )
        monthly[f"gap_q{q:02d}"] = monthly["price_close"] / monthly[f"boundary_q{q:02d}"] - 1

    monthly["S1_low_pe"] = monthly["pe_pct_5y"] <= 0.10
    monthly["S2_high_erp"] = monthly["erp_pct_5y"] >= 0.90
    monthly["S3_below_dynamic_q10"] = monthly["gap_q10"] <= 0
    monthly["S4_quality_adjusted"] = (
        monthly["S2_high_erp"] | monthly["S3_below_dynamic_q10"]
    ) & ~monthly["earnings_deterioration"].fillna(True)
    monthly["MVP_combo"] = monthly["S1_low_pe"] & monthly["S2_high_erp"]
    monthly["S1_low_pe_10y"] = monthly["pe_pct_10y"] <= 0.10
    monthly["S2_high_erp_10y"] = monthly["erp_pct_10y"] >= 0.90
    monthly.index.name = "date"
    monthly.to_csv(PROCESSED / "monthly_model_data.csv", encoding="utf-8-sig")
    pd.DataFrame(coef_rows).to_csv(OUTPUT / "quantile_coefficients.csv", index=False, encoding="utf-8-sig")
    return monthly


def build_daily(price: pd.DataFrame, tri: pd.DataFrame, bond: pd.DataFrame) -> pd.DataFrame:
    daily = price.set_index("date")[["close"]].rename(columns={"close": "price"})
    daily = daily.join(
        tri.set_index("date")[["close"]].rename(columns={"close": "stock_tr"}), how="outer"
    )
    daily = daily.join(
        bond.set_index("date")[["close"]].rename(columns={"close": "bond_tr"}), how="outer"
    )
    daily = daily.sort_index().loc[: pd.Timestamp(END_DATE)]
    daily.to_csv(PROCESSED / "daily_market_data.csv", encoding="utf-8-sig")
    return daily


def first_on_or_after(index: pd.DatetimeIndex, target: pd.Timestamp) -> pd.Timestamp | None:
    position = index.searchsorted(target, side="left")
    if position >= len(index):
        return None
    return index[position]


def one_event(
    signal_name: str,
    signal_date: pd.Timestamp,
    daily: pd.DataFrame,
    horizon: int,
) -> dict[str, object] | None:
    usable = daily.dropna(subset=["stock_tr", "bond_tr"])
    entry = first_on_or_after(usable.index, signal_date + pd.Timedelta(days=1))
    if entry is None:
        return None
    exit_date = first_on_or_after(usable.index, entry + pd.DateOffset(months=horizon))
    if exit_date is None:
        return None
    stock_return = usable.loc[exit_date, "stock_tr"] / usable.loc[entry, "stock_tr"] - 1
    bond_return = usable.loc[exit_date, "bond_tr"] / usable.loc[entry, "bond_tr"] - 1
    years = horizon / 12
    stock_ann = (1 + stock_return) ** (1 / years) - 1
    bond_ann = (1 + bond_return) ** (1 / years) - 1
    path = usable.loc[entry:exit_date, "stock_tr"] / usable.loc[entry, "stock_tr"] - 1
    min_return = float(path.min())
    trough = path.idxmin()
    recovery = usable.loc[trough:exit_date, "stock_tr"]
    recovered = recovery[recovery >= usable.loc[entry, "stock_tr"]]
    recovery_days = (recovered.index[0] - entry).days if len(recovered) else np.nan
    return {
        "signal": signal_name,
        "signal_date": signal_date.date().isoformat(),
        "entry_date": entry.date().isoformat(),
        "exit_date": exit_date.date().isoformat(),
        "horizon_months": horizon,
        "stock_total_return": stock_return,
        "stock_ann_return": stock_ann,
        "bond_total_return": bond_return,
        "bond_ann_return": bond_ann,
        "ann_excess_return": stock_ann - bond_ann,
        "max_drawdown_from_entry": min_return,
        "fell_10pct": min_return <= -0.10,
        "fell_20pct": min_return <= -0.20,
        "recovery_days": recovery_days,
    }


def event_starts(signal: pd.Series) -> pd.DatetimeIndex:
    flag = signal.fillna(False).astype(bool)
    return flag.index[flag & ~flag.shift(1, fill_value=False)]


def bootstrap_ci(values: pd.Series, repetitions: int = 4000) -> tuple[float, float]:
    clean = values.dropna().to_numpy(dtype=float)
    if len(clean) < 2:
        return np.nan, np.nan
    draws = RNG.choice(clean, size=(repetitions, len(clean)), replace=True).mean(axis=1)
    return float(np.quantile(draws, 0.025)), float(np.quantile(draws, 0.975))


def run_backtest(monthly: pd.DataFrame, daily: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    signal_columns = [
        "S1_low_pe",
        "S2_high_erp",
        "S3_below_dynamic_q10",
        "S4_quality_adjusted",
        "MVP_combo",
        "S1_low_pe_10y",
        "S2_high_erp_10y",
    ]
    rows: list[dict[str, object]] = []
    for signal in signal_columns:
        for date in event_starts(monthly[signal]):
            for horizon in (12, 36, 60):
                result = one_event(signal, date, daily, horizon)
                if result:
                    rows.append(result)
    # Overlapping unconditional observations are explicitly a descriptive baseline.
    valid_dates = monthly.dropna(subset=["pe_ttm", "yield_10y_pct"]).index
    for date in valid_dates:
        for horizon in (12, 36, 60):
            result = one_event("UNCONDITIONAL_MONTHLY", date, daily, horizon)
            if result:
                rows.append(result)
    events = pd.DataFrame(rows)
    events.to_csv(OUTPUT / "event_study.csv", index=False, encoding="utf-8-sig")

    summary_rows: list[dict[str, object]] = []
    for (signal, horizon), group in events.groupby(["signal", "horizon_months"]):
        low_ci, high_ci = bootstrap_ci(group["ann_excess_return"])
        summary_rows.append(
            {
                "signal": signal,
                "horizon_months": horizon,
                "n": len(group),
                "mean_stock_ann_return": group["stock_ann_return"].mean(),
                "median_stock_ann_return": group["stock_ann_return"].median(),
                "mean_bond_ann_return": group["bond_ann_return"].mean(),
                "mean_ann_excess_return": group["ann_excess_return"].mean(),
                "excess_bootstrap_ci_low": low_ci,
                "excess_bootstrap_ci_high": high_ci,
                "median_max_drawdown": group["max_drawdown_from_entry"].median(),
                "worst_max_drawdown": group["max_drawdown_from_entry"].min(),
                "prob_fell_10pct": group["fell_10pct"].mean(),
                "prob_fell_20pct": group["fell_20pct"].mean(),
                "median_recovery_days": group["recovery_days"].median(),
            }
        )
    summary = pd.DataFrame(summary_rows).sort_values(["horizon_months", "signal"])
    summary.to_csv(OUTPUT / "backtest_summary.csv", index=False, encoding="utf-8-sig")
    return events, summary


def pb_roe_sensitivity() -> pd.DataFrame:
    rows = []
    for roe in (0.08, 0.10, 0.12, 0.14):
        for growth in (0.00, 0.02, 0.04, 0.06):
            for cost in (0.07, 0.09, 0.11, 0.13):
                pb = (roe - growth) / (cost - growth) if cost > growth else np.nan
                rows.append({"roe": roe, "growth": growth, "cost_of_equity": cost, "theoretical_pb": pb})
    out = pd.DataFrame(rows)
    out.to_csv(OUTPUT / "pb_roe_sensitivity.csv", index=False, encoding="utf-8-sig")
    return out


def set_plot_style() -> None:
    plt.rcParams.update(
        {
            "font.sans-serif": ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"],
            "axes.unicode_minus": False,
            "figure.dpi": 140,
            "axes.grid": True,
            "grid.alpha": 0.20,
        }
    )


def make_figures(monthly: pd.DataFrame, summary: pd.DataFrame) -> None:
    set_plot_style()
    history = monthly.loc[pd.Timestamp("2011-01-31") :].dropna(subset=["price_close"])
    model = monthly.dropna(subset=["boundary_q10"])
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(history.index, history["price_close"], color="#172554", lw=1.8, label="沪深300价格指数")
    for q, color in ((5, "#7f1d1d"), (10, "#dc2626"), (15, "#fb7185")):
        ax.plot(
            history.index,
            history[f"history_boundary_q{q:02d}"],
            color=color,
            lw=1.0,
            label=f"历史PE {q}%边界",
        )
    ax.fill_between(
        history.index,
        history["history_boundary_q05"],
        history["history_boundary_q15"],
        color="#fecdd3",
        alpha=0.25,
    )
    ax.plot(model.index, model["boundary_q10"], color="#0f766e", lw=1.4, ls="--", label="条件回归10%边界")
    ax.set_title("沪深300近15年估值低分位边界（所有阈值仅使用当期以前数据）")
    ax.legend(ncol=3, fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGURES / "01_dynamic_boundaries.png")
    plt.close(fig)

    erp = monthly.dropna(subset=["erp"])
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
    axes[0].plot(erp.index, erp["erp"] * 100, color="#0f766e", label="ERP proxy")
    axes[0].axhline(0, color="black", lw=0.7)
    axes[0].set_ylabel("百分点")
    axes[0].legend()
    axes[1].plot(erp.index, erp["erp_pct_5y"] * 100, color="#7c3aed", label="5年滚动百分位")
    axes[1].axhline(90, color="#dc2626", ls="--", lw=1, label="90%阈值")
    axes[1].set_ylabel("百分位 %")
    axes[1].legend()
    fig.suptitle("盈利收益率减10年国债收益率：水平与实时历史百分位")
    fig.tight_layout()
    fig.savefig(FIGURES / "02_erp_percentile.png")
    plt.close(fig)

    scatter = monthly.dropna(subset=["pe_pct_5y", "stock_tr_close"]).copy()
    scatter["forward_36m_stock_ann"] = (scatter["stock_tr_close"].shift(-36) / scatter["stock_tr_close"]) ** (1 / 3) - 1
    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.scatter(scatter["pe_pct_5y"] * 100, scatter["forward_36m_stock_ann"] * 100, s=18, alpha=0.55, color="#2563eb")
    ax.axvline(10, color="#dc2626", ls="--", lw=1)
    ax.axhline(0, color="black", lw=0.7)
    ax.set_xlabel("PE在此前5年中的百分位（%）")
    ax.set_ylabel("未来3年股票年化总回报（%）")
    ax.set_title("估值位置与未来3年回报（重叠观察，仅作描述）")
    fig.tight_layout()
    fig.savefig(FIGURES / "03_valuation_forward_return.png")
    plt.close(fig)

    risk = summary[(summary["horizon_months"] == 36) & (summary["signal"] != "UNCONDITIONAL_MONTHLY")]
    if not risk.empty:
        fig, ax = plt.subplots(figsize=(10, 5.5))
        x = np.arange(len(risk))
        width = 0.36
        ax.bar(x - width / 2, risk["prob_fell_10pct"] * 100, width, label="继续下跌≥10%", color="#f59e0b")
        ax.bar(x + width / 2, risk["prob_fell_20pct"] * 100, width, label="继续下跌≥20%", color="#dc2626")
        ax.set_xticks(x, risk["signal"], rotation=25, ha="right")
        ax.set_ylabel("事件比例（%）")
        ax.set_title("信号触发后3年内的进一步下跌风险")
        ax.legend()
        fig.tight_layout()
        fig.savefig(FIGURES / "04_downside_risk.png")
        plt.close(fig)

    wealth = monthly.dropna(subset=["stock_tr_close", "bond_tr_close"])
    normalized = wealth[["stock_tr_close", "bond_tr_close"]] / wealth[["stock_tr_close", "bond_tr_close"]].iloc[0] * 100
    fig, ax = plt.subplots(figsize=(12, 5.5))
    ax.plot(normalized.index, normalized["stock_tr_close"], label="沪深300全收益", color="#1d4ed8")
    ax.plot(normalized.index, normalized["bond_tr_close"], label="中证全债", color="#15803d")
    ax.set_yscale("log")
    ax.set_ylabel("归一化财富（对数轴）")
    ax.set_title("股债总回报基准比较（不用于拟合估值底线）")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIGURES / "05_stock_bond_wealth.png")
    plt.close(fig)


def pct(value: float | int | None, digits: int = 1) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value) * 100:.{digits}f}%"


def num(value: float | int | None, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value):,.{digits}f}"


def latest_monitor(monthly: pd.DataFrame) -> pd.Series:
    usable = monthly.dropna(subset=["price_close", "pe_ttm", "yield_10y_pct", "erp"])
    return usable.iloc[-1]


def summary_row(summary: pd.DataFrame, signal: str, horizon: int) -> pd.Series | None:
    match = summary[(summary.signal == signal) & (summary.horizon_months == horizon)]
    return None if match.empty else match.iloc[0]


def make_report(monthly: pd.DataFrame, events: pd.DataFrame, summary: pd.DataFrame) -> None:
    latest = latest_monitor(monthly)
    analysis_date = pd.Timestamp(latest.name).date().isoformat()
    low_pe_12 = summary_row(summary, "S1_low_pe", 12)
    high_erp_12 = summary_row(summary, "S2_high_erp", 12)
    high_erp_60 = summary_row(summary, "S2_high_erp", 60)
    baseline_36 = summary_row(summary, "UNCONDITIONAL_MONTHLY", 36)
    signal_names = ["S1_low_pe", "S2_high_erp", "S3_below_dynamic_q10", "S4_quality_adjusted", "MVP_combo"]
    primary_36 = [summary_row(summary, name, 36) for name in signal_names]
    primary_36 = [row for row in primary_36 if row is not None]
    stock_36_low = min((row.mean_stock_ann_return for row in primary_36), default=np.nan)
    stock_36_high = max((row.mean_stock_ann_return for row in primary_36), default=np.nan)
    excess_36_low = min((row.mean_ann_excess_return for row in primary_36), default=np.nan)
    excess_36_high = max((row.mean_ann_excess_return for row in primary_36), default=np.nan)
    fall10_low = min((row.prob_fell_10pct for row in primary_36), default=np.nan)
    fall10_high = max((row.prob_fell_10pct for row in primary_36), default=np.nan)
    lines = []
    for signal in signal_names:
        row = summary_row(summary, signal, 36)
        if row is None:
            continue
        advantage = row.mean_ann_excess_return - (baseline_36.mean_ann_excess_return if baseline_36 is not None else np.nan)
        lines.append(
            f"| {signal} | {int(row.n)} | {pct(row.mean_stock_ann_return)} | {pct(row.mean_ann_excess_return)} | {pct(advantage)} | {pct(row.median_max_drawdown)} | {pct(row.prob_fell_10pct)} | {pct(row.prob_fell_20pct)} |"
        )
    signal_table = "\n".join(lines) if lines else "| 无可用已完成事件 | — | — | — | — | — | — | — |"
    active = [
        name
        for name in signal_names
        if bool(latest.get(name, False))
    ]
    report = f"""# 沪深300长期估值底部：模型与实证报告

> 联合模型数据截止：{analysis_date}（央行月度统计表最新可用月末）  
> 运行日期：{RUN_DATE}  
> 性质：研究模型，不构成投资建议。

## 一、结论先行

- 最新可评估月末的沪深300点位为 **{num(latest.price_close)}**，PE-TTM为 **{num(latest.pe_ttm)}**，10年期国债收益率为 **{num(latest.yield_10y_pct)}%**，简化ERP为 **{pct(latest.erp)}**。
- PE在此前5年/10年中的实时百分位分别为 **{pct(latest.pe_pct_5y)} / {pct(latest.pe_pct_10y)}**，ERP百分位分别为 **{pct(latest.erp_pct_5y)} / {pct(latest.erp_pct_10y)}**；当前触发信号：**{', '.join(active) if active else '无'}**。
- 动态10%低估值边界为 **{num(latest.boundary_q10)}**，实际点位相对该边界的Gap为 **{pct(latest.gap_q10)}**。Gap≤0只表示进入模型低估区，不代表价格底部或不会继续下跌。
- 结果呈现明显的期限差异：1年期低PE信号的股票年化回报为 **{pct(low_pe_12.mean_stock_ann_return if low_pe_12 is not None else np.nan)}**，高ERP信号为 **{pct(high_erp_12.mean_stock_ann_return if high_erp_12 is not None else np.nan)}**；3年期各主信号股票年化约 **{pct(stock_36_low)}—{pct(stock_36_high)}**、股债超额约 **{pct(excess_36_low)}—{pct(excess_36_high)}**；5年期共有 **{int(high_erp_60.n) if high_erp_60 is not None else 0}** 个成熟高ERP事件，股债年化超额为 **{pct(high_erp_60.mean_ann_excess_return if high_erp_60 is not None else np.nan)}**。
- 样本有效期受官方PE历史限制，PE和10年期国债收益率联合序列从2011年中开始并覆盖至{analysis_date}。主检验使用5年滚动窗，10年窗作为稳健性检查；完整近15年历史边界和需要训练期的条件回归边界分开展示。

## 二、模型判断

### A. PE历史分位

这是最透明、最稳健的基准。优点是几乎不依赖参数；缺点是忽略利率中枢、盈利质量和行业结构变化。本报告的分位数只使用当期以前数据，杜绝全样本分位造成的未来函数。

### B. 股债利差（ERP proxy）

定义为 `1/PE - 10年国债收益率`。它适合衡量相对估值，但不是严格前瞻ERP：盈利可能下修，PE口径会受亏损公司处理影响，利率与风险偏好也可能同步变化。因此它必须和未来总回报及回撤一起验证。

### C. PB—ROE模型

理论关系 `PB=(ROE-g)/(Ke-g)` 对参数极敏感，且 `Ke` 与长期增长率不可直接观察。免费官方历史数据没有可按公告日回放的指数PB和可持续ROE，本报告只交付理论敏感性表 `pb_roe_sensitivity.csv`，**不把 PB/PE 近似值冒充真实ROE，也不做伪精确回测**。这是下一阶段接入Wind/中证授权基本面数据后再完成的模块。

### D. 标准化盈利 + 条件分位数回归

先以 `P/PE` 得到指数等价盈利，再用36个月滚动中位数平滑；每月只用此前至少60个月样本，分别估计5%、10%、15%和50%条件分位的 `ln(PE)`，解释变量为当期10年国债收益率和标准化盈利同比增长。该模型形成动态边界，但存在两个重要限制：样本短、解释变量由指数口径盈利派生，不能替代公告日财务数据。

### E. 股息率—国债利差

中证免费历史接口未提供完整可回放的股息率序列，本次没有将其用于信号。后续如接入统一口径股息率，可作为现金分红交叉验证，不应直接替代盈利估值。

## 三、3年事件回测摘要

| 信号 | 独立事件数 | 股票年化 | 股债年化超额 | 相对无条件超额优势 | 中位最大回撤 | 继续跌10%概率 | 继续跌20%概率 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
{signal_table}

基准的“无条件月度”观察相互重叠，仅用于描述性比较；信号表使用连续触发区间的首次月份，减少同一轮熊市被重复计数。主要信号触发后继续下跌10%的比例为{pct(fall10_low)}—{pct(fall10_high)}，说明“便宜”不等于短期见底。事件数量依然有限，Bootstrap区间不能消除市场阶段少的根本问题。

## 四、实施口径与防偏差处理

1. 月末形成信号，下一可用交易日以沪深300全收益指数入场。
2. 股票持有收益使用沪深300全收益指数 H00300；债券对照使用中证全债利息再投资指数 N11001。两者均为中证官网历史序列。
3. 最大回撤使用日度全收益路径；未来1/3/5年收益按实际交易日对齐。
4. 滚动分位和分位数回归只看过去；条件分位模型逐月扩展窗口重新估计。
5. 连续信号合并为一个独立事件；同时保留全部月度无条件样本作描述性基准。
6. 10年窗信号单列，避免把5年窗结果误称为原方案的10年检验。

## 五、产出清单

- `data/processed/monthly_model_data.csv`：月度点位、PE、国债收益率、ERP、分位、盈利、动态边界和信号。
- `data/processed/daily_market_data.csv`：用于执行日和真实回撤测量的日度数据。
- `outputs/event_study.csv`：逐事件、逐期限的股票/债券收益和风险。
- `outputs/backtest_summary.csv`：汇总回测及Bootstrap区间。
- `outputs/quantile_coefficients.csv`：逐月、逐分位的样本外回归参数。
- `outputs/pb_roe_sensitivity.csv`：PB—ROE理论敏感性表。
- `dashboard.html`：月度监测面板；`outputs/figures/`：五张核心图。

## 六、不能据此断言的内容

- 不能把任何边界解释为永不跌破的点位底线。
- 不能把高ERP解释为确定性的未来高回报。
- 不能把样本内或短样本外优势解释为稳定可交易策略。
- 不能在缺少公告日ROE、历史PB与股息率统一口径时声称已完成盈利质量验证。

## 七、数据来源

- 中证指数有限公司官网历史行情接口：000300、H00300、N11001。
- 2011—2014年10年期国债收益率来自中债收益率曲线历史接口的月末最后观测；2015年以后来自中国人民银行“金融市场统计—中债国债收益率统计表”，源数据均由中央国债登记结算有限责任公司编制。
- 数据和模型字段定义见 `data_dictionary.md`；再现方式见 `README.md`。
"""
    (ROOT / "research_report.md").write_text(report, encoding="utf-8")

    cards = [
        ("沪深300", num(latest.price_close), "月末点位"),
        ("PE-TTM", num(latest.pe_ttm), f"5年分位 {pct(latest.pe_pct_5y)}"),
        ("10年国债", f"{num(latest.yield_10y_pct)}%", "月末收益率"),
        ("ERP proxy", pct(latest.erp), f"5年分位 {pct(latest.erp_pct_5y)}"),
        ("动态10%边界", num(latest.boundary_q10), f"Gap {pct(latest.gap_q10)}"),
    ]
    html_template = Template("""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>沪深300长期估值监测</title><style>
body{margin:0;background:#f8fafc;color:#0f172a;font-family:"Microsoft YaHei",sans-serif}.wrap{max-width:1180px;margin:auto;padding:28px}
h1{margin:0 0 6px}.sub{color:#64748b;margin-bottom:24px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px}.card{background:white;border:1px solid #e2e8f0;border-radius:12px;padding:18px;box-shadow:0 4px 14px #0f172a0b}.label{font-size:13px;color:#64748b}.value{font-size:27px;font-weight:700;margin:8px 0}.note{font-size:12px;color:#475569}.panel{background:white;border:1px solid #e2e8f0;border-radius:12px;padding:18px;margin-top:18px}img{width:100%;height:auto}.warn{border-left:4px solid #dc2626;background:#fff1f2;padding:12px 16px;margin:18px 0}.signals{font-weight:700;color:#9f1239}table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:8px;border-bottom:1px solid #e2e8f0;text-align:right}th:first-child,td:first-child{text-align:left}
</style></head><body><div class="wrap"><h1>沪深300长期估值监测</h1><div class="sub">数据截止 {{ date }}｜研究模型，不构成投资建议</div>
<div class="grid">{% for c in cards %}<div class="card"><div class="label">{{ c[0] }}</div><div class="value">{{ c[1] }}</div><div class="note">{{ c[2] }}</div></div>{% endfor %}</div>
<div class="warn">当前触发：<span class="signals">{{ active }}</span>。进入低估区仍可能继续下跌；边界是条件分位，不是价格支撑承诺。</div>
<div class="panel"><h2>动态估值边界</h2><img src="outputs/figures/01_dynamic_boundaries.png"></div>
<div class="panel"><h2>ERP与实时百分位</h2><img src="outputs/figures/02_erp_percentile.png"></div>
<div class="panel"><h2>3年事件回测</h2>{{ table }}</div>
<div class="panel"><h2>下行风险</h2><img src="outputs/figures/04_downside_risk.png"></div>
<div class="panel"><h2>股债财富比较</h2><img src="outputs/figures/05_stock_bond_wealth.png"></div>
</div></body></html>""")
    table = summary[(summary.horizon_months == 36) & (summary.signal != "UNCONDITIONAL_MONTHLY")][
        ["signal", "n", "mean_stock_ann_return", "mean_ann_excess_return", "median_max_drawdown", "prob_fell_20pct"]
    ].copy()
    for col in ["mean_stock_ann_return", "mean_ann_excess_return", "median_max_drawdown", "prob_fell_20pct"]:
        table[col] = table[col].map(pct)
    html = html_template.render(
        date=analysis_date,
        cards=cards,
        active=", ".join(active) if active else "无",
        table=table.to_html(index=False, border=0),
    )
    (ROOT / "dashboard.html").write_text(html, encoding="utf-8")


def write_docs() -> None:
    dictionary = """# 数据字典

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
"""
    (ROOT / "data_dictionary.md").write_text(dictionary, encoding="utf-8")
    readme = """# 沪深300长期估值底部研究

本项目把研究方案第六节落地为可复现的数据、模型、回测、图表和月度面板。

## 运行

```powershell
.\\.venv\\Scripts\\python.exe src\\run_research.py
```

强制刷新官网数据：

```powershell
.\\.venv\\Scripts\\python.exe src\\run_research.py --refresh
```

## 主要文件

- `research_report.md`：结论、模型评价、回测摘要和局限。
- `dashboard.html`：月度监测面板。
- `data/processed/`：清洗后的日度和月度数据。
- `outputs/`：事件研究、汇总、参数、敏感性表和图。

## 复现说明

脚本从中证指数官网接口读取 000300、H00300、N11001；2011—2014年国债收益率读取中债历史曲线，2015年以后读取中国人民银行年度统计表。网络失败时保留已缓存原始文件。模型上限固定为2026-09-30，并以月度统计表最新已发布月末作为实际联合模型截止日。
"""
    (ROOT / "README.md").write_text(readme, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="Refresh all remote source data")
    args = parser.parse_args()
    ensure_dirs()
    price = fetch_csindex_series("000300", "csindex_000300.csv", args.refresh)
    tri = fetch_csindex_series("H00300", "csindex_H00300.csv", args.refresh)
    bond = fetch_csindex_series("N11001", "csindex_N11001.csv", args.refresh)
    yields = fetch_pbc_yields(args.refresh)
    daily = build_daily(price, tri, bond)
    monthly = build_monthly(price, tri, bond, yields)
    events, summary = run_backtest(monthly, daily)
    pb_roe_sensitivity()
    make_figures(monthly, summary)
    make_report(monthly, events, summary)
    write_docs()
    print(f"Completed. Monthly rows={len(monthly)}, events={len(events)}")


if __name__ == "__main__":
    main()
