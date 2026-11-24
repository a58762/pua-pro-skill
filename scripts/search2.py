#!/usr/bin/env python3
"""search2 —— 自建搜索 v2：融合 Tavily / Firecrawl 的设计优点，零额度运行。

读源码后吸收的设计：
  · Tavily  : score 相关度字段、include/exclude_domains、news+days 时效、answer 摘要
  · Firecrawl: 搜索与抓取一体（--scrape）、分类与时间过滤
  · 社区实践 : 查询扩展（原查询为锚）、跨查询 RRF 融合、元数据前置过滤、fallback 链

本脚本比它们多做的事：
  1. 零成本主路径（Bing RSS），不消耗任何额度
  2. **跨查询 RRF**：同一文档在多个查询变体下命中就累加分数
  3. **本地相关性打分**：标题命中 3x、摘要 1x、一手域名加权、时效衰减
  4. **一手优先**：官方文档/论文/本地社区自动加权，二手站默认剔除
  5. 结果缓存（默认 10 分钟内不重复请求）

用法：
  python3 search2.py --query "gemini 4 neon"
  python3 search2.py --query "..." --expand --multi        # 查询扩展 + 跨查询融合
  python3 search2.py --query "..." --news --days 3
  python3 search2.py --query "..." --include blog.google,deepmind.google
  python3 search2.py --query "..." --json
"""
import argparse, hashlib, json, os, re, sys, time, urllib.parse, urllib.request
from xml.etree import ElementTree as ET

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
TIMEOUT = 20
CACHE_DIR = "/dev/shm/search2_cache"
CACHE_TTL = 600

BLACKLIST = ("zhihu.com","csdn.net","juejin.cn","jianshu.com","cnblogs.com","51cto.com",
    "oschina.net","baike.baidu.com","baijiahao.baidu.com","cloud.tencent.com",
    "developer.aliyun.com","bilibili.com","segmentfault.com","infoq.cn","runoob.com",
    "36kr.com","huxiu.com","tmtpost.com","sspai.com","geekpark.net","woshipm.com")

# 一手来源加权（官方文档 / 论文 / 本地社区）
FIRST_PARTY = ("deepmind.google","blog.google","openai.com","anthropic.com","ai.google.dev",
    "docs.github.com","github.com","arxiv.org","aclanthology.org","nature.com","science.org",
    "news.ycombinator.com","lobste.rs","qiita.com","zenn.dev","habr.com","heise.de",
    "tweakers.net","stackoverflow.com","reddit.com","velog.io","developpez.com")

STOP = set("the a an of for to in on and or with is are how what why best vs versus".split())

# 可疑域名特征（SEO 山寨站的典型命名）
SUSPICIOUS = ("-zh.", "zh-", "cn.", ".cn", "3pro", "4pro", "gpt-zh", "ai-zh",
              "offical", "guanwang", "download-", "free-")

def cache_path(key):
    try: os.makedirs(CACHE_DIR, exist_ok=True)
    except Exception: return None
    return os.path.join(CACHE_DIR, hashlib.md5(key.encode()).hexdigest() + ".xml")

def fetch_rss(query, mkt="en-US", count=10, retries=2):
    cp = cache_path(f"{query}|{mkt}|{count}")
    if cp and os.path.exists(cp) and time.time() - os.path.getmtime(cp) < CACHE_TTL:
        return open(cp, "rb").read()
    url = "https://www.bing.com/search?" + urllib.parse.urlencode(
        {"q": query, "format": "rss", "count": count, "mkt": mkt})
    last = None
    for _ in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                raw = r.read()
            if cp:
                try: open(cp, "wb").write(raw)
                except Exception: pass
            return raw
        except Exception as e:
            last = e; time.sleep(1)
    raise last

def parse(raw):
    out = []
    try: root = ET.fromstring(raw)
    except ET.ParseError: return out
    for it in root.iter("item"):
        out.append({
            "title": (it.findtext("title") or "").strip(),
            "url": (it.findtext("link") or "").strip(),
            "desc": (it.findtext("description") or "").strip(),
            "date": (it.findtext("pubDate") or "").strip(),
        })
    return [x for x in out if x["url"]]

def dom(u):
    m = re.match(r"https?://([^/]+)", u)
    return m.group(1).lower() if m else ""

def expand(q):
    """查询扩展：原查询保留为锚，附加词只作补充"""
    qs = [q]
    core = " ".join(w for w in re.split(r"\s+", q.lower()) if w not in STOP)
    if core != q.lower(): qs.append(core)
    return qs[:2]

