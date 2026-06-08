"""GitHub Stars Analyzer - 后端服务"""
import json, os, time, re, uuid
from threading import Thread, Lock
from flask import Flask, jsonify, render_template, request, redirect, session
from flask_cors import CORS
import requests

# 加载 .env 文件（项目根目录）
_env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

# ── 路径初始化 ──
SRC_DIR = os.path.dirname(__file__)
BASE_DIR = os.path.dirname(SRC_DIR)

app = Flask(__name__, template_folder=os.path.join(SRC_DIR, "templates"))
app.secret_key = os.environ.get("FLASK_SECRET", "github-stars-secret")
CORS(app, supports_credentials=True)

cache = {}
cache_lock = Lock()
cache_time = {}
CACHE_DURATION = 86400  # 24小时
CACHE_PATH = os.path.join(BASE_DIR, "cached_data.json")
FETCHER_PATH = os.path.join(SRC_DIR, "github_fetcher.py")

# ── 启动时加载缓存 ──
def load_cache():
    global cache, cache_time
    if os.path.exists(CACHE_PATH):
        mtime = os.path.getmtime(CACHE_PATH)
        age_days = (time.time() - mtime) / 86400
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                cache = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"  Cache file corrupted ({e}), starting fresh...")
            return None
        cache_time = {"time": time.time()}
        total = cache.get("stats", {}).get("total_repos", 0)
        print(f"  Loaded {total} repos from cache (age: {age_days:.1f} days)")
        return age_days
    return None

# ── 后台抓取更新 ──
_fetch_progress = {"running": False, "fetched": 0, "total": 0}

