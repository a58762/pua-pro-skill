#!/usr/bin/env python3
"""社区检索器：走官方 API / RSS，不伪造 UA、不轮换代理。

设计依据：
  - 日文社区共识：站点提供 API 时应优先用 API
  - 英文实践：先试纯 HTTP，浏览器只作最后手段
  - 德文排障：403 分三层（UA/头 → 指纹 → IP），硬绕不稳定且不合规

用法：
  python3 fetch_community.py --list
  python3 fetch_community.py --source hn --query "gemini 4"
  python3 fetch_community.py --source se --query "gemini" --site stackoverflow
  python3 fetch_community.py --source zenn [--limit 5]
  python3 fetch_community.py --source qiita --query "gemini"
  python3 fetch_community.py --source habr [--lang ru]
  python3 fetch_community.py --source all --query "gemini"
"""
import argparse, json, sys, urllib.request, urllib.parse
from xml.etree import ElementTree as ET

UA = "pua-pro-skill/1.0 (+community-fetch)"   # 诚实标识，不伪装浏览器
TIMEOUT = 20
LIMIT = 5

def get(url, retries=1):
    last = None
    for _ in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read()
        except Exception as e:
            last = e
    raise last

def get_json(url):
    return json.loads(get(url))

def fetch_hn(q):
    d = get_json(f"https://hn.algolia.com/api/v1/search?query={urllib.parse.quote(q)}&tags=story&hitsPerPage={LIMIT}")
    return [(h.get("title") or "(no title)", h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}", h.get("created_at",""))
            for h in d.get("hits", [])]

def fetch_se(q, site="stackoverflow"):
    d = get_json(f"https://api.stackexchange.com/2.3/search/advanced?order=desc&sort=relevance&q={urllib.parse.quote(q)}&site={site}&pagesize={LIMIT}")
    return [(i.get("title",""), i.get("link",""), "") for i in d.get("items", [])]

def _rss(url, ns="{http://www.w3.org/2005/Atom}"):
    root = ET.fromstring(get(url))
    out = []
    items = root.findall(f"{ns}entry") or root.findall("./channel/item")
    for it in items[:LIMIT]:
        t = it.findtext(f"{ns}title") or it.findtext("title") or ""
        l = it.findtext(f"{ns}link") or it.findtext("link") or ""
        if not l:
            e = it.find(f"{ns}link")
            l = e.get("href","") if e is not None else ""
        dt = it.findtext(f"{ns}published") or it.findtext("pubDate") or ""
        out.append((t, l, dt))
    return out

def fetch_zenn():
    return _rss("https://zenn.dev/feed")

def fetch_qiita(q):
    d = get_json(f"https://qiita.com/api/v2/items?per_page={LIMIT}&query={urllib.parse.quote(q)}")
    return [(i.get("title",""), i.get("url",""), i.get("created_at","")) for i in d]

def fetch_habr(lang="ru"):
    for _ in range(3):
        try:
            return _rss(f"https://habr.com/{lang}/rss/all/all/")
        except Exception:
            continue
    raise RuntimeError("habr rss 三次均失败")

SOURCES = {
    "hn":    ("Hacker News (Algolia 官方 API)", True,  fetch_hn),
    "se":    ("Stack Exchange 官方 API",         True,  fetch_se),
    "zenn":  ("Zenn 官方 RSS（仅最新流，不支持关键词）",                   False, fetch_zenn),
    "qiita": ("Qiita 官方 API v2",                True,  fetch_qiita),
    "habr":  ("Habr 官方 RSS",                   False, fetch_habr),
}


# ---------------- 被封站点的通道：检索 API 代抓 ----------------
# 原理：检索 API 的服务器在海外，替我们抓取并把内容返回，无需本地代理
SEARCH_DOMAINS = {
    "reddit":  "reddit.com",
    "heise":   "heise.de",
    "tweakers":"tweakers.net",
    "lobsters":"lobste.rs",
    "devto":   "dev.to",
}

def fetch_via_search(domain_key, q, limit=LIMIT):
    import os
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        raise RuntimeError("未配置 TAVILY_API_KEY")
    dom = SEARCH_DOMAINS[domain_key]
    body = {"api_key": key, "query": q, "include_domains": [dom],
            "max_results": limit, "search_depth": "advanced"}
    req = urllib.request.Request("https://api.tavily.com/search",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read())
    return [(it.get("title","")[:90], it.get("url",""), (it.get("content") or "")[:160].replace("\n"," "))
            for it in d.get("results", [])]

# 已确认直连不通的源（现可用 --source <name> 走检索API），需要代理或检索 API 缓存
UNAVAILABLE = {k: "直连不通 → 用 --source " + k + "（走检索 API 代抓）" for k in
    ["reddit","heise","devto","lobsters","tweakers"]}

def run(name, q=None, site="stackoverflow", limit=LIMIT):
    global LIMIT
    LIMIT = limit
    if name in SEARCH_DOMAINS:
        try:
            rows = fetch_via_search(name, q, limit)
        except Exception as e:
            print(f"[{name}] 失败：{type(e).__name__}: {e}"); return 1
        print(f"=== {name} · 检索API代抓（{SEARCH_DOMAINS[name]}） · {len(rows)} 条 ===")
        for ti, l, sn in rows:
            print(f"- {ti}"); print(f"  {l}"); print(f"  {sn}")
        return 0
    desc, needs_q, fn = SOURCES[name]
    try:
        rows = fn(q) if needs_q else (fn() if name != "habr" else fn(site))
    except Exception as e:
        print(f"[{name}] 失败：{type(e).__name__}: {e}")
        return 1
    print(f"=== {name} · {desc} · {len(rows)} 条 ===")
    for t, l, d in rows:
        print(f"- {t[:78]}")
        print(f"  {l}")
        if d: print(f"  {d}")
    return 0

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--source", default="")
    ap.add_argument("--query", default="")
    ap.add_argument("--site", default="stackoverflow")
    ap.add_argument("--lang", default="ru")
    ap.add_argument("--limit", type=int, default=LIMIT)
    a = ap.parse_args()

    if a.list or not a.source:
        print("可用源（官方通道）：")
        for k,(d,nq,_) in SOURCES.items():
            print(f"  {k:8s} {d}{'  需 --query' if nq else ''}")
        print("\n检索 API 代抓（无需代理）：")
        for k in SEARCH_DOMAINS: print(f"  {k:10s} {SEARCH_DOMAINS[k]}")
        print()
        for k,v in UNAVAILABLE.items():
            print(f"  {k:10s} {v}")
        return 0

    names = list(SOURCES) if a.source == "all" else [a.source]
    rc = 0
    for n in names:
        if n not in SOURCES and n not in SEARCH_DOMAINS:
            print(f"[skip] 未知源 {n}"); rc = 2; continue
        if n == "habr": rc |= run(n, site=a.lang, limit=a.limit)
        elif n in SEARCH_DOMAINS:
            if not a.query:
                print(f"[skip] {n} 需要 --query"); rc = 2
            else:
                rc |= run(n, q=a.query, limit=a.limit)
        elif SOURCES[n][1] and not a.query:
            print(f"[skip] {n} 需要 --query"); rc = 2
        else: rc |= run(n, q=a.query, site=a.site, limit=a.limit)
    return rc

if __name__ == "__main__":
    sys.exit(main())
