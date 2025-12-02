#!/usr/bin/env python3
import json
import sys
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
import requests
from urllib.parse import urlparse

ALLOW_ORIGIN = "*"

# 读取统一配置（ABC/config/app.json）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BASE_DIR, 'config')
CONFIG_PATH = os.path.join(CONFIG_DIR, 'app.json')
_RL_BUCKETS = {}

def _load_config():
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

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

class Handler(BaseHTTPRequestHandler):
    @staticmethod
    def _resolve_api_key(name: str, endpoint: str, explicit_key: str | None) -> str | None:
        """解析API Key：显式 > name映射 > 域名映射 > 通用变量。支持OPENAI_API_KEY、DEEPSEEK_API_KEY、LLM_API_KEY、API_KEY。"""
        # 1) 优先使用显式传入（不推荐前端传，但兼容）
        if explicit_key:
            return explicit_key
        # 2) 读取统一配置中的 llmKey（仅本机）
        cfg = _load_config()
        k = (cfg.get('llmKey') or '').strip()
        if k:
            return k
        name_l = (name or '').strip().lower()
        host = ''
        try:
            host = urlparse(endpoint or '').netloc.lower()
        except Exception:
            pass
        env_candidates = []
        if name_l == 'openai' or (host and 'openai' in host):
            env_candidates.append('OPENAI_API_KEY')
        if name_l == 'deepseek' or (host and 'deepseek' in host):
            env_candidates.append('DEEPSEEK_API_KEY')
        env_candidates.extend(['LLM_API_KEY', 'API_KEY'])
        for var in env_candidates:
            val = os.environ.get(var)
            if val:
                return val
        return None
    def _set_cors(self):
        self.send_header("Access-Control-Allow-Origin", ALLOW_ORIGIN)
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")

    def do_OPTIONS(self):
        self.send_response(200)
        self._set_cors()
        self.end_headers()

    def do_POST(self):
        if self.path not in ("/llm", "/v1/chat/completions"):
            self.send_response(404)
            self._set_cors()
            self.end_headers()
            self.wfile.write(b"Not Found")
            return

        ip = _client_ip(self)
        if not _allowed_ip(ip):
            self.send_response(403)
            self._set_cors()
            self.end_headers()
            self.wfile.write(json.dumps({"error":"forbidden","ip":ip}).encode('utf-8'))
            return
        # 默认 60 次/分钟/IP（可在需要时调整）
        if _rate_limit_hit('llm_post', ip, limit=60, window_sec=60):
            self.send_response(429)
            self._set_cors()
            self.end_headers()
            self.wfile.write(json.dumps({"error":"rate limit","note":"too many requests","ip":ip}).encode('utf-8'))
            return

        try:
            length = int(self.headers.get('Content-Length', '0'))
            body = self.rfile.read(length)
            payload = json.loads(body.decode('utf-8'))
        except Exception as e:
            self.send_response(400)
            self._set_cors()
            self.end_headers()
            self.wfile.write(json.dumps({"error": f"invalid json: {e}"}).encode('utf-8'))
            return

        # 多模型聚合支持：providers 列表
        providers = payload.get('providers')
        if isinstance(providers, list) and providers:
            results = []
            for i, prov in enumerate(providers):
                ep = prov.get('endpoint')
                key = self._resolve_api_key(prov.get('name'), ep, prov.get('api_key'))
                fb = prov.get('forward_body') or {}
                if not ep:
                    results.append({"provider": f"p{i}", "error": "missing endpoint"})
                    continue
                # 内置模拟：builtin:echo
                if isinstance(ep, str) and ep.startswith('builtin:echo'):
                    content = ' '.join([
                        msg.get('content', '') for msg in fb.get('messages', []) if isinstance(msg, dict)
                    ]) or fb.get('prompt') or 'OK'
                    j = {
                        'choices': [{'message': {'role': 'assistant', 'content': f'Echo: {content}'}}]
                    }
                    text = j['choices'][0]['message']['content']
                    results.append({"provider": prov.get('name') or f"p{i}", "text": text, "raw": j})
                    continue
                try:
                    headers = {"Content-Type": "application/json"}
                    if key:
                        headers["Authorization"] = f"Bearer {key}"
                    resp = requests.post(ep, json=fb, headers=headers, timeout=30)
                    resp.raise_for_status()
                    try:
                        j = resp.json()
                    except Exception:
                        j = {"raw": resp.text}
                    text = (
                        j.get('choices', [{}])[0].get('message', {}).get('content')
                        or j.get('output')
                        or json.dumps(j, ensure_ascii=False)
                    )
                    results.append({"provider": prov.get('name') or f"p{i}", "text": text, "raw": j})
                except requests.exceptions.HTTPError as e:
                    content = e.response.text if getattr(e, 'response', None) is not None else ''
                    results.append({"provider": prov.get('name') or f"p{i}", "error": f"HTTPError {getattr(e.response, 'status_code', '')}", "raw": content})
                except requests.exceptions.ConnectionError as e:
                    results.append({"provider": prov.get('name') or f"p{i}", "error": f"ConnectionError {e}"})
                except requests.exceptions.Timeout as e:
                    results.append({"provider": prov.get('name') or f"p{i}", "error": f"Timeout {e}"})
                except Exception as e:
                    results.append({"provider": prov.get('name') or f"p{i}", "error": str(e)})

            combined = "\n\n".join([
                f"【{r.get('provider')}】\n{r.get('text') or r.get('error')}" for r in results
            ])
            self.send_response(200)
            self._set_cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"outputs": results, "combined": combined}, ensure_ascii=False).encode('utf-8'))
            return

        # 单模型直通
        endpoint = payload.get('endpoint')
        api_key = self._resolve_api_key(payload.get('name'), endpoint, payload.get('api_key'))
        forward_body = payload.get('forward_body') or {
            'model': payload.get('model', ''),
            'messages': payload.get('messages', []),
            'temperature': payload.get('temperature', 0.2),
            'stream': False
        }
        if not endpoint:
            self.send_response(400)
            self._set_cors()
            self.end_headers()
            self.wfile.write(json.dumps({"error": "missing endpoint"}).encode('utf-8'))
            return

        # 内置模拟：builtin:echo
        if isinstance(endpoint, str) and endpoint.startswith('builtin:echo'):
            content = ' '.join([
                msg.get('content', '') for msg in forward_body.get('messages', []) if isinstance(msg, dict)
            ]) or forward_body.get('prompt') or 'OK'
            j = {
                'choices': [{'message': {'role': 'assistant', 'content': f'Echo: {content}'}}]
            }
            data = json.dumps(j, ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            self._set_cors()
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(data)
            return

        try:
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            resp = requests.post(endpoint, json=forward_body, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.text.encode('utf-8')
            self.send_response(200)
            self._set_cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)
        except requests.exceptions.HTTPError as e:
            content = e.response.text if getattr(e, 'response', None) is not None else ''
            code = getattr(e.response, 'status_code', 500)
            self.send_response(code)
            self._set_cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(content.encode('utf-8') if content else json.dumps({"error": str(e)}).encode('utf-8'))
        except requests.exceptions.ConnectionError as e:
            self.send_response(502)
            self._set_cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": f"upstream connection error: {e}"}).encode('utf-8'))
        except requests.exceptions.Timeout as e:
            self.send_response(504)
            self._set_cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": f"upstream timeout: {e}"}).encode('utf-8'))
        except Exception as e:
            self.send_response(500)
            self._set_cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))


def main():
    port = 8787
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    server = HTTPServer(('0.0.0.0', port), Handler)
    print(f"LLM proxy running on http://localhost:{port}/llm")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    main()