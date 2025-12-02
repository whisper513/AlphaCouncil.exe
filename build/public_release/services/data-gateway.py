#!/usr/bin/env python3
import json
import sys
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
import time
import requests
import csv
import subprocess
import threading
import asyncio

try:
    import websockets
except Exception:
    websockets = None

# 简易内存缓存，降低免费API速率压力
CACHE = {}
CACHE_TTL = 60  # 秒

ALLOW_ORIGIN = "*"

# 统一配置文件路径
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
CONFIG_DIR = os.path.join(BASE_DIR, 'config')
CONFIG_PATH = os.path.join(CONFIG_DIR, 'app.json')
AUDIT_DIR = os.path.join(BASE_DIR, 'data', 'logs')
AUDIT_LOG = os.path.join(AUDIT_DIR, 'config_audit.log')
_RL_BUCKETS = {}

def _load_config():
    try:
        if not os.path.exists(CONFIG_PATH):
            return {}
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f) or {}
    except Exception:
        return {}

def _save_config(patch: dict):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    current = _load_config()
    current.update({k:v for k,v in patch.items() if v is not None})
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(current, f, ensure_ascii=False, indent=2)

def _client_ip(handler: BaseHTTPRequestHandler) -> str:
    try:
        return handler.client_address[0]
    except Exception:
        return 'unknown'

def _allowed_ip(ip: str) -> bool:
    cfg = _load_config()
    lst = cfg.get('allowed_ips')
    if isinstance(lst, list) and lst:
        return ip in lst
    # 未配置时默认放行（保持兼容）
    return True

def _rate_limit_hit(bucket: str, ip: str, limit: int, window_sec: int = 60) -> bool:
    now = time.time()
    key = f"{bucket}:{ip}"
    arr = _RL_BUCKETS.get(key) or []
    arr = [t for t in arr if now - t < window_sec]
    if len(arr) >= limit:
        _RL_BUCKETS[key] = arr
        return True
    arr.append(now)
    _RL_BUCKETS[key] = arr
    return False

ALPHA_API_KEY_ENV = "ALPHAVANTAGE_API_KEY"
ALPHA_BASE = "https://www.alphavantage.co/query"


def _cache_get(key):
    item = CACHE.get(key)
    if not item:
        return None
    ts, val = item
    if time.time() - ts > CACHE_TTL:
        return None
    return val


def _cache_set(key, val):
    CACHE[key] = (time.time(), val)


def _get_alpha_key():
    cfg = _load_config()
    return (cfg.get('alphaKey') or os.environ.get(ALPHA_API_KEY_ENV))


def normalize_symbol(symbol: str) -> str:
    s = (symbol or '').strip().upper()
    if s.isdigit() and len(s) == 6:
        if s.startswith(('0','2','3')):
            return s + '.SZ'
        if s.startswith('6'):
            return s + '.SHH'
    return s


def fetch_alpha_global_quote(symbol: str):
    key = _get_alpha_key()
    if not key:
        return {"error": f"missing {ALPHA_API_KEY_ENV}"}
    sym = normalize_symbol(symbol)
    cache_key = f"global_quote:{sym}"
    c = _cache_get(cache_key)
    if c:
        return c
    try:
        resp = requests.get(ALPHA_BASE, params={
            'function': 'GLOBAL_QUOTE', 'symbol': sym, 'apikey': key
        }, timeout=20)
        resp.raise_for_status()
        j = resp.json()
        # 配额/次数用尽检测
        note = j.get('Note') or j.get('Information')
        if note:
            return {"error": "alpha vantage quota exceeded", "reason": "quota", "note": note}
        raw = j.get('Global Quote') or {}
        data = {
            'symbol': raw.get('01. symbol') or sym,
            'open': float(raw.get('02. open') or 0),
            'high': float(raw.get('03. high') or 0),
            'low': float(raw.get('04. low') or 0),
            'price': float(raw.get('05. price') or 0),
            'volume': int(raw.get('06. volume') or 0),
            'latest_day': raw.get('07. latest trading day'),
            'prev_close': float(raw.get('08. previous close') or 0),
            'change': float(raw.get('09. change') or 0),
            'change_percent': raw.get('10. change percent')
        }
        _cache_set(cache_key, data)
        return data
    except requests.exceptions.HTTPError as e:
        return {"error": f"HTTPError {getattr(e.response, 'status_code', '')}", "raw": getattr(e.response, 'text', '')}
    except requests.exceptions.Timeout as e:
        return {"error": f"Timeout {e}", "reason": "network"}
    except requests.exceptions.ConnectionError as e:
        return {"error": f"ConnectionError {e}", "reason": "network"}
    except Exception as e:
        return {"error": str(e)}


