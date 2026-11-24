#!/usr/bin/env python3
"""own_search —— 自建搜索：不依赖任何付费 API 额度。

机制来源（参考国外开源做法）：
  · SearXNG 的元搜索思路：不自己建索引，聚合上游引擎结果
  · 它的排序用 RRF（Reciprocal Rank Fusion）：score = Σ 1/(k + rank_i)
  · 抓取层优先用「引擎自带的机器可读输出」（Bing 的 format=rss），比解析 HTML 稳

本脚本做的事：
  1. 向 Bing 的 RSS 端点发查询（无 key、无额度、无追踪）
  2. 解析出 title / link / description / pubDate
  3. 按黑名单过滤二手站（知乎、CSDN、百度百科等）
  4. 去重 + 可选 RRF 融合多区域结果

用法：
  python3 own_search.py --query "gemini 4 neon"
  python3 own_search.py --query "..." --count 20 --mkt ja-JP
  python3 own_search.py --query "..." --keep-cn        # 保留中文站（默认过滤）
  python3 own_search.py --query "..." --json
"""
import argparse, json, re, sys, time, urllib.parse, urllib.request, html
from xml.etree import ElementTree as ET

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
TIMEOUT = 20

# 默认过滤的二手/聚合站（与技术一手原则一致）
BLACKLIST = (
    "zhihu.com", "csdn.net", "juejin.cn", "jianshu.com", "cnblogs.com",
    "51cto.com", "oschina.net", "baike.baidu.com", "baijiahao.baidu.com",
    "cloud.tencent.com", "developer.aliyun.com", "bilibili.com",
    "segmentfault.com", "infoq.cn", "runoob.com",
    "36kr.com", "huxiu.com", "tmtpost.com", "sspai.com", "geekpark.net",
    "woshipm.com", "zhuanlan.zhihu.com",
)

def fetch_rss(query, mkt="en-US", count=10, retries=2):
    url = ("https://www.bing.com/search?" +
           urllib.parse.urlencode({"q": query, "format": "rss", "count": count, "mkt": mkt}))
    last = None
    for _ in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read()
        except Exception as e:
            last = e; time.sleep(1)
    raise last

def parse_rss(raw):
    out = []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return out
    for it in root.iter("item"):
        t = (it.findtext("title") or "").strip()
        l = (it.findtext("link") or "").strip()
        d = (it.findtext("description") or "").strip()
        if l:
            out.append({"title": t, "url": l, "desc": d})
    return out

def domain_of(url):
    m = re.match(r"https?://([^/]+)", url)
    return m.group(1).lower() if m else ""

def blocked(url, extra=()):
    dom = domain_of(url)
    return any(b in dom for b in BLACKLIST) or any(b in dom for b in extra)

def rrf_merge(lists, k=60):
    """Reciprocal Rank Fusion：多组结果按排名融合，抵消单一来源偏差"""
    score, meta = {}, {}
    for lst in lists:
        for rank, item in enumerate(lst):
            key = domain_of(item["url"]) + re.sub(r"\W+", "", item["url"])[-40:]
            score[key] = score.get(key, 0) + 1.0 / (k + rank + 1)
            meta.setdefault(key, item)
    ranked = sorted(score.items(), key=lambda x: -x[1])
    return [meta[k] for k, _ in ranked]

def search(query, mkt="en-US", count=10, keep_cn=False):
    raw = fetch_rss(query, mkt, count)
    rows = parse_rss(raw)
    if not keep_cn:
        rows = [r for r in rows if not blocked(r["url"])]
    # 去重（同域名+同路径）
    seen, uniq = set(), []
    for r in rows:
        key = re.sub(r"[?#].*$", "", r["url"])
        if key in seen: continue
        seen.add(key); uniq.append(r)
    return uniq

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", required=True)
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--mkt", default="en-US")
    ap.add_argument("--multi", action="store_true", help="多区域抓取后 RRF 融合")
    ap.add_argument("--keep-cn", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    try:
        if a.multi:
            regions = ["en-US", "ja-JP", "de-DE", "ru-RU", "ko-KR"]
            lists = []
            for m in regions:
                try:
                    lists.append(search(a.query, m, a.count, a.keep_cn))
                except Exception:
                    pass
            rows = rrf_merge(lists)
        else:
            rows = search(a.query, a.mkt, a.count, a.keep_cn)
    except Exception as e:
        print(f"[error] {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1)); return 0
    print(f"=== {len(rows)} 条（引擎：Bing RSS｜区域：{a.mkt}{'｜多区融合' if a.multi else ''}｜来源：自建，无额度） ===")
    for i, r in enumerate(rows, 1):
        print(f"{i}. {r['title'][:90]}")
        print(f"   {r['url']}")
        if r["desc"]: print(f"   {r['desc'][:180]}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
