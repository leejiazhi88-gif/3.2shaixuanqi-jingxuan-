import json, math, sys, concurrent.futures
from pathlib import Path
import pandas as pd
sys.path.insert(0,'/Users/fuguiplus/Documents/Codex/2026-09-14/new-chat/work')
import refresh_all_20260923 as x
import build_all as old
x.SHEET='kg45hf'
TARGET_SPREADSHEET='IEpIsPff6hkPsqt1jmtcPu61nef'
x.BASE=f'sheets/v2/spreadsheets/{TARGET_SPREADSHEET}'
BASE=x.BASE
OUT=Path('/Users/fuguiplus/Documents/Codex/2026-09-14/new-chat/work/refresh-selected-20260923')
OUT.mkdir(parents=True,exist_ok=True)

def pad(row,w=52): return list(row[:w])+['']*max(0,w-len(row))
def num(v):
    if v in ('',None) or isinstance(v,bool): return None
    try:
        z=float(v); return z if math.isfinite(z) else None
    except: return None

def prepare():
    token=old.b.get_feishu_token(old.b.DEFAULT_FEISHU_ENV)
    before=x.api(f'{BASE}/values/{x.SHEET}!A1:AZ500?valueRenderOption=UnformattedValue',token)['data']['valueRange']['values']
    headers=list(before[0]); idx={h:i for i,h in enumerate(headers) if h}
    rows=[pad(r) for r in before[1:] if r and r[0]]
    codes=[str(r[3]) for r in rows]
    assert len(codes)==len(set(codes)) and len(codes)>0
    width=len(headers)
    pro=old.b.ts.pro_api(); daily,stocks,companies=x.fetch_market(pro)
    market=daily.merge(stocks[['ts_code','name']],on='ts_code',how='left').merge(companies[['ts_code','main_business']],on='ts_code',how='left').set_index('ts_code')
    missing=[c for c in codes if c not in market.index]
    assert not missing, missing
    # Ensure price histories exist in shared 9/23 cache.
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        fs=[pool.submit(x.fetch_prices,c) for c in codes if not (x.RAW/'prices'/f'{c.replace(".","_")}.csv').exists()]
        for f in fs: f.result()
    out=[]; audit=[]
    for r,code in zip(rows,codes):
        item=market.loc[code]
        prices=x.history(code); latest=prices.iloc[-1]
        assert str(latest['trade_date'])==x.ASOF, (code,latest['trade_date'])
        cap=float(item['total_mv'])/10000.0
        old_cap=num(r[idx['市值(亿元)']]); old_y26=num(r[idx['本财年预估全年股息率（26年）']])
        r[idx['名称']]=str(item['name']); r[idx['市值(亿元)']]=round(cap,1)
        r[idx['PE(TTM)']]=old.b.fmt_num(item.get('pe_ttm'))
        for year in (2026,2027,2028):
            p=num(r[idx[f'{year}净利润(预测,亿元)']])
            r[idx[f'{year} PE(预测)']]=old.b.fmt_num(cap/p) if p and p>0 else ''
        r[idx['最新交易日']]=x.ASOF_DISPLAY
        r[idx['当日涨幅%']]=old.b.fmt_pct_value(float(latest['pct_chg']))
        for days in (10,30,60,90,250,360,720,1080):
            v=old.b.pct_return(prices,days); r[idx[f'{days}日涨幅%']]=old.b.fmt_pct_value(v) if v is not None else '历史不足'
        r[idx['股息率%']]=old.b.fmt_pct_fraction(item.get('dv_ttm'),digits=6)
        if old_y26 is not None and old_cap and cap>0: r[idx['本财年预估全年股息率（26年）']]=old_y26*old_cap/cap
        if code=='600795.SH':
            forecast=num(r[idx['2026净利润(预测,亿元)']])
            if forecast is not None: r[idx['本财年预估全年股息率（26年）']]=max(forecast*.60/cap,.22/float(latest['close']))
            r[idx['2026年股息率估算备注']]=x.update_guidance_note(r[idx['2026年股息率估算备注']],float(latest['close']))
        out.append(r); audit.append({'row':len(out)+1,'code':code,'name':r[0],'market_cap_yi':cap})
    clear_to=len(out)+1
    payload={'valueRange':{'range':f'{x.SHEET}!A1:AZ{clear_to}','values':[headers]+out+[['']*width for _ in range(clear_to-len(out)-1)]}}
    (OUT/'before.json').write_text(json.dumps(before,ensure_ascii=False))
    (OUT/'payload.json').write_text(json.dumps(payload,ensure_ascii=False))
    (OUT/'audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2))
    cf=x.api(f'{BASE}/condition_formats?sheet_ids={x.SHEET}',token); (OUT/'cf_before.json').write_text(json.dumps(cf,ensure_ascii=False))
    print(json.dumps({'rows':len(out),'asof':x.ASOF_DISPLAY,'codes':codes[:3]},ensure_ascii=False))

def apply():
    token=old.b.get_feishu_token(old.b.DEFAULT_FEISHU_ENV)
    before=json.loads((OUT/'before.json').read_text()); headers=list(before[0]); idx={h:i for i,h in enumerate(headers) if h}; current=x.api(f'{BASE}/values/{x.SHEET}!A1:AZ500?valueRenderOption=UnformattedValue',token)['data']['valueRange']['values']; assert current==before
    payload=json.loads((OUT/'payload.json').read_text()); x.api(f'{BASE}/values',token,method='PUT',body=payload)
    n=len(json.loads((OUT/'audit.json').read_text()))
    after=x.api(f'{BASE}/values/{x.SHEET}!A1:AZ{n+1}?valueRenderOption=UnformattedValue',token)['data']['valueRange']['values']
    assert len(after)==n+1 and all(str(r[idx['最新交易日']])==x.ASOF_DISPLAY for r in after[1:])
    assert len({str(r[3]) for r in after[1:]})==n
    result={'sheet':'2026-09-23（精选）','sheet_id':x.SHEET,'asof':x.ASOF_DISPLAY,'rows':n,'values_verified':True,'conditional_format_rules_preserved':len(json.loads((OUT/'cf_before.json').read_text())['data']['sheet_condition_formats'])}
    (OUT/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)); print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':
    (prepare if sys.argv[1]=='prepare' else apply)()