def fetch_alpha_daily(symbol: str):
    key = _get_alpha_key()
    if not key:
        return {"error": f"missing {ALPHA_API_KEY_ENV}"}
    sym = normalize_symbol(symbol)
    cache_key = f"daily:{sym}"
    c = _cache_get(cache_key)
    if c:
        return c
    try:
        resp = requests.get(ALPHA_BASE, params={
            'function': 'TIME_SERIES_DAILY', 'symbol': sym, 'apikey': key
        }, timeout=30)
        resp.raise_for_status()
        j = resp.json()
        note = j.get('Note') or j.get('Information')
        if not note:
            series = j.get('Time Series (Daily)') or {}
            rows = []
            for date, d in sorted(series.items()):
                rows.append({
                    'date': date,
                    'open': float(d.get('1. open') or 0),
                    'high': float(d.get('2. high') or 0),
                    'low': float(d.get('3. low') or 0),
                    'close': float(d.get('4. close') or 0),
                    'volume': int(d.get('5. volume') or d.get('6. volume') or 0)
                })
            data = {'symbol': sym, 'rows': rows, 'count': len(rows)}
            _cache_set(cache_key, data)
            return data
        # fallback: 使用60分钟级别最近100条近似替代
        resp2 = requests.get(ALPHA_BASE, params={
            'function': 'TIME_SERIES_INTRADAY', 'symbol': sym, 'interval': '60min', 'apikey': key
        }, timeout=30)
        resp2.raise_for_status()
        j2 = resp2.json()
        series2 = j2.get('Time Series (60min)') or {}
        rows2 = []
        for ts, d in sorted(series2.items()):
            rows2.append({
                'date': ts,
                'open': float(d.get('1. open') or 0),
                'high': float(d.get('2. high') or 0),
                'low': float(d.get('3. low') or 0),
                'close': float(d.get('4. close') or 0),
                'volume': int(d.get('5. volume') or 0)
            })
        data2 = {'symbol': sym, 'rows': rows2, 'count': len(rows2), 'note': 'fallback_intraday_60min'}
        _cache_set(cache_key, data2)
        return data2
    except requests.exceptions.HTTPError as e:
        return {"error": f"HTTPError {getattr(e.response, 'status_code', '')}", "raw": getattr(e.response, 'text', '')}
    except requests.exceptions.Timeout as e:
        return {"error": f"Timeout {e}", "reason": "network"}
    except requests.exceptions.ConnectionError as e:
        return {"error": f"ConnectionError {e}", "reason": "network"}
    except Exception as e:
        return {"error": str(e)}


def fetch_alpha_overview(symbol: str):
    key = _get_alpha_key()
    if not key:
        return {"error": f"missing {ALPHA_API_KEY_ENV}"}
    sym = normalize_symbol(symbol)
    cache_key = f"overview:{sym}"
    c = _cache_get(cache_key)
    if c:
        return c
    try:
        resp = requests.get(ALPHA_BASE, params={'function': 'OVERVIEW', 'symbol': sym, 'apikey': key}, timeout=20)
        resp.raise_for_status()
        j = resp.json()
        note = j.get('Note') or j.get('Information')
        if note:
            return {"error": "alpha vantage quota exceeded", "reason": "quota", "note": note}
        data = {
            'Symbol': j.get('Symbol'),
            'Name': j.get('Name'),
            'Sector': j.get('Sector'),
            'Industry': j.get('Industry'),
            'MarketCapitalization': j.get('MarketCapitalization'),
            'PERatio': j.get('PERatio'),
            'EPS': j.get('EPS'),
            'DividendYield': j.get('DividendYield'),
            'ROE': j.get('ReturnOnEquityTTM'),
            'DebtToEquity': j.get('QuarterlyDebtToEquity'),
        }
        _cache_set(cache_key, data)
        return data
    except requests.exceptions.HTTPError as e:
        return {"error": f"HTTPError {getattr(e.response, 'status_code', '')}", "raw": getattr(e.response, 'text', '')}
    except requests.exceptions.Timeout as e:
        return {"error": f"Timeout {e}", "reason": "network"}
    except requests.exceptions.ConnectionError as e:
        return {"error": f"ConnectionError {e}", "reason": "network"}
    except Exception as e:
        return {"error": str(e)}