def fetch_latest():
    """后台线程：重新抓取 GitHub 数据并更新缓存"""
    global _fetch_progress
    _fetch_progress["running"] = True
    _fetch_progress["fetched"] = 0
    _fetch_progress["total"] = 0
    try:
        # 动态导入 fetcher（避免启动时依赖网络）
        import importlib.util as _iu
        spec = _iu.spec_from_file_location("github_fetcher", FETCHER_PATH)
        mod = _iu.module_from_spec(spec)
        spec.loader.exec_module(mod)

        print("[Updater] 开始重新抓取数据...")
        all_raw = []
        for category, queries in mod.QUERIES.items():
            print(f"[Updater] 分类: {mod.CATEGORY_NAMES.get(category, category)}")
            seen = set()
            for query in queries:
                try:
                    repos = mod.search_repositories(query, sort="stars", max_pages=5)
                    for r in repos:
                        name = r.get("full_name", "")
                        if name not in seen:
                            seen.add(name)
                            all_raw.append(r)
                            _fetch_progress["fetched"] = len(all_raw)
                except Exception as e:
                    print(f"[Updater] Query error: {e}")
                time.sleep(0.2)

        if not all_raw:
            print("[Updater] 未获取到数据，跳过更新")
            _fetch_progress["running"] = False
            return

        from analyzer import analyze_trending, categorize_repositories, get_stats_summary
        global_analysis = analyze_trending(all_raw)
        lang_cats = categorize_repositories(all_raw)
        stats = get_stats_summary(all_raw)

        # 按分类整理
        from collections import defaultdict
        cat_repos = defaultdict(list)
        for r in all_raw:
            desc = ((r.get("description") or "") + " " + " ".join(r.get("topics") or [])).lower()
            topics_list = [t.lower() for t in (r.get("topics") or [])]
            for cat, queries in mod.QUERIES.items():
                for q in queries:
                    # Topic 查询：仓库包含该 topic 就直接归入
                    if q.startswith("topic:"):
                        topic_name = q.split()[0].replace("topic:", "").lower()
                        if any(topic_name in t for t in topics_list):
                            cat_repos[cat].append(r)
                            break
                    else:
                        # 关键词匹配
                        keywords = [w.lower() for w in q.split() if not w.startswith("stars:") and not w.startswith(">") and not w.startswith("updated:")]
                        if any(kw in desc for kw in keywords):
                            cat_repos[cat].append(r)
                            break

        # ── 从全部仓库中计算 Rising Stars ──
        rising_candidates = []
        for r in all_raw:
            stars = r.get("stargazers_count", 0)
            spd = r.get("_stars_per_day", 0)
            recent = r.get("_recently_updated", False)
            if stars < 10000 and spd > 1 and recent:
                rising_candidates.append(r)
        rising_candidates.sort(key=lambda r: r.get("_stars_per_day", 0), reverse=True)
        if rising_candidates:
            cat_repos["rising_stars"] = rising_candidates

        new_data = {
            "categories": {},
            "global": global_analysis,
            "language_categories": lang_cats,
            "stats": stats,
            "category_names": mod.CATEGORY_NAMES,
            "category_descriptions": mod.CATEGORY_DESCRIPTIONS,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        for cat, repos in cat_repos.items():
            repos.sort(key=lambda r: r.get("_stars_per_day" if cat == "rising_stars" else "stargazers_count", 0), reverse=True)
            new_data["categories"][cat] = {
                "repos": repos[:500],
                "analysis": analyze_trending(repos),
                "name": mod.CATEGORY_NAMES.get(cat, cat),
                "description": mod.CATEGORY_DESCRIPTIONS.get(cat, "")
            }

        # 写回缓存文件
        tmp = CACHE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(new_data, f, ensure_ascii=False)
        os.replace(tmp, CACHE_PATH)

        global cache, cache_time
        with cache_lock:
            cache = new_data
            cache_time = {"time": time.time()}
        print(f"[Updater] 数据更新完成，共 {len(all_raw)} 个项目")
        _fetch_progress["running"] = False
    except Exception as e:
        print(f"[Updater] 更新失败: {e}")
        import traceback; traceback.print_exc()
        _fetch_progress["running"] = False

# ── 启动时检查是否需要更新 ──
age_days = load_cache()
if age_days is None or age_days >= 7:
    print("  Cache is empty or older than 7 days, starting background fetch...")
    t = Thread(target=fetch_latest, daemon=True)
    t.start()

# ── 构建 repo 查找索引 ──
def build_repo_index():
    idx = {}
    with cache_lock:
        cats = cache.get("categories", {})
        for cat in cats.values():
            for r in cat.get("repos", []):
                if r.get("full_name"):
                    idx[r["full_name"]] = r
        # 也索引 global 里的
        g = cache.get("global", {})
        for key in ["all_time_stars", "fast_growing", "trending"]:
            for r in g.get(key, []):
                if r.get("full_name"):
                    idx[r["full_name"]] = r
    return idx

# ── README 缓存 ──
readme_cache = {}
README_CACHE_DURATION = 3600  # 1小时

# ── GitHub OAuth ──
GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET", "")

@app.route("/api/github/login")
def github_login():
    uri = request.host_url.rstrip("/") + "/api/github/callback"
    return redirect(f"https://github.com/login/oauth/authorize?client_id={GITHUB_CLIENT_ID}&redirect_uri={uri}&scope=public_repo")

@app.route("/api/github/callback")
def github_callback():
    code = request.args.get("code")
    if not code: return redirect("/?error=login_failed")
    uri = request.host_url.rstrip("/") + "/api/github/callback"
    try:
        r = requests.post("https://github.com/login/oauth/access_token",
            headers={"Accept":"application/json"},
            json={"client_id":GITHUB_CLIENT_ID,"client_secret":GITHUB_CLIENT_SECRET,"code":code,"redirect_uri":uri}, timeout=15)
        d = r.json()
        if d.get("access_token"):
            session["gh_token"] = d["access_token"]
            u = requests.get("https://api.github.com/user", headers={"Authorization":f"Bearer {d['access_token']}"}, timeout=15)
            session["gh_user"] = u.json().get("login","") if u.ok else ""
            return redirect("/")
    except Exception as e:
        print(f"[OAuth] Error: {e}")
    return redirect("/?error=login_failed")

@app.route("/api/github/user")
def github_user():
    return jsonify({"ok":bool(session.get("gh_token")),"login":session.get("gh_user","")})

@app.route("/api/github/logout")
def github_logout():
    session.clear(); return redirect("/")

@app.route("/api/github/star", methods=["POST"])
def github_star():
    t = session.get("gh_token")
    if not t: return jsonify({"error":"login"}),401
    fn = request.get_json().get("repo","")
    r = requests.put(f"https://api.github.com/user/starred/{fn}", headers={"Authorization":f"Bearer {t}","Content-Length":"0"}, timeout=10)
    return jsonify({"ok":r.status_code==204})

@app.route("/api/github/unstar", methods=["POST"])
def github_unstar():
    t = session.get("gh_token")
    if not t: return jsonify({"error":"login"}),401
    fn = request.get_json().get("repo","")
    r = requests.delete(f"https://api.github.com/user/starred/{fn}", headers={"Authorization":f"Bearer {t}"}, timeout=10)
    return jsonify({"ok":r.status_code==204})

# ── README 缓存 ──
@app.route("/api/repo/readme/<path:full_name>")
def repo_readme(full_name):
    """获取仓库 README 并提取摘要"""
    now = time.time()
    cached = readme_cache.get(full_name)
    if cached and (now - cached["time"]) < README_CACHE_DURATION:
        return jsonify(cached["data"])

    # 从 gitHub_fetcher 读 token 和代理
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    headers = {
        "Accept": "application/vnd.github.v3.raw+json",
        "User-Agent": "GitHubStarsAnalyzer/1.0"
    }
    if token:
        headers["Authorization"] = f"token {token}"

    # 尝试获取 README
    readme_text = ""
    for ext in ["", ".md", ".rst", ".txt"]:
        url = f"https://api.github.com/repos/{full_name}/readme{ext}"
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                readme_text = resp.text
                break
        except:
            continue

    if not readme_text:
        readme_cache[full_name] = {"data": {"error": "README not found"}, "time": now}
        return jsonify({"error": "README not found"}), 404

    # 改进的 README 解析：提取可读的内容段落
    lines = readme_text.split('\n')
    sections = {}
    current_section = "_intro"
    sections[current_section] = []
    in_code = False

    heading_map = {
        "about": "About", "description": "About", "introduction": "About",
        "overview": "About", "什么是": "About", "简介": "About",
        "features": "Features", "特性": "Features", "功能": "Features",
        "quick start": "Quick Start", "getting started": "Quick Start",
        "installation": "Installation", "安装": "Installation",
        "usage": "Usage", "使用": "Usage"
    }

    for line in lines:
        s = line.strip()
        if s.startswith('```'): in_code = not in_code; continue
        if in_code: continue
        if not s: continue
        if re.match(r'^\[?!\[', s) or re.match(r'^https?://img\.shields\.io', s) or re.match(r'^<img\s', s, re.I): continue
        hm = re.match(r'^(#{1,4})\s+(.+)$', s)
        if hm:
            if hm.group(1).count('#') == 1: continue
            t = hm.group(2).strip().lower()
            cs = None
            for kw, sn in heading_map.items():
                if kw in t: cs = sn; break
            current_section = cs or hm.group(2).strip()
            if current_section not in sections: sections[current_section] = []
            continue
        t = s
        t = re.sub(r'!\[.*?\]\(.*?\)', '', t)
        t = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', t)
        t = re.sub(r'`([^`]+)`', r'\1', t)
        t = re.sub(r'[*_]{1,3}', '', t)
        t = re.sub(r'<[^>]+>', '', t)
        t = re.sub(r'\s+', ' ', t).strip()
        if t and len(t) > 10:
            sections[current_section].append(t)

    parts = []
    seen = set()
    def add(t):
        k = t[:80].lower()
        if k not in seen and len(t) > 15: seen.add(k); parts.append(t)
    for ps in ["About", "Description", "Features"]:
        if ps in sections:
            for p in sections[ps][:5]: add(p)
            break
    for p in sections.get("_intro", [])[:8]: add(p)
    if len(' '.join(parts)) < 300:
        for sn, sc in sections.items():
            if sn not in ("About", "Description", "Features", "_intro"):
                for p in sc[:3]: add(p)
                if len(' '.join(parts)) >= 800: break
    summary = ' '.join(parts)
    if len(summary) > 3000:
        summary = summary[:3000]
        lp = summary.rfind('.')
        if lp > 300: summary = summary[:lp+1]
    if not summary: summary = "该项目暂无详细描述。"

    result = {
        "full_name": full_name,
        "readme_summary": summary[:2000],
        "readme_length": len(readme_text),
        "has_readme": bool(readme_text)
    }
    readme_cache[full_name] = {"data": result, "time": now}
    return jsonify(result)

# ── 路由 ──
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/data")
def get_data():
    with cache_lock:
        if cache:
            return jsonify(cache)
    return jsonify({"status": "loading", "message": "数据加载中..."})

@app.route("/api/repo/<path:full_name>")
def repo_detail(full_name):
    idx = build_repo_index()
    r = idx.get(full_name)
    if r:
        return jsonify({"repo": r, "source": "cache"})
    return jsonify({"error": "Repository not found"}), 404

@app.route("/api/refresh")
def refresh_data():
    t = Thread(target=fetch_latest, daemon=True)
    t.start()
    return jsonify({"status": "started", "message": "正在后台重新抓取数据..."})

@app.route("/api/status")
def status():
    with cache_lock:
        has_data = bool(cache)
        age = int(time.time() - cache_time.get("time", 0)) if cache_time else -1
    return jsonify({
        "has_data": has_data,
        "cache_age_seconds": age,
        "total_repos": cache.get("stats", {}).get("total_repos", 0) if cache else 0,
        "refreshing": _fetch_progress["running"],
        "fetched_count": _fetch_progress["fetched"]
    })

if __name__ == "__main__":
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    port = int(os.environ.get("PORT", 5000))
    print(f"  GitHub Stars Analyzer 启动于 http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
