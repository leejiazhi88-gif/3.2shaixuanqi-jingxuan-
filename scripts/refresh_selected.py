#!/usr/bin/env python3
"""Refresh a copied Feishu selected-stock sheet with a specified closing date.

Annual/quarterly earnings assumptions and manual dividend guidance stay in the
sheet. Only market-dependent columns are written. Prepare is read-only; apply
checks snapshots and verifies every written cell, other cells, and data bars.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
import tushare as ts

ROOT = Path(__file__).resolve().parents[1]
SPREADSHEET = 'IEpIsPff6hkPsqt1jmtcPu61nef'
WIKI = 'https://my.feishu.cn/wiki/UI5Tw4yxSiFsEXk5mkmcgqPWnPc'
FEISHU_ENV = Path(os.environ.get('FEISHU_ENV', '/Users/fuguiplus/Documents/Codex/2026-04-30/new-chat/xiaoniuma-feishu/.env'))
HISTORY_CACHE = Path(os.environ.get('SELECTED_HISTORY_CACHE', '/Users/fuguiplus/Documents/Codex/2026-09-14/new-chat/work/refresh-all-20260923/raw/prices'))
BASE = f'sheets/v2/spreadsheets/{SPREADSHEET}'
PERIODS = (10, 30, 60, 90, 250, 360, 720, 1080)
PRICE_FIELDS = 'ts_code,trade_date,close,pct_chg'


def api(path, token=None, method='GET', body=None):
    headers = {'Authorization': f'Bearer {token}'} if token else {}
    response = requests.request(method, 'https://open.feishu.cn/open-apis/' + path,
                                headers=headers, json=body, timeout=45)
    response.raise_for_status()
    result = response.json()
    if result.get('code', 0) != 0:
        raise RuntimeError(f"Feishu error {result.get('code')}: {result.get('msg')}")
    return result.get('data', result)


def token():
    env = {}
    if FEISHU_ENV.exists():
        for line in FEISHU_ENV.read_text().splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                env[key.strip()] = value.strip().strip('\"').strip("'")
    app_id = os.environ.get('FEISHU_APP_ID', env.get('FEISHU_APP_ID'))
    secret = os.environ.get('FEISHU_APP_SECRET', env.get('FEISHU_APP_SECRET'))
    if not app_id or not secret:
        raise RuntimeError('Missing FEISHU_APP_ID / FEISHU_APP_SECRET')
    return api('auth/v3/tenant_access_token/internal', method='POST',
               body={'app_id': app_id, 'app_secret': secret})['tenant_access_token']


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def col(index):
    result = ''
    while index:
        index, rest = divmod(index - 1, 26)
        result = chr(65 + rest) + result
    return result


def values(auth, sheet):
    sheets = api(f'sheets/v3/spreadsheets/{SPREADSHEET}/sheets/query', auth)['sheets']
    meta = next(s for s in sheets if s['sheet_id'] == sheet)
    grid = meta['grid_properties']
    address = f"{sheet}!A1:{col(grid['column_count'])}{grid['row_count']}"
    data = api(f'{BASE}/values/{address}?valueRenderOption=UnformattedValue', auth)['valueRange']['values']
    return meta, data


def number(value):
    if value in ('', None) or isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def rounded(value, digits=1):
    result = number(value)
    return round(result, digits) if result is not None else ''


def equivalent(a, b):
    if a in ('', None) and b in ('', None):
        return True
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-10)
    return a == b


def query(pro, endpoint, **params):
    # Keep calls below the existing project's rate; retry transient transport errors.
    for attempt in range(3):
        time.sleep(.25)
        try:
            return getattr(pro, endpoint)(**params)
        except (requests.Timeout, requests.ConnectionError):
            if attempt == 2:
                raise
            time.sleep(1 + attempt)


def guidance(note, date, close, profit, cap):
    result = copy.deepcopy(note)
    floor_profit = profit * .60 / cap
    floor_share = .22 / close
    basis = (f'每股0.22元÷{date.month}月{date.day}日股价{close:.2f}元得到{floor_share:.2%}'
             if floor_share >= floor_profit else
             f'2026年归母净利润预测{profit:g}亿元×60%÷{date.month}月{date.day}日市值{cap:.1f}亿元得到{floor_profit:.2%}')
    def replace(text):
        # Keep the policy wording and source link; change only the dated calculation.
        return re.sub(r'本行由.*?得到[\d.]+%', '本行由' + basis, text)
    if isinstance(result, list):
        for item in result:
            if 'text' in item and item.get('type') != 'url':
                item['text'] = replace(item['text'])
    else:
        result = replace(str(result or ''))
    return max(floor_profit, floor_share), result


def prepare(args, out):
    auth = token()
    source_meta, source = values(auth, args.source)
    target_meta, before = values(auth, args.target)
    assert args.source != args.target, 'Use a copied sheet to preserve history'
    # User-created copies may omit the leading zero in the month or day.
    target_date = datetime.strptime(target_meta['title'], '%Y-%m-%d（精选）')
    assert target_date.date() == args.date.date(), 'Target sheet date differs from requested date'
    assert source == before, 'Target must be an unchanged copy of the source'
    headers = before[0]
    idx = {h: i for i, h in enumerate(headers) if h}
    entries = [(i, copy.deepcopy(row)) for i, row in enumerate(before[1:], 2) if row and row[0]]
    codes = [r[idx['代码']] for _, r in entries]
    assert len(codes) == len(set(codes)) and codes
    asof = args.date.strftime('%Y%m%d')
    pro = ts.pro_api(os.environ['TUSHARE_TOKEN']) if os.environ.get('TUSHARE_TOKEN') else ts.pro_api()
    market = query(pro, 'daily_basic', trade_date=asof,
                   fields='ts_code,trade_date,close,pe_ttm,dv_ttm,total_mv')
    assert not market.empty and market.trade_date.astype(str).eq(asof).all(), 'Closing valuations unavailable'
    assert len(market) < 6000, 'Market response may be truncated'
    market = market.set_index('ts_code')
    missing = sorted(set(codes) - set(market.index))
    assert not missing, f'Missing current valuations: {missing}'
    market.to_csv(out / 'daily_basic.csv')

    histories = {}
    for code in codes:
        path = HISTORY_CACHE / f'{code.replace(".", "_")}.csv'
        if path.exists():
            history = pd.read_csv(path, dtype={'trade_date': str})
            history = history[history.trade_date <= asof]
        else:
            history = query(pro, 'daily', ts_code=code, start_date='20220101', end_date=asof, fields=PRICE_FIELDS)
        assert not history.empty, f'No price history: {code}'
        histories[code] = history[['ts_code', 'trade_date', 'close', 'pct_chg']].copy()
    start = min(datetime.strptime(h.trade_date.max(), '%Y%m%d') for h in histories.values()) + timedelta(days=1)
    increments = []
    while start <= args.date:
        daily = query(pro, 'daily', trade_date=start.strftime('%Y%m%d'), fields=PRICE_FIELDS)
        if not daily.empty:
            assert len(daily) < 6000, 'Daily response may be truncated'
            assert daily.trade_date.astype(str).eq(start.strftime('%Y%m%d')).all()
            increments.append(daily[daily.ts_code.isin(codes)])
        start += timedelta(days=1)
    recent = pd.concat(increments, ignore_index=True) if increments else pd.DataFrame(columns=PRICE_FIELDS.split(','))
    patches, audit = [], []
    for row_num, row in entries:
        code = row[idx['代码']]
        history = pd.concat([histories[code], recent[recent.ts_code == code]], ignore_index=True)
        history = history.sort_values('trade_date').drop_duplicates('trade_date', keep='last')
        latest = history.iloc[-1]
        assert str(latest.trade_date) == asof, f'Stale close: {code}'
        item = market.loc[code]
        cap, close = float(item.total_mv) / 10000, float(latest.close)
        assert cap > 0 and math.isclose(close, float(item.close), abs_tol=.001)
        old_cap = number(row[idx['市值(亿元)']])
        old_yield = number(row[idx['本财年预估全年股息率（26年）']])
        changes = {'市值(亿元)': round(cap, 1), 'PE(TTM)': rounded(item.pe_ttm),
                   '最新交易日': args.date.strftime('%Y-%m-%d'),
                   '当日涨幅%': round(float(latest.pct_chg) / 100, 3),
                   '股息率%': round(float(item.dv_ttm) / 100, 6) if number(item.dv_ttm) is not None else ''}
        for year in (2026, 2027, 2028):
            profit = number(row[idx[f'{year}净利润(预测,亿元)']])
            changes[f'{year} PE(预测)'] = round(cap / profit, 1) if profit and profit > 0 else ''
        for days in PERIODS:
            changes[f'{days}日涨幅%'] = (round(close / float(history.iloc[-days - 1].close) - 1, 3)
                                        if len(history) > days else '历史不足')
        if old_yield is not None:
            assert old_cap and old_cap > 0
            changes['本财年预估全年股息率（26年）'] = old_yield * old_cap / cap
        if code == '600795.SH':
            profit = number(row[idx['2026净利润(预测,亿元)']])
            assert profit is not None
            y, note = guidance(row[idx['2026年股息率估算备注']], args.date, close, profit, cap)
            changes['本财年预估全年股息率（26年）'] = y
            changes['2026年股息率估算备注'] = note
        for header, value in changes.items():
            patches.append({'row': row_num, 'column': idx[header], 'value': value})
        audit.append({'row': row_num, 'code': code, 'close': close, 'market_cap_yi': cap,
                      'history_rows': len(history), 'trade_date': asof})
        history_path = out / 'prices' / f'{code.replace(".", "_")}.csv'
        history_path.parent.mkdir(exist_ok=True)
        history.to_csv(history_path, index=False)
    plan = {'asof': asof, 'source': args.source, 'target': args.target, 'rows': len(entries),
            'source_meta': source_meta, 'target_meta': target_meta, 'patches': patches, 'audit': audit}
    save(out / 'source.json', source)
    save(out / 'before.json', before)
    save(out / 'plan.json', plan)
    save(out / 'cf_before.json', api(f'{BASE}/condition_formats?sheet_ids={args.target}', auth))
    print(json.dumps({'prepared_rows': len(entries), 'asof': asof, 'cells': len(patches)}, ensure_ascii=False), flush=True)


def apply(args, out):
    plan = json.loads((out / 'plan.json').read_text())
    assert plan['asof'] == args.date.strftime('%Y%m%d') and plan['target'] == args.target and plan['source'] == args.source
    before = json.loads((out / 'before.json').read_text())
    source = json.loads((out / 'source.json').read_text())
    auth = token()
    assert values(auth, args.source)[1] == source, 'Source changed after preparation'
    assert values(auth, args.target)[1] == before, 'Target changed after preparation'
    expected = copy.deepcopy(before)
    by_column = {}
    for p in plan['patches']:
        expected[p['row'] - 1][p['column']] = p['value']
        by_column.setdefault(p['column'], []).append(p)
    # Write only refreshed columns, preserving formulas and rich text elsewhere.
    for column, patches in sorted(by_column.items()):
        patches.sort(key=lambda p: p['row'])
        groups = []
        for p in patches:
            if not groups or p['row'] != groups[-1][-1]['row'] + 1:
                groups.append([])
            groups[-1].append(p)
        for group in groups:
            letter = col(column + 1)
            address = f"{args.target}!{letter}{group[0]['row']}:{letter}{group[-1]['row']}"
            api(BASE + '/values', auth, 'PUT', {'valueRange': {'range': address, 'values': [[p['value']] for p in group]}})
    # PE fonts in the prior project use <30 green, >50 red; refresh only these
    # fonts, leaving manual name colors, quarterly backgrounds and data bars.
    pe_columns = {i for i, h in enumerate(before[0]) if h in
                  ('PE(TTM)', '2026 PE(预测)', '2027 PE(预测)', '2028 PE(预测)')}
    font_groups = {}
    for p in plan['patches']:
        if p['column'] in pe_columns:
            value = number(p['value'])
            color = '#00B050' if value is not None and value < 30 else '#C00000' if value is not None and value > 50 else '#000000'
            cell = f"{col(p['column'] + 1)}{p['row']}"
            font_groups.setdefault(color, []).append(f'{args.target}!{cell}:{cell}')
    styles = [{'ranges': cells[i:i + 100], 'style': {'foreColor': color}}
              for color, cells in font_groups.items() for i in range(0, len(cells), 100)]
    api(BASE + '/styles_batch_update', auth, 'PUT', {'data': styles})
    after = values(auth, args.target)[1]
    assert len(after) == len(expected)
    for row_num, (want, got) in enumerate(zip(expected, after), 1):
        for column in range(max(len(want), len(got))):
            a = want[column] if column < len(want) else None
            b = got[column] if column < len(got) else None
            assert equivalent(a, b), f'Value mismatch {col(column + 1)}{row_num}'
    cf = api(f'{BASE}/condition_formats?sheet_ids={args.target}', auth)
    assert cf == json.loads((out / 'cf_before.json').read_text()), 'Conditional formats changed'
    assert values(auth, args.source)[1] == source, 'Source changed during refresh'
    result = {'date': args.date.strftime('%Y-%m-%d'), 'rows': plan['rows'], 'sheet_id': args.target,
              'url': WIKI + '?sheet=' + args.target, 'cells_verified': len(plan['patches']),
              'condition_format_rules': len(cf['sheet_condition_formats']),
              'source_preserved': True, 'other_cells_preserved': True,
              'earnings_assumptions': 'carried forward from source',
              'history_shortfalls': {str(d): sum(a['history_rows'] <= d for a in plan['audit']) for d in PERIODS}}
    save(out / 'verification.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['prepare', 'apply'])
    parser.add_argument('--date', required=True, type=lambda d: datetime.strptime(d, '%Y-%m-%d'))
    parser.add_argument('--source', required=True)
    parser.add_argument('--target', required=True)
    args = parser.parse_args()
    out = ROOT / 'work' / ('refresh-' + args.date.strftime('%Y%m%d'))
    out.mkdir(parents=True, exist_ok=True)
    (prepare if args.mode == 'prepare' else apply)(args, out)


if __name__ == '__main__':
    main()