def fetch_alpha_news(symbol: str):
    key = _get_alpha_key()
    if not key:
        return {"error": f"missing {ALPHA_API_KEY_ENV}"}
    sym = normalize_symbol(symbol)
    cache_key = f"news:{sym}"
    c = _cache_get(cache_key)
    if c:
        return c
    try:
        resp = requests.get(ALPHA_BASE, params={
            'function': 'NEWS_SENTIMENT', 'tickers': sym, 'apikey': key
        }, timeout=20)
        resp.raise_for_status()
        j = resp.json()
        note = j.get('Note') or j.get('Information')
        if note:
            return {"error": "alpha vantage quota exceeded", "reason": "quota", "note": note}
        feed = j.get('feed') or []
        data = [{
            'title': item.get('title'),
            'summary': item.get('summary'),
            'url': item.get('url'),
            'time_published': item.get('time_published'),
            'sentiment': item.get('overall_sentiment_score'),
            'source': item.get('source')
        } for item in feed][:50]
        _cache_set(cache_key, data)
        return {'symbol': symbol, 'items': data, 'count': len(data)}
    except requests.exceptions.HTTPError as e:
        return {"error": f"HTTPError {getattr(e.response, 'status_code', '')}", "raw": getattr(e.response, 'text', '')}
    except requests.exceptions.Timeout as e:
        return {"error": f"Timeout {e}", "reason": "network"}
    except requests.exceptions.ConnectionError as e:
        return {"error": f"ConnectionError {e}", "reason": "network"}
    except Exception as e:
        return {"error": str(e)}


