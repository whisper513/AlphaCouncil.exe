#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AlphaCouncil 启动器（应用层）

职责：
- 启动静态网页服务，提供仪表板页面；
- 启动 LLM 代理（底层服务），转发到外部大模型接口；
- 打开内嵌 Web 窗口（pywebview）或回退到默认浏览器。

说明：
- 端口占用时自动回退到可用端口；
- 退出时优雅关闭所有服务。
"""

import os
import sys
import socket
import threading
import time
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
import requests
from pathlib import Path
import subprocess


# ---------------------------
# 工具：端口选择与资源路径
# ---------------------------
def pick_port(preferred: int, attempts: int = 3, step: int = 2) -> int:
    """选择可用端口，优先使用 preferred；否则递增尝试。"""
    p = preferred
    for _ in range(attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                p += step
    return p


def get_ui_dir() -> str:
    """获取 UI 资源目录（支持 PyInstaller 打包后路径）。"""
    if hasattr(sys, "_MEIPASS"):
        # 打包后，资源通过 --add-data 放在 app/ui 下
        return os.path.join(sys._MEIPASS, "app", "ui")
    # 源码运行：本文件位于 ABC/app/launcher.py
    base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "ui")


def get_app_version(default: str = "") -> str:
    """读取应用版本号，优先从打包内置 VERSION 文件。"""
    candidates = []
    try:
        if hasattr(sys, "_MEIPASS"):
            candidates.append(os.path.join(sys._MEIPASS, "VERSION"))
        # 源码运行场景
        here = Path(__file__).resolve().parent
        candidates.append(str(here / "VERSION"))
        candidates.append(str((here / ".." / "build" / "VERSION").resolve()))
    except Exception:
        pass
    for p in candidates:
        try:
            if p and os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    v = f.read().strip()
                    if v:
                        return v
        except Exception:
            continue
    return default


# ---------------------------
# 静态站点（应用层界面）
# ---------------------------
class SPAHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=get_ui_dir(), **kwargs)

    def end_headers(self):
        # 禁用缓存，确保调试时实时加载
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def start_static_server(port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), SPAHandler)
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    print(f"Static server: http://127.0.0.1:{port}/alpha-dashboard.html")
    return server


# ---------------------------
# LLM 代理（底层服务）
# ---------------------------
ALLOW_ORIGIN = "*"

class LLMProxyHandler(BaseHTTPRequestHandler):
    @staticmethod
    def _resolve_api_key(name: str, endpoint: str, explicit_key: str | None) -> str | None:
        """从显式参数、环境变量或本地配置解析API Key。
        优先级：显式 > 基于name映射/域名映射的环境变量 > 通用变量 > 配置文件(ABC/config/app.json: llmKey)。
        """
        if explicit_key:
            return explicit_key
        name_l = (name or "").strip().lower()
        host = ""
        try:
            host = urlparse(endpoint or "").netloc.lower()
        except Exception:
            pass

        env_candidates = []
        if name_l == "openai" or (host and "openai" in host):
            env_candidates.append("OPENAI_API_KEY")
        if name_l == "deepseek" or (host and "deepseek" in host):
            env_candidates.append("DEEPSEEK_API_KEY")
        # 通用兜底
        env_candidates.extend(["LLM_API_KEY", "API_KEY"])

        for var in env_candidates:
            val = os.environ.get(var)
            if val:
                return val
        try:
            base = Path(__file__).resolve().parent.parent
            cfg_path = base / "config" / "app.json"
            if cfg_path.exists():
                with open(cfg_path, "r", encoding="utf-8") as f:
                    j = json.load(f)
                k = j.get("llmKey")
                if k:
                    return k
        except Exception:
            pass
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

        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            payload = json.loads(body.decode("utf-8"))
        except Exception as e:
            self.send_response(400)
            self._set_cors()
            self.end_headers()
            self.wfile.write(json.dumps({"error": f"invalid json: {e}"}).encode("utf-8"))
            return

        # 多模型聚合：providers 列表
        providers = payload.get("providers")
        if isinstance(providers, list) and providers:
            results = []
            for i, prov in enumerate(providers):
                ep = prov.get("endpoint")
                key = self._resolve_api_key(prov.get("name"), ep, prov.get("api_key"))
                fb = prov.get("forward_body") or {}
                if not ep:
                    results.append({"provider": f"p{i}", "error": "missing endpoint"})
                    continue
                # 内置模拟：builtin:echo
                if isinstance(ep, str) and ep.startswith("builtin:echo"):
                    content = " ".join([
                        msg.get("content", "") for msg in fb.get("messages", []) if isinstance(msg, dict)
                    ]) or fb.get("prompt") or "OK"
                    j = {
                        "choices": [{"message": {"role": "assistant", "content": f"Echo: {content}"}}]
                    }
                    text = j["choices"][0]["message"]["content"]
                    results.append({"provider": prov.get("name") or f"p{i}", "text": text, "raw": j})
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
                        j.get("choices", [{}])[0].get("message", {}).get("content")
                        or j.get("output")
                        or json.dumps(j, ensure_ascii=False)
                    )
                    results.append({"provider": prov.get("name") or f"p{i}", "text": text, "raw": j})
                except requests.exceptions.HTTPError as e:
                    content = e.response.text if getattr(e, "response", None) is not None else ""
                    results.append({"provider": prov.get("name") or f"p{i}", "error": f"HTTPError {getattr(e.response, 'status_code', '')}", "raw": content})
                except requests.exceptions.ConnectionError as e:
                    results.append({"provider": prov.get("name") or f"p{i}", "error": f"ConnectionError {e}"})
                except requests.exceptions.Timeout as e:
                    results.append({"provider": prov.get("name") or f"p{i}", "error": f"Timeout {e}"})
                except Exception as e:
                    results.append({"provider": prov.get("name") or f"p{i}", "error": str(e)})

            combined = "\n\n".join([
                f"【{r.get('provider')}】\n{r.get('text') or r.get('error')}" for r in results
            ])
            self.send_response(200)
            self._set_cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"outputs": results, "combined": combined}, ensure_ascii=False).encode("utf-8"))
            return

        # 单模型直通
        endpoint = payload.get("endpoint")
        api_key = self._resolve_api_key(payload.get("name"), endpoint, payload.get("api_key"))
        forward_body = payload.get("forward_body") or {
            "model": payload.get("model", ""),
            "messages": payload.get("messages", []),
            "temperature": payload.get("temperature", 0.2),
            "stream": False,
        }
        if not endpoint:
            self.send_response(400)
            self._set_cors()
            self.end_headers()
            self.wfile.write(json.dumps({"error": "missing endpoint"}).encode("utf-8"))
            return

        # 内置模拟：builtin:echo
        if isinstance(endpoint, str) and endpoint.startswith("builtin:echo"):
            content = " ".join([
                msg.get("content", "") for msg in forward_body.get("messages", []) if isinstance(msg, dict)
            ]) or forward_body.get("prompt") or "OK"
            j = {
                "choices": [{"message": {"role": "assistant", "content": f"Echo: {content}"}}]
            }
            data = json.dumps(j, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self._set_cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)
            return

        try:
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            resp = requests.post(endpoint, json=forward_body, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.text.encode("utf-8")
            self.send_response(200)
            self._set_cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)
        except requests.exceptions.HTTPError as e:
            content = e.response.text if getattr(e, "response", None) is not None else ""
            code = getattr(e.response, "status_code", 500)
            self.send_response(code)
            self._set_cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(content.encode("utf-8") if content else json.dumps({"error": str(e)}).encode("utf-8"))
        except requests.exceptions.ConnectionError as e:
            self.send_response(502)
            self._set_cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": f"upstream connection error: {e}"}).encode("utf-8"))
        except requests.exceptions.Timeout as e:
            self.send_response(504)
            self._set_cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": f"upstream timeout: {e}"}).encode("utf-8"))
        except Exception as e:
            self.send_response(500)
            self._set_cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))


def start_llm_proxy(port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), LLMProxyHandler)
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    print(f"LLM proxy: http://127.0.0.1:{port}/llm")
    return server


def start_data_gateway(port: int) -> subprocess.Popen | None:
    try:
      here = Path(__file__).resolve()
      script = (here.parent.parent / "services" / "data-gateway.py").resolve()
      if not script.exists():
        print("Data gateway script not found, skip.")
        return None
      proc = subprocess.Popen([sys.executable or "python", str(script), str(port)], cwd=str(here.parent.parent))
      print(f"Data gateway: http://127.0.0.1:{port}/data/quote?symbol=IBM")
      return proc
    except Exception as e:
      print("Data gateway start failed:", e)
      return None


# ---------------------------
# 入口：启动服务与窗口
# ---------------------------
def main():
    static_port = pick_port(5173)
    llm_port = pick_port(8787)
    data_port = pick_port(8788)
    static_server = start_static_server(static_port)
    llm_server = start_llm_proxy(llm_port)
    data_proc = start_data_gateway(data_port)

    url = f"http://127.0.0.1:{static_port}/alpha-dashboard.html"
    version = get_app_version("")
    # 小补丁：将页面默认 LLM 代理地址指向当前端口（如果不同于 8787，可在页面中手动改）
    print("Launching UI:", url)
    try:
        import webview
        title = f"AlphaCouncil 实时分析仪表板" + (f" v{version}" if version else "")
        window = webview.create_window(title, url, width=1280, height=800)
        webview.start()
    except Exception as e:
        # WebView 环境不可用时，回退到默认浏览器
        print("WebView 启动失败，回退到浏览器：", e)
        if version:
            print(f"AlphaCouncil 版本：{version}")
        import webbrowser
        webbrowser.open(url)
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass

    # 退出时关闭服务
    try:
        static_server.shutdown()
    except Exception:
        pass
    try:
        llm_server.shutdown()
    except Exception:
        pass
    try:
        if data_proc:
            data_proc.terminate()
    except Exception:
        pass


if __name__ == "__main__":
    main()
