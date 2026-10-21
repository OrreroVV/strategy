"""Static scientific figures with exported source tables and explicit synthetic labels."""
import os
from pathlib import Path
import numpy as np
import pandas as pd
from .data import sha256


def render_research_figures(out,panel,ds,forecasts,relative,interval_stats,ledger,settings,manifest,run_id,write_json):
    folder=Path(out)/'figures';folder.mkdir(exist_ok=True)
    os.environ.setdefault('MPLCONFIGDIR',str(folder/'.mplconfig'))
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    kind=manifest['data_kind'];prefix='SYNTHETIC TEST ONLY' if kind=='synthetic' else 'HISTORICAL RESEARCH'
    footer=f"Source: {manifest['provider']} | Input: USD gross TR | run {run_id}"
    entries=[]
    def figure(size=(11,5)):
        f=Figure(figsize=size);FigureCanvasAgg(f);return f
    def save(name,fig,source,description):
        source=source.copy();source['data_kind']=kind;source['run_id']=run_id;source['input_sha256']=manifest['sha256']
        csv=folder/(name+'_source.csv');source.to_csv(csv,index=False)
        time_col='date' if 'date' in source else 'forecast_date' if 'forecast_date' in source else None
        span=source[time_col] if time_col else forecasts.forecast_date
        period=(str(pd.Timestamp(span.min()).date())+' to '+str(pd.Timestamp(span.max()).date())) if len(span) else 'no available dates'
        fig.text(.03,.015,footer+'\nPeriod: '+period,fontsize=8,color='#555555')
        fig.subplots_adjust(bottom=.15,top=.88,left=.09,right=.97)
        path=folder/(name+'.png');fig.savefig(path,dpi=160,facecolor='white')
        entries.append(dict(name=name,status='rendered',path='figures/'+path.name,source_csv='figures/'+csv.name,
            description=description,rows=len(source),png_sha256=sha256(path),source_sha256=sha256(csv),data_kind=kind,run_id=run_id))
    def skipped(name,reason):entries.append(dict(name=name,status='skipped',reason=reason,data_kind=kind,run_id=run_id))
    f=figure();ax=f.subplots()
    source=[]
    for j,g in panel.groupby('index_id'):
        g=g.sort_values('date');values=g.total_return_index/g.total_return_index.iloc[0]*100
        ax.plot(g.date,values,label=j,linewidth=1.7)
        source.append(pd.DataFrame(dict(date=g.date,index_id=j,rebased_total_return=values)))
    ax.set_yscale('log');ax.set_ylabel('Total return index (start=100, log scale)');ax.legend();ax.grid(alpha=.2)
    ax.set_title(prefix+' | Monthly USD total return\n'+str(panel.date.min().date())+' to '+str(panel.date.max().date()))
    save('market_total_return',f,pd.concat(source,ignore_index=True),'Descriptive total return history; no price-index substitution')
    if 'price_index' not in panel:skipped('price_vs_total_return','price_index absent; total-return-only figure supplied')
    else:skipped('price_vs_total_return','Separate price/TR comparison not implemented; no implicit series substitution')
    for column,name,title in [('y','nominal_return_distributions','Nominal annualized log return'),
                               ('y_real','real_return_distributions','Ex-post real annualized log return')]:
        valid=ds[ds[column].notna()] if column in ds else ds.iloc[:0]
        if valid.empty:skipped(name,'No available historical target values');continue
        horizons=sorted(valid.horizon_months.unique());rows=(len(horizons)+1)//2
        f=figure((11,3.4*rows+1));axes=f.subplots(rows,2,squeeze=False)
        for ax,h in zip(axes.flat,horizons):
            g=valid[valid.horizon_months==h];bounds=np.histogram_bin_edges(g[column]*100,bins=18)
            for j,v in g.groupby('index_id'):ax.hist(v[column]*100,bins=bounds,alpha=.45,label=j)
            ax.set_title(f'{h} months');ax.set_xlabel('Annualized log return (%)');ax.set_ylabel('Overlapping labels');ax.legend(fontsize=8)
        for ax in list(axes.flat)[len(horizons):]:ax.set_visible(False)
        f.suptitle(prefix+' | '+title+'\nMonthly labels overlap; counts are not independent cycles',fontsize=12)
        f.subplots_adjust(hspace=.48)
        save(name,f,valid[['date','index_id','horizon_months',column]],'Historical target distribution; not forecast evidence')
    h=settings['horizon_months'];model=settings['model_name']
    selected=forecasts[(forecasts.horizon_months==h)&(forecasts.model_name==model)]
    if selected.empty:skipped('oos_absolute','No selected horizon/model predictions')
    else:
        f=figure((11,7));axes=f.subplots(2,1)
        for ax,j in zip(axes,['SPX','NDX']):
            g=selected[selected.index_id==j].sort_values('forecast_date')
            ax.plot(g.forecast_date,g.actual_log_annual_return*100,label='Realized outcome',color='#222222',marker='o',markersize=3)
            ax.plot(g.forecast_date,g.predicted_log_annual_return*100,label='OOS prediction',color='#2878b5',linestyle='--')
            ax.set_title(j);ax.set_ylabel('Annualized log return (%)');ax.grid(alpha=.2);ax.legend(fontsize=8)
        f.suptitle(f'{prefix} | Historical OOS, {model}, {h} months',fontsize=12);f.subplots_adjust(hspace=.4)
        save('oos_absolute',f,selected,'Only matured historical OOS predictions, never in-sample fits')
        f=figure();ax=f.subplots();parts=[]
        for j,g in selected.groupby('index_id'):
            g=g.sort_values('forecast_date').copy()
            g['rolling_rmse_3_origins']=np.sqrt((g.predicted_log_annual_return-g.actual_log_annual_return).pow(2).rolling(3,min_periods=3).mean())
            ax.plot(g.forecast_date,g.rolling_rmse_3_origins*100,label=j);parts.append(g)
        ax.set_title(f'{prefix} | OOS RMSE over 3 forecast origins, {h} months');ax.set_ylabel('Annualized log-return error (percentage points)')
        ax.legend();ax.grid(alpha=.2)
        save('rolling_oos_errors',f,pd.concat(parts),'Window is three prediction origins, not three calendar months')
    if relative is None or relative.empty:skipped('relative_paths','Relative predictions unavailable')
    else:
        g=relative[(relative.horizon_months==h)&(relative.model_name==model)]
        if g.empty:skipped('relative_paths','Selected relative horizon/model unavailable')
        else:
            f=figure();ax=f.subplots()
            actual=g[g.prediction_path=='direct'].sort_values('forecast_date')
            ax.plot(actual.forecast_date,actual.actual_log_annual_return*100,color='#222222',label='Realized relative outcome')
            for path,v in g.groupby('prediction_path'):
                v=v.sort_values('forecast_date');ax.plot(v.forecast_date,v.predicted_log_annual_return*100,linestyle='--',label=path+' OOS')
            ax.axhline(0,color='#999999',linewidth=.7);ax.set_ylabel('NDX - SPX annualized log return (pp)')
            ax.set_title(f'{prefix} | Relative paths, {model}, {h} months');ax.legend();ax.grid(alpha=.2)
            save('relative_paths',f,g,'Point paths shown; missing intervals are not invented')
    if interval_stats is None or interval_stats.empty:skipped('interval_availability','Interval diagnostics unavailable')
    else:
        data=interval_stats.groupby('model_name')[['n_forecasts','n_intervals_80','n_intervals_95']].sum().reset_index()
        f=figure();ax=f.subplots();x=np.arange(len(data));width=.35
        ax.bar(x-width/2,data.n_intervals_80/data.n_forecasts,width,label='80% interval availability')
        ax.bar(x+width/2,data.n_intervals_95/data.n_forecasts,width,label='95% interval availability')
        ax.set_xticks(x,data.model_name,rotation=25,ha='right');ax.set_ylim(0,1.05);ax.set_ylabel('Available intervals / all forecasts')
        ax.set_title(prefix+' | Interval availability (not coverage)');ax.legend(fontsize=8)
        if data[['n_intervals_80','n_intervals_95']].to_numpy().sum()==0:
            ax.text(.5,.5,'No eligible intervals; coverage is NA',transform=ax.transAxes,ha='center',color='#555555')
        save('interval_availability',f,data,'Availability denominator includes all forecasts; zero availability is not zero coverage')
    if ledger is None or ledger.empty:skipped('strategy_book','Portfolio module not executed')
    else:
        data=ledger[(ledger.funding_kind=='dca')&np.isclose(ledger.cost_bps,settings['cost_bps']) &
            ((ledger.strategy!='limited_tilt_new_money')|np.isclose(ledger.max_tilt,settings['tilt_limit']))]
        f=figure((11,10));axes=f.subplots(3,1)
        labels=dict(fixed_50_50_annual='50/50 annual rebalance',limited_tilt_new_money='Limited tilt (new money)',
                    ndx_hold='NDX hold',spx_hold='SPX hold',strategic_new_money='Strategic (new money)')
        for strategy,g in data.groupby('strategy'):
            g=g.sort_values('date');axes[0].plot(g.date,g.unit_nav,label=labels[strategy])
            axes[1].plot(g.date,g.drawdown*100,label=labels[strategy])
        tilt=data[data.strategy=='limited_tilt_new_money'].sort_values('date')
        axes[2].bar(tilt.date,tilt.turnover*100,width=20,color='#527c9b')
        axes[0].set_ylabel('Flow-adjusted unit NAV');axes[0].legend(fontsize=8,ncol=2)
        axes[1].set_ylabel('Unit-NAV drawdown (%)');axes[2].set_ylabel('Two-sided turnover (%)')
        for ax in axes:ax.grid(alpha=.2)
        if not data.signal_active.any():f.text(.09,.915,'No eligible tilt: tilt and strategic rules coincide',fontsize=10,color='#444444')
        f.suptitle(f"{prefix} | DCA index-proxy simulation, {settings['cost_bps']}bp one-way cost\nUnit NAV excludes deposits; monthly marks are not executable product quotes",fontsize=12)
        f.subplots_adjust(hspace=.3)
        save('strategy_book',f,data,'Net TWR unit NAV, drawdown and turnover; not raw account-value growth')
    skipped('point_in_time_valuation_percentiles','Historical PE availability/percentile feature not implemented')
    skipped('return_decomposition','No verified complete main-sample EPS/dividend decomposition series')
    write_json(Path(out)/'chart_manifest.json',dict(run_id=run_id,data_kind=kind,input_sha256=manifest['sha256'],figures=entries))
    links=['# 研究图表\n',f'**{prefix}**；所有图均来自本次实际输入和运行，源表及校验值见chart_manifest.json。\n']
    for entry in entries:
        if entry['status']=='rendered':links.append(f"## {entry['name']}\n\n![{entry['description']}]({entry['path']})\n")
        else:links.append(f"- {entry['name']}：未生成，{entry['reason']}。\n")
    (Path(out)/'figures_report.md').write_text('\n'.join(links),encoding='utf-8')
    return entries
