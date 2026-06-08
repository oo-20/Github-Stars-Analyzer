import requests
import time
import os
from datetime import datetime


GITHUB_API = "https://api.github.com"
HEADERS = {
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "GitHubStarsAnalyzer/1.0"
}
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
PROXIES = None

# Auto-detect system proxy from environment vars and Windows registry
import os as _os
import winreg as _wr

def _detect_proxies():
    _proxies = {}
    _no_proxy = set(["127.0.0.1", "localhost", "<local>"])
    
    # 1) Try environment variables first
    for _var in ["HTTP_PROXY", "http_proxy"]:
        _v = _os.environ.get(_var)
        if _v:
            _proxies["http"] = _v
            break
    for _var in ["HTTPS_PROXY", "https_proxy"]:
        _v = _os.environ.get(_var)
        if _v:
            _proxies["https"] = _v
            break
    
    # 2) Try Windows registry
    if not _proxies:
        try:
            _key = _wr.OpenKey(_wr.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
            _enable, _ = _wr.QueryValueEx(_key, "ProxyEnable")
            _server, _ = _wr.QueryValueEx(_key, "ProxyServer")
            _override, _ = _wr.QueryValueEx(_key, "ProxyOverride")
            _wr.CloseKey(_key)
            if _enable and _server:
                _server = _server.strip()
                if "=" in _server:
                    for _part in _server.replace(" ", "").split(";"):
                        if "=" in _part:
                            _p, _a = _part.split("=", 1)
                            _proxies[_p.strip()] = f"http://{_a.strip()}"
                else:
                    _proxies["http"] = f"http://{_server}"
                    _proxies["https"] = f"http://{_server}"
                if _override:
                    for _p in _override.replace(" ", "").split(";"):
                        if _p.strip():
                            _no_proxy.add(_p.strip())
        except Exception as _e:
            pass
    
    return _proxies if _proxies else None, _no_proxy

PROXIES, NO_PROXY = _detect_proxies()
# 自动检测代理



def _headers():
    h = HEADERS.copy()
    if TOKEN:
        h["Authorization"] = f"token {TOKEN}"
    return h


def _rate_limit_safe(response):
    """检查剩余请求数，必要时等待"""
    remaining = int(response.headers.get("X-RateLimit-Remaining", 60))
    reset_time = int(response.headers.get("X-RateLimit-Reset", 0))
    if remaining < 5:
        wait = max(reset_time - time.time() + 5, 0)
        if wait > 0:
            time.sleep(wait)


def search_repositories(query, sort="stars", order="desc", per_page=100, max_pages=10):
    """
    搜索 GitHub 仓库。
    sort: stars, updated, help-wanted-issues
    """
    all_items = []
    for page in range(1, max_pages + 1):
        url = f"{GITHUB_API}/search/repositories"
        params = {
            "q": query,
            "sort": sort,
            "order": order,
            "per_page": per_page,
            "page": page
        }
        try:
            resp = requests.get(url, headers=_headers(), params=params, proxies=PROXIES, timeout=15)
            if resp.status_code != 200:
                break
            data = resp.json()
            items = data.get("items", [])
            if not items:
                break
            all_items.extend(items)
            _rate_limit_safe(resp)
        except Exception as _e:
            print(f"[Fetcher] API error: {_e}")
            break
    return all_items


def get_repo_details(full_name):
    """获取仓库详细信息"""
    url = f"{GITHUB_API}/repos/{full_name}"
    try:
        resp = requests.get(url, headers=_headers(), proxies=PROXIES, timeout=15)
        if resp.status_code == 200:
            _rate_limit_safe(resp)
            return resp.json()
    except Exception as _e:
        pass
    return None


def get_repo_readme(full_name):
    """获取仓库 README"""
    url = f"{GITHUB_API}/repos/{full_name}/readme"
    try:
        resp = requests.get(url, headers=_headers(), proxies=PROXIES, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            import base64
            content = base64.b64decode(data.get("content", "")).decode("utf-8")
            return content
    except Exception as _e:
        pass
    return None


def get_star_history(full_name):
    """使用 Star History API 获取星标历史"""
    url = f"https://api.star-history.com/svg?repos={full_name}&type=Date"
    try:
        resp = requests.get(url, proxies=PROXIES, timeout=15)
        return resp.url if resp.status_code == 200 else None
    except Exception as _e:
        return None


QUERIES = {
    "ai_agent": [
        # 高精度查询（低门槛）
        "topic:ai-agent stars:>100",
        "AI agent framework stars:>200",
        "autonomous agent AI stars:>100",
        "LLM agent tool-use stars:>50",
        "multi-agent system stars:>100",
        "agent platform stars:>50",
        "AI coding agent stars:>100",
        "agentic framework stars:>50",
        # 发现查询（不限 stars，按活跃度）
        "AI agent framework updated:>2025-01-01",
        "autonomous agent updated:>2025-01-01",
    ],
    "computer_science": [
        "topic:machine-learning stars:>200",
        "machine learning framework stars:>300",
        "deep learning library stars:>500",
        "topic:computer-vision stars:>100",
        "NLP natural language processing stars:>200",
        "reinforcement learning stars:>100",
        "data science library stars:>300",
        "recommender system stars:>100",
        "deep learning updated:>2025-01-01 stars:>50",
        "computer science learning stars:>50",
    ],
    "llm": [
        "topic:large-language-model stars:>200",
        "LLM chatbot stars:>200",
        "RAG retrieval augmented generation stars:>100",
        "prompt engineering framework stars:>50",
        "fine-tuning LLM stars:>50",
        "topic:text-to-image stars:>100",
        "LLM evaluation benchmark stars:>50",
        "voice AI speech recognition stars:>100",
        "LLM application updated:>2025-01-01",
        "RAG updated:>2025-01-01 stars:>20",
    ],
    "developer_tools": [
        "topic:developer-tools stars:>200",
        "developer tools CLI stars:>200",
        "code assistant AI stars:>100",
        "topic:productivity-tools stars:>100",
        "database client tool stars:>100",
        "AI API wrapper stars:>50",
        "CLI tool updated:>2025-01-01",
        "developer productivity stars:>50",
    ]
}

CATEGORY_NAMES = {
    "ai_agent": "🤖 AI Agent",
    "computer_science": "💻 计算机科学",
    "llm": "🧠 大语言模型",
    "developer_tools": "🛠️ 开发者工具",
    "rising_stars": "⭐ 潜力新星"
}

CATEGORY_DESCRIPTIONS = {
    "ai_agent": "人工智能代理框架、自主代理、多代理协作系统",
    "computer_science": "机器学习、深度学习、计算机视觉、NLP 等核心领域",
    "llm": "大语言模型、对话系统、RAG、提示工程、微调",
    "developer_tools": "开发者工具、CLI、AI 编程助手、效率工具",
    "rising_stars": "近期快速增长但总体 stars 较低的高潜力项目"
}