class Handler(BaseHTTPRequestHandler):
    def _set_cors(self):
        self.send_header("Access-Control-Allow-Origin", ALLOW_ORIGIN)
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def do_OPTIONS(self):
        self.send_response(200)
        self._set_cors()
        self.end_headers()

    def _write_json(self, code: int, obj):
        self.send_response(code)
        self._set_cors()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(obj, ensure_ascii=False).encode('utf-8'))

    def _read_json(self):
        length = int(self.headers.get('Content-Length') or '0')
        if length <= 0:
            return {}
        try:
            raw = self.rfile.read(length)
            return json.loads(raw.decode('utf-8'))
        except Exception:
            return {}

    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            path = parsed.path
        except Exception:
            return self._write_json(400, {"error": "invalid url"})

        if path == "/data/quote":
            symbol = (qs.get('symbol', [''])[0] or '').strip()
            if not symbol:
                return self._write_json(400, {"error": "missing symbol"})
            data = fetch_alpha_global_quote(symbol)
            err = data.get('error') or ''
            reason = data.get('reason')
            code = 200 if not err else (429 if reason=='quota' else (504 if 'Timeout' in err else (502 if 'ConnectionError' in err else (500 if 'HTTPError' in err else 400))))
            return self._write_json(code, data)

        if path == "/data/history":
            symbol = (qs.get('symbol', [''])[0] or '').strip()
            save = (qs.get('save', ['false'])[0] or 'false').lower() in ('true', '1', 'yes')
            if not symbol:
                return self._write_json(400, {"error": "missing symbol"})
            data = fetch_alpha_daily(symbol)
            if 'rows' in data and save:
                try:
                    from data_store import StockDatabase
                    db = StockDatabase()
                    db.upsert_daily_prices(symbol, data['rows'])
                    db.close()
                    data['saved'] = True
                except Exception as e:
                    data['saved'] = False
                    data['save_error'] = str(e)
            err = data.get('error') or ''
            reason = data.get('reason')
            code = 200 if not err else (429 if reason=='quota' else (504 if 'Timeout' in err else (502 if 'ConnectionError' in err else (500 if 'HTTPError' in err else 400))))
            return self._write_json(code, data)

        # 从本地SQLite读取历史数据
        if path == "/data/history_local":
            symbol = (qs.get('symbol', [''])[0] or '').strip()
            limit = int((qs.get('limit', ['500'])[0] or '500'))
            if not symbol:
                return self._write_json(400, {"error": "missing symbol"})
            try:
                from data_store import StockDatabase
                db = StockDatabase()
                rows = db.get_daily_prices(normalize_symbol(symbol), limit=limit)
                db.close()
                return self._write_json(200, {"symbol": normalize_symbol(symbol), "rows": rows, "count": len(rows)})
            except Exception as e:
                return self._write_json(500, {"error": str(e)})

        # 从CSV导入到SQLite（便于离线数据导入）
        if path == "/data/import_csv":
            symbol = (qs.get('symbol', [''])[0] or '').strip()
            file_q = (qs.get('file', [''])[0] or '').strip()
            if not symbol:
                return self._write_json(400, {"error": "missing symbol"})
            base_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'import')
            default_path = os.path.join(base_dir, f"{symbol}.csv")
            csv_path = file_q or default_path
            try:
                os.makedirs(base_dir, exist_ok=True)
                rows = []
                with open(csv_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    # 期望列：date, open, high, low, close, volume
                    for r in reader:
                        rows.append({
                            'date': r.get('date'),
                            'open': float(r.get('open') or 0),
                            'high': float(r.get('high') or 0),
                            'low': float(r.get('low') or 0),
                            'close': float(r.get('close') or 0),
                            'volume': int(r.get('volume') or 0),
                        })
                from data_store import StockDatabase
                db = StockDatabase()
                db.upsert_daily_prices(symbol, rows)
                db.close()
                return self._write_json(200, {"symbol": symbol, "imported": len(rows), "path": csv_path})
            except FileNotFoundError:
                return self._write_json(404, {"error": f"csv not found: {csv_path}"})
            except Exception as e:
                return self._write_json(500, {"error": str(e)})

        if path == "/data/fundamentals":
            symbol = (qs.get('symbol', [''])[0] or '').strip()
            if not symbol:
                return self._write_json(400, {"error": "missing symbol"})
            data = fetch_alpha_overview(symbol)
            err = data.get('error') or ''
            reason = data.get('reason')
            code = 200 if not err else (429 if reason=='quota' else (504 if 'Timeout' in err else (502 if 'ConnectionError' in err else (500 if 'HTTPError' in err else 400))))
            return self._write_json(code, data)

        if path == "/data/news":
            symbol = (qs.get('symbol', [''])[0] or '').strip()
            if not symbol:
                return self._write_json(400, {"error": "missing symbol"})
            data = fetch_alpha_news(symbol)
            err = data.get('error') or ''
            reason = data.get('reason')
            code = 200 if not err else (429 if reason=='quota' else (504 if 'Timeout' in err else (502 if 'ConnectionError' in err else (500 if 'HTTPError' in err else 400))))
            return self._write_json(code, data)

        # 综合分析：返回技术面指标 + 策略建议 + 条件评估
        if path == "/data/analyze":
            symbol = (qs.get('symbol', [''])[0] or '').strip()
            if not symbol:
                return self._write_json(400, {"error": "missing symbol"})
            sym = normalize_symbol(symbol)
            source = (qs.get('source', [''])[0] or '').strip().lower()
            def _num(q, d=None):
                try:
                    return float((qs.get(q, [str(d or '')])[0] or '').strip()) if qs.get(q) else d
                except Exception:
                    return d
            conds = {
                'low': _num('low'),
                'high': _num('high'),
                'max_pe': _num('max_pe'),
                'min_div': _num('min_div'),
                'min_rsi': _num('min_rsi'),
                'max_vol': _num('max_vol')
            }

            if source == 'local':
                try:
                    from data_store import StockDatabase
                    db = StockDatabase()
                    rows = db.get_daily_prices(sym, limit=500)
                    db.close()
                    hist = {'symbol': sym, 'rows': rows, 'count': len(rows)}
                except Exception as e:
                    return self._write_json(500, {'error': str(e)})
                quote = {'price': rows[0]['close'] if rows else None}
                funda = {}
            else:
                quote = fetch_alpha_global_quote(sym)
                hist = fetch_alpha_daily(sym)
                funda = fetch_alpha_overview(sym)
                if quote.get('error'):
                    return self._write_json(400, {'error': quote.get('error')})
                if hist.get('error'):
                    try:
                        from data_store import StockDatabase
                        db = StockDatabase()
                        rows = db.get_daily_prices(sym, limit=500)
                        db.close()
                        hist = {'symbol': sym, 'rows': rows, 'count': len(rows), 'note': 'fallback_local'}
                    except Exception as e:
                        return self._write_json(400, {'error': hist.get('error')})

            prices = [float(r.get('close') or r.get('price') or 0) for r in hist.get('rows', []) if (r.get('close') or r.get('price'))]
            if not prices:
                return self._write_json(404, {'error': 'no history'})
            last = float(quote.get('price') or prices[-1])

            def sma(arr, n):
                if len(arr) < n:
                    return None
                return sum(arr[-n:]) / n
            def ema(arr, n):
                if len(arr) < n:
                    return None
                k = 2/(n+1)
                e = arr[-n]
                for i in range(len(arr)-n+1, len(arr)):
                    e = arr[i]*k + e*(1-k)
                return e
            def rsi(arr, n=14):
                if len(arr) < n+1:
                    return None
                gains = 0.0
                losses = 0.0
                for i in range(len(arr)-n, len(arr)):
                    d = arr[i] - arr[i-1]
                    if d > 0:
                        gains += d
                    else:
                        losses -= d
                rs = gains / (losses or 1e-6)
                return 100 - 100/(1+rs)
            def annual_vol(arr):
                if len(arr) < 30:
                    return None
                rets = [(arr[i]-arr[i-1])/arr[i-1] for i in range(1, len(arr))]
                n = min(60, len(rets))
                rets = rets[-n:]
                avg = sum(rets)/n
                varr = sum((x-avg)**2 for x in rets)/n
                import math
                return math.sqrt(varr) * math.sqrt(250)

            p20 = sma(prices, 20) or last
            p60 = sma(prices, 60) or last
            e20 = ema(prices, 20) or last
            rsi14 = rsi(prices, 14) or 50
            vol = annual_vol(prices) or 0.25
            chg = ((last - p60) / (p60 or last) * 100) if p60 else 0

            n = min(40, len(prices))
            slice_p = prices[-n:]
            avg = sum(slice_p)/n if n>0 else last
            import math
            std = math.sqrt(sum((x-avg)**2 for x in slice_p)/n) if n>0 else 0.1
            low = avg - 2*std
            high = avg + 2*std

            pe = float(funda.get('PERatio') or 0)
            div = float(funda.get('DividendYield') or 0)

            used_conds = {
                'low': conds['low'] if conds['low'] is not None else low,
                'high': conds['high'] if conds['high'] is not None else high,
                'max_pe': conds['max_pe'] if conds['max_pe'] is not None else None,
                'min_div': conds['min_div'] if conds['min_div'] is not None else None,
                'min_rsi': conds['min_rsi'] if conds['min_rsi'] is not None else 45.0,
                'max_vol': conds['max_vol'] if conds['max_vol'] is not None else 0.50
            }

            checks = []
            def add_check(name, ok, detail):
                checks.append({'name': name, 'ok': bool(ok), 'detail': detail})
            add_check('价格≥下限', last >= used_conds['low'], f"last={last:.2f}, low={used_conds['low']:.2f}")
            add_check('价格≤上限', last <= used_conds['high'], f"last={last:.2f}, high={used_conds['high']:.2f}")
            if conds['max_pe'] is not None:
                add_check('估值PE≤阈值', (pe or 0) <= conds['max_pe'], f"PE={pe}, max={conds['max_pe']}")
            if conds['min_div'] is not None:
                add_check('股息率≥阈值', (div or 0) >= conds['min_div'], f"Div={div}, min={conds['min_div']}")
            add_check('RSI≥阈值', (rsi14 or 0) >= used_conds['min_rsi'], f"RSI14={rsi14:.1f}, min={used_conds['min_rsi']}")
            add_check('波动率≤阈值', (vol or 0) <= used_conds['max_vol'], f"Vol={vol:.3f}, max={used_conds['max_vol']}")

            tone = '偏强' if last > p60 else '偏弱'
            pos = 0.7 if (last>e20 and last>p60) else (0.5 if last>e20 else 0.3)

            return self._write_json(200, {
                'symbol': sym,
                'last': round(last,2),
                'indicators': {
                    'p20': round(p20,2), 'p60': round(p60,2), 'e20': round(e20,2),
                    'rsi14': round(rsi14,1), 'vol': vol,
                    'low': round(low,2), 'high': round(high,2),
                    'chg_pct_vs_p60': round(chg,2)
                },
                'fundamentals': {
                    'PE': pe, 'DividendYield': div
                },
                'summary': f"价格 {last:.2f}，相对SMA60涨跌 {chg:.2f}%，波动率 {(vol*100):.1f}%。动量{tone}。建议仓位 {int(pos*100)}%。观察区间 {low:.2f}~{high:.2f}。",
                'checks': checks
                , 'conditions': used_conds
            })

        # 读取统一配置（敏感字段返回遮罩）
        if path == "/config":
            ip = _client_ip(self)
            if not _allowed_ip(ip):
                return self._write_json(403, {"error": "forbidden", "ip": ip})
            cfg = _load_config()
            def mask(s):
                n = len(s or '')
                return '*' * min(n, 24) + ('…' if n > 24 else '') if n > 0 else ''
            # 返回敏感字段遮罩 + 仪表板默认配置（统一管理）
            return self._write_json(200, {
                'alphaKey_mask': mask(cfg.get('alphaKey') or ''),
                'llmKey_mask': mask(cfg.get('llmKey') or ''),
                'llmEndpoint': cfg.get('llmEndpoint'),
                'llmModel': cfg.get('llmModel'),
                # 仪表板默认项（可选）：symbol、source、url、interval、simple模式
                'dashboardDefaultSymbol': cfg.get('dashboardDefaultSymbol'),
                'dashboardSource': cfg.get('dashboardSource'),
                'dashboardUrl': cfg.get('dashboardUrl'),
                'dashboardInterval': cfg.get('dashboardInterval'),
                'dashboardSimple': cfg.get('dashboardSimple')
            })

        # 启动每日增量更新（异步子进程，返回pid与日志路径）
        if path == "/data/run_daily_update":
            file_q = (qs.get('file', [''])[0] or '').strip()
            symbols_q = (qs.get('symbols', [''])[0] or '').strip()
            sleep_q = int((qs.get('sleep', ['15'])[0] or '15'))
            try:
                base_dir = os.path.dirname(os.path.dirname(__file__))
                script = os.path.join(os.path.dirname(__file__), 'daily_update.py')
                symbols_file = file_q or os.path.join(base_dir, 'data', 'symbols.txt')
                logs_dir = os.path.join(base_dir, 'data', 'logs')
                os.makedirs(logs_dir, exist_ok=True)
                stamp = time.strftime('%Y%m%d-%H%M%S')
                log_path = os.path.join(logs_dir, f'daily_update-{stamp}.log')
                last_summary = os.path.join(logs_dir, 'daily_update-last.json')
                args = [sys.executable or 'python', script, '-f', symbols_file, '--sleep', str(sleep_q)]
                if symbols_q:
                    args += ['-s', symbols_q]
                # 将日志与摘要路径传递给子进程，便于前端查询
                args += ['--summary', last_summary, '--log', log_path]
                f = open(log_path, 'w', encoding='utf-8')
                proc = subprocess.Popen(args, stdout=f, stderr=f)
                return self._write_json(200, {"status": "started", "pid": proc.pid, "log_path": log_path, "summary_path": last_summary})
            except Exception as e:
                return self._write_json(500, {"error": str(e)})

        # 查询最近一次增量更新摘要
        if path == "/data/daily_update_status":
            try:
                base_dir = os.path.dirname(os.path.dirname(__file__))
                summary_path = os.path.join(base_dir, 'data', 'logs', 'daily_update-last.json')
                if not os.path.exists(summary_path):
                    return self._write_json(404, {"error": "no summary"})
                with open(summary_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return self._write_json(200, data)
            except Exception as e:
                return self._write_json(500, {"error": str(e)})

        # 计划任务开关：enable=true/false，time=HH:mm（启用时可选）
        if path == "/data/schedule/toggle":
            enable = (qs.get('enable', ['true'])[0] or 'true').lower() in ('true','1','yes')
            time_str = (qs.get('time', ['09:00'])[0] or '09:00').strip()
            try:
                base_dir = os.path.dirname(os.path.dirname(__file__))
                script_path = os.path.join(base_dir, 'scripts', 'register_daily_update.ps1')
                if enable:
                    # 调用现有脚本注册计划任务
                    cmd = [
                        'powershell', '-ExecutionPolicy', 'Bypass', '-File', script_path, '-DailyTime', time_str
                    ]
                    proc = subprocess.run(cmd, cwd=base_dir, capture_output=True, text=True)
                    if proc.returncode == 0:
                        return self._write_json(200, {"enabled": True, "time": time_str, "output": proc.stdout})
                    else:
                        return self._write_json(500, {"enabled": False, "error": proc.stderr})
                else:
                    # 删除计划任务
                    cmd = ['schtasks', '/Delete', '/TN', 'AlphaCouncilDailyUpdate', '/F']
                    proc = subprocess.run(cmd, cwd=base_dir, capture_output=True, text=True)
                    if proc.returncode == 0:
                        return self._write_json(200, {"enabled": False, "output": proc.stdout})
                    else:
                        return self._write_json(500, {"enabled": True, "error": proc.stderr})
            except Exception as e:
                return self._write_json(500, {"error": str(e)})

        # 查询计划任务状态
        if path == "/data/schedule/status":
            try:
                cmd = ['schtasks', '/Query', '/TN', 'AlphaCouncilDailyUpdate']
                proc = subprocess.run(cmd, capture_output=True, text=True)
                if proc.returncode == 0:
                    return self._write_json(200, {"enabled": True, "raw": proc.stdout})
                else:
                    return self._write_json(200, {"enabled": False, "raw": proc.stderr})
            except Exception as e:
                return self._write_json(500, {"error": str(e)})

        return self._write_json(404, {"error": "Not Found"})

    def do_POST(self):
        try:
            parsed = urlparse(self.path)
            path = parsed.path
        except Exception:
            return self._write_json(400, {"error": "invalid url"})

        # 写入统一配置：密钥 + 仪表板默认项（限流 + 审计 + 白名单）
        if path == "/config":
            ip = _client_ip(self)
            if not _allowed_ip(ip):
                return self._write_json(403, {"error": "forbidden", "ip": ip})
            if _rate_limit_hit('config_write', ip, limit=10, window_sec=60):
                return self._write_json(429, {"error": "rate limit", "note": "too many writes", "ip": ip})
            payload = self._read_json()
            allow_keys = (
                'alphaKey','llmEndpoint','llmModel','llmKey',
                'dashboardDefaultSymbol','dashboardSource','dashboardUrl','dashboardInterval','dashboardSimple'
            )
            allowed = {k: payload.get(k) for k in allow_keys if k in payload}
            try:
                _save_config(allowed)
                # 审计：仅记录键名与长度，不记录明文
                try:
                    os.makedirs(AUDIT_DIR, exist_ok=True)
                    stamp = time.strftime('%Y-%m-%d %H:%M:%S')
                    sensitive = {k: (len(allowed.get(k) or '') if isinstance(allowed.get(k), str) else None) for k in ('alphaKey','llmKey') if k in allowed}
                    non_sensitive = {k: (str(allowed.get(k))[:128] if k not in ('alphaKey','llmKey') else None) for k in allowed.keys()}
                    line = json.dumps({
                        'ts': stamp,
                        'ip': ip,
                        'changed_keys': list(allowed.keys()),
                        'sensitive_len': sensitive,
                        'non_sensitive_preview': {k:v for k,v in non_sensitive.items() if v is not None}
                    }, ensure_ascii=False)
                    with open(AUDIT_LOG, 'a', encoding='utf-8') as f:
                        f.write(line + "\n")
                except Exception:
                    pass
                return self._write_json(200, {"status": "ok"})
            except Exception as e:
                return self._write_json(500, {"error": str(e)})

        if path == "/data/import_csv":
            try:
                parsed = urlparse(self.path)
                qs = parse_qs(parsed.query)
                symbol = (qs.get('symbol', [''])[0] or '').strip()
                if not symbol:
                    return self._write_json(400, {"error": "missing symbol"})
                raw = self._read_json()
                content = raw.get('content') if isinstance(raw, dict) else None
                if not content:
                    return self._write_json(400, {"error": "missing content"})
                rows = []
                import io
                f = io.StringIO(content)
                reader = csv.DictReader(f)
                for r in reader:
                    rows.append({
                        'date': r.get('date'),
                        'open': float(r.get('open') or 0),
                        'high': float(r.get('high') or 0),
                        'low': float(r.get('low') or 0),
                        'close': float(r.get('close') or 0),
                        'volume': int(r.get('volume') or 0),
                    })
                from data_store import StockDatabase
                db = StockDatabase()
                db.upsert_daily_prices(normalize_symbol(symbol), rows)
                db.close()
                return self._write_json(200, {"symbol": normalize_symbol(symbol), "imported": len(rows)})
            except Exception as e:
                return self._write_json(500, {"error": str(e)})

        return self._write_json(404, {"error": "Not Found"})


def main():
    port = 8788
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    server = HTTPServer(('0.0.0.0', port), Handler)
    print(f"Data gateway running on http://localhost:{port}/data/quote?symbol=IBM")

    # 启动 WebSocket 推送服务（端口默认为 HTTP+1，例如 8789）
    ws_port = port + 1
    if websockets is None:
        print("[WS] websockets 未安装，跳过 WebSocket 服务。可在 requirements 中添加 'websockets'。")
    else:
        async def ws_quote_handler(websocket, path):
            # 解析 symbol 参数，形如 /ws/quote?symbol=IBM
            try:
                parsed = urlparse(path or "/")
                qs = parse_qs(parsed.query)
                symbol = (qs.get('symbol', [''])[0] or '').strip()
                if not symbol:
                    await websocket.send(json.dumps({"error":"missing symbol"}, ensure_ascii=False))
                    return
                # 简单循环推送：读取 Alpha Vantage（含缓存），构造统一payload
                while True:
                    data = fetch_alpha_global_quote(symbol)
                    payload = {
                        'symbol': data.get('symbol') or symbol,
                        'last': data.get('price') or data.get('close') or 0,
                        'volume': data.get('volume') or 0,
                        'ts': int(time.time())
                    }
                    await websocket.send(json.dumps(payload, ensure_ascii=False))
                    await asyncio.sleep(2)
            except Exception as e:
                try:
                    await websocket.send(json.dumps({"error": str(e)}, ensure_ascii=False))
                except Exception:
                    pass

        async def ws_main():
            async with websockets.serve(ws_quote_handler, '0.0.0.0', ws_port, ping_interval=20, ping_timeout=20):
                print(f"[WS] WebSocket running on ws://localhost:{ws_port}/ws/quote?symbol=IBM")
                await asyncio.Future()  # run forever

        def start_ws_thread():
            try:
                asyncio.run(ws_main())
            except Exception as e:
                print(f"[WS] start failed: {e}")

        t = threading.Thread(target=start_ws_thread, daemon=True)
        t.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