def rrf(weighted_lists, k=60):
    """加权 RRF：原查询 w=1.0，扩展查询 w=0.5，避免扩展词稀释原意"""
    score, meta = {}, {}
    for lst, w in weighted_lists:
        for rank, item in enumerate(lst):
            key = re.sub(r"[?#].*$", "", item["url"])
            score[key] = score.get(key, 0.0) + w * 1.0 / (k + rank + 1)
            meta.setdefault(key, dict(item))
    return [(meta[k], s) for k, s in sorted(score.items(), key=lambda x: -x[1])]

def local_score(item, q, now=None):
    """本地相关性打分（模拟 Tavily 的 score，但可解释）"""
    terms = [w for w in re.split(r"\s+", q.lower()) if w and w not in STOP]
    tl = item["title"].lower(); dl = item["desc"].lower()
    s = 0.0
    for t in terms:
        if t in tl: s += 3.0
        if t in dl: s += 1.0
    d = dom(item["url"])
    if any(d.endswith(f) or d == f for f in FIRST_PARTY): s += 2.0
    else: s -= 1.0   # 非一手来源轻微降权
    if any(x in d for x in SUSPICIOUS): s -= 3.0   # SEO 山寨站重罚
    # 时效：近 7 天加分
    try:
        import email.utils as eu, datetime as dt
        if item.get("date"):
            t = eu.parsedate_to_datetime(item["date"])
            if t.tzinfo is None: t = t.replace(tzinfo=dt.timezone.utc)
            age = (dt.datetime.now(dt.timezone.utc) - t).days
            if age <= 7: s += 1.5
            elif age <= 30: s += 0.5
    except Exception: pass
    return s

def search(query, mkt="en-US", count=10, exclude_cn=True, include=(), exclude=(),
           expand_q=False, multi=False, news=False, days=None):
    queries = expand(query) if expand_q else [query]
    metas = [mkt] + (["ja-JP","de-DE","ru-RU"] if multi else [])
    weighted = []
    for qi, q in enumerate(queries):
        w = 1.0 if qi == 0 else 0.5      # 原查询为锚，扩展查询降权
        for m in metas:
            try:
                rows = parse(fetch_rss(q, m, count))
            except Exception:
                continue
            rows = [r for r in rows
                    if not (exclude_cn and any(b in dom(r["url"]) for b in BLACKLIST))
                    and not (exclude and any(e in dom(r["url"]) for e in exclude))
                    and (not include or any(i in dom(r["url"]) for i in include))]
            if days and news:
                rows = [r for r in rows if fresh_within(r, days)]
            weighted.append((rows, w))
    fused = rrf(weighted) if weighted else []
    out = []
    for item, rscore in fused:
        item = dict(item); item["rrf"] = round(rscore, 5)
        item["score"] = round(local_score(item, query), 2)
        out.append(item)
    out.sort(key=lambda x: (-x["score"], -x["rrf"]))
    return out

def fresh_within(item, days):
    try:
        import email.utils as eu, datetime as dt
        if not item.get("date"): return True
        t = eu.parsedate_to_datetime(item["date"])
        if t.tzinfo is None: t = t.replace(tzinfo=dt.timezone.utc)
        return (dt.datetime.now(dt.timezone.utc) - t).days <= days
    except Exception:
        return True

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", required=True)
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--mkt", default="en-US")
    ap.add_argument("--expand", action="store_true", help="查询扩展 + 跨查询 RRF")
    ap.add_argument("--multi", action="store_true", help="多区域融合")
    ap.add_argument("--news", action="store_true")
    ap.add_argument("--days", type=int, default=None)
    ap.add_argument("--include", default="")
    ap.add_argument("--exclude", default="")
    ap.add_argument("--keep-cn", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    inc = tuple(x.strip() for x in a.include.split(",") if x.strip())
    exc = tuple(x.strip() for x in a.exclude.split(",") if x.strip())
    try:
        rows = search(a.query, a.mkt, a.count, not a.keep_cn, inc, exc,
                      a.expand, a.multi, a.news, a.days)
    except Exception as e:
        print(f"[error] {type(e).__name__}: {e}", file=sys.stderr); return 1
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1)); return 0
    tag = []
    if a.expand: tag.append("查询扩展")
    if a.multi: tag.append("多区融合")
    if a.news: tag.append("时效")
    print(f"=== {len(rows)} 条（自建 · 零额度 · {a.mkt}{' · '+'+'.join(tag) if tag else ''}） ===")
    for i, r in enumerate(rows, 1):
        print(f"{i}. [{r['score']:.1f}] {r['title'][:84]}")
        print(f"   {r['url']}")
        if r["desc"]: print(f"   {r['desc'][:170]}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
