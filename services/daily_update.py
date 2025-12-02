#!/usr/bin/env python3
import os
import sys
import time
import argparse
import requests
import json
from typing import List

# 复用本项目的SQLite存储
from data_store import StockDatabase

ALPHA_API_KEY_ENV = "ALPHAVANTAGE_API_KEY"
ALPHA_BASE = "https://www.alphavantage.co/query"

# 统一配置文件路径
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
CONFIG_DIR = os.path.join(BASE_DIR, 'config')
CONFIG_PATH = os.path.join(CONFIG_DIR, 'app.json')

def load_app_config():
    try:
        if not os.path.exists(CONFIG_PATH):
            return {}
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f) or {}
    except Exception:
        return {}


def fetch_alpha_daily(symbol: str, api_key: str):
    try:
        resp = requests.get(ALPHA_BASE, params={
            'function': 'TIME_SERIES_DAILY_ADJUSTED', 'symbol': symbol, 'apikey': api_key
        }, timeout=30)
        resp.raise_for_status()
        j = resp.json()
        # 配额/次数用尽检测
        note = j.get('Note') or j.get('Information')
        if note:
            return {"error": "alpha vantage quota exceeded", "reason": "quota", "note": note}
        series = j.get('Time Series (Daily)') or {}
        rows = []
        for date, d in sorted(series.items()):
            rows.append({
                'date': date,
                'open': float(d.get('1. open') or 0),
                'high': float(d.get('2. high') or 0),
                'low': float(d.get('3. low') or 0),
                'close': float(d.get('5. adjusted close') or d.get('4. close') or 0),
                'volume': int(d.get('6. volume') or 0)
            })
        return {'symbol': symbol, 'rows': rows, 'count': len(rows)}
    except requests.exceptions.HTTPError as e:
        return {"error": f"HTTPError {getattr(e.response, 'status_code', '')}", "raw": getattr(e.response, 'text', '')}
    except requests.exceptions.Timeout as e:
        return {"error": f"Timeout {e}", "reason": "network"}
    except requests.exceptions.ConnectionError as e:
        return {"error": f"ConnectionError {e}", "reason": "network"}
    except Exception as e:
        return {"error": str(e)}


def load_symbols(file_path: str | None, symbols_arg: List[str] | None) -> List[str]:
    syms = []
    if file_path and os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                s = (line.strip() or '').split('#')[0].strip()
                if s:
                    syms.append(s)
    if symbols_arg:
        for s in symbols_arg:
            for t in (s or '').split(','):
                t2 = t.strip()
                if t2:
                    syms.append(t2)
    # 去重并保持顺序
    seen = set()
    uniq = []
    for s in syms:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


def main():
    parser = argparse.ArgumentParser(description='AlphaCouncil 每日增量更新：从 Alpha Vantage 拉取日线并写入本地SQLite')
    parser.add_argument('-f', '--file', default=os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'symbols.txt'), help='股票清单文件路径')
    parser.add_argument('-s', '--symbols', nargs='*', help='以逗号分隔的股票代码列表，如 AAPL,IBM')
    parser.add_argument('--sleep', type=int, default=15, help='每次外部请求之间的休眠秒数（免费额度建议>=12）')
    parser.add_argument('--summary', default=None, help='执行摘要JSON输出路径')
    parser.add_argument('--log', default=None, help='日志文件路径（由外部进程管理）')
    args = parser.parse_args()

    cfg = load_app_config()
    api_key = cfg.get('alphaKey') or os.environ.get(ALPHA_API_KEY_ENV)
    if not api_key:
        print(f"[ERROR] 缺少环境变量 {ALPHA_API_KEY_ENV}，或配置文件未设置 alphaKey")
        sys.exit(1)

    symbols = load_symbols(args.file, args.symbols)
    if not symbols:
        print("[WARN] 未提供股票代码；请在 data/symbols.txt 写入或通过 --symbols 指定")
        sys.exit(0)

    start_ts = int(time.time())
    print(f"[INFO] 本次增量更新股票数：{len(symbols)}；源：Alpha Vantage；写入：SQLite")
    db = StockDatabase()
    ok, fail = 0, 0
    for i, code in enumerate(symbols, start=1):
        print(f"[INFO] ({i}/{len(symbols)}) 拉取 {code} …")
        data = fetch_alpha_daily(code, api_key)
        if 'rows' in data:
            try:
                db.upsert_daily_prices(code, data['rows'])
                ok += 1
                print(f"[OK] {code} 写入 {len(data['rows'])} 条记录")
            except Exception as e:
                fail += 1
                print(f"[FAIL] {code} 写入失败：{e}")
        else:
            fail += 1
            reason = data.get('reason')
            if reason == 'quota':
                print(f"[FAIL] {code} 拉取失败：API 次数用完或配额受限｜{data.get('note') or data.get('error')}")
            elif (data.get('error') or '').startswith('Timeout') or (data.get('error') or '').startswith('ConnectionError'):
                print(f"[FAIL] {code} 拉取失败：网络问题或上游不可达｜{data.get('error')}")
            else:
                print(f"[FAIL] {code} 拉取失败：{data.get('error')}")
        if i < len(symbols):
            time.sleep(args.sleep)
    db.close()
    end_ts = int(time.time())
    print(f"[DONE] 成功：{ok}，失败：{fail}，数据库：ABC/data/stocks.db")

    # 写入执行摘要，便于前端查询最近一次状态
    try:
        base_dir = os.path.dirname(os.path.dirname(__file__))
        logs_dir = os.path.join(base_dir, 'data', 'logs')
        os.makedirs(logs_dir, exist_ok=True)
        summary_path = args.summary or os.path.join(logs_dir, 'daily_update-last.json')
        summary = {
            'start_ts': start_ts,
            'end_ts': end_ts,
            'ok': ok,
            'fail': fail,
            'sleep': args.sleep,
            'symbols': symbols,
            'log_path': args.log,
            'db_path': os.path.join(base_dir, 'data', 'stocks.db')
        }
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARN] 摘要写入失败：{e}")


if __name__ == '__main__':
    main()