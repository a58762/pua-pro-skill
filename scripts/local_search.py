#!/usr/bin/env python3
"""local_search —— 自己的搜索技能：自建语料库 + 本地索引，不依赖任何搜索 API。

思路来自国外 agent 社区的通行做法：
  · strands agents / openclaw-memory：用 SQLite FTS5 + BM25 做零服务器检索
  · Jean Galea：选定你真正关心的几个源，定时抓取并存储
  · 日文 Zenn 实践：LIKE 慢，FTS5 快几个数量级

做的事：
  1. index  —— 从内置/自定义源抓最新内容，入库（按 URL 去重，可反复跑）
  2. search —— 本地全文检索，BM25 排序（毫秒级，零网络）
  3. stats  —— 看索引规模与源分布

为什么比调 API 强：
  · 无额度、无 402、无 key
  · 搜的是"我选定的源"，质量可控，不用在垃圾里淘
  · 离线可用，检索速度与网络无关

用法：
  python3 local_search.py index                # 增量抓取所有源
  python3 local_search.py index --source hn    # 只抓某个源
  python3 local_search.py search "gemini 4 neon"
  python3 local_search.py search "异步" --limit 10
  python3 local_search.py stats
"""
import argparse, json, os, re, sqlite3, sys, time, urllib.request, urllib.parse
from xml.etree import ElementTree as ET

for _p in ("/opt/toolchain/pylibs",):
    if _p not in sys.path:
        sys.path.insert(0, _p)

DB = "/sandbox/workspace/.pua/u-0/index/search.db"
UA = "pua-pro-skill/1.0 (local index)"

SOURCES = {
    "hn":     ("Hacker News 首页", "api", "https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=30"),
    "qiita":  ("Qiita 最新", "api", "https://qiita.com/api/v2/items?per_page=30"),
    "zenn":   ("Zenn 最新", "rss", "https://zenn.dev/feed"),
    "habr":   ("Habr 最新（俄）", "rss", "https://habr.com/ru/rss/all/all/"),
    "habr_en":("Habr 最新（英）", "rss", "https://habr.com/en/rss/all/all/"),
    # —— 多语种扩充（2026-11-24 实测可达）——
    "gihyo":  ("技術評論社（日）", "rss", "https://gihyo.jp/feed/atom"),
    "golem":  ("Golem（德）", "rss", "https://www.golem.de/rss.php?feed=RSS2.0"),
    "borncity":("Born's Tech（德）", "rss", "https://www.borncity.com/blog/feed/"),
    "nextink":("Next（法）", "rss", "https://next.ink/feed/"),
    "linuxfr":("LinuxFr（法）", "rss", "https://linuxfr.org/news.atom"),
    "hipertextual":("Hipertextual（西）", "rss", "https://hipertextual.com/feed"),
    "tabnews":("TabNews（葡/巴西）", "rss", "https://tabnews.com.br/rss"),
    "thereg": ("The Register（英）", "rss", "https://www.theregister.com/headlines.atom"),
    "lwn":    ("LWN（英）", "rss", "https://lwn.net/headlines/rss"),
    "phoronix":("Phoronix（英）", "rss", "https://www.phoronix.com/rss.php"),
    "osnews": ("OSNews（英）", "rss", "https://www.osnews.com/feed/"),
}

def conn():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB)
    # trigram 分词：对中文、日文、英文都能命中（sqlite >= 3.34）
    c.executescript("""
    CREATE TABLE IF NOT EXISTS docs(
      id INTEGER PRIMARY KEY, source TEXT, title TEXT, url TEXT UNIQUE,
      body TEXT, ts TEXT
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
      title, body, content='docs', content_rowid='id', tokenize='trigram'
    );
    CREATE TRIGGER IF NOT EXISTS docs_ai AFTER INSERT ON docs BEGIN
      INSERT INTO docs_fts(rowid, title, body) VALUES (new.id, new.title, new.body);
    END;
    CREATE TRIGGER IF NOT EXISTS docs_au AFTER UPDATE ON docs BEGIN
      INSERT INTO docs_fts(docs_fts, rowid, title, body) VALUES('delete', old.id, old.title, old.body);
      INSERT INTO docs_fts(rowid, title, body) VALUES (new.id, new.title, new.body);
    END;
    """)
    return c

def get(url, timeout=20, retries=2):
    last = None
    for _ in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            last = e; time.sleep(1)
    raise last

def extract_body(url, timeout=15):
    """用 trafilatura 抓正文（社区评测 F1 最高，Newspaper3k 已淘汰）"""
    try:
        import trafilatura
    except ImportError:
        return ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            html = r.read().decode("utf-8", "ignore")
        return (trafilatura.extract(html) or "")[:8000]
    except Exception:
        return ""

def parse_rss(raw):
    out = []
    try: root = ET.fromstring(raw)
    except ET.ParseError: return out
    ns = "{http://www.w3.org/2005/Atom}"
    items = list(root.iter(f"{ns}entry")) or list(root.iter("item"))
    for it in items:
        t = it.findtext(f"{ns}title") or it.findtext("title") or ""
        l = it.findtext(f"{ns}link") or it.findtext("link") or ""
        if not l:
            e = it.find(f"{ns}link")
            l = e.get("href", "") if e is not None else ""
        body = it.findtext(f"{ns}summary") or it.findtext("description") or ""
        d = it.findtext(f"{ns}published") or it.findtext("pubDate") or ""
        if l and len(out) < 60: out.append({"title": t.strip(), "url": l.strip(),
                          "body": re.sub(r"<[^>]+>", " ", body).strip(), "ts": d.strip()})
    return out

def parse_api(name, raw):
    d = json.loads(raw)
    out = []
    if name == "hn":
        for h in d.get("hits", []):
            out.append({"title": h.get("title") or "", "url": h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
                        "body": (h.get("story_text") or "")[:2000], "ts": h.get("created_at","")})
    elif name == "qiita":
        for it in d:
            out.append({"title": it.get("title",""), "url": it.get("url",""),
                        "body": (it.get("body") or "")[:3000], "ts": it.get("created_at","")})
    return out

def cmd_index(args):
    c = conn(); total_new = 0
    names = [args.source] if args.source else list(SOURCES)
    for name in names:
        if name not in SOURCES:
            print(f"[skip] 未知源 {name}"); continue
        label, kind, url = SOURCES[name]
        try:
            raw = get(url)
            rows = parse_api(name, raw) if kind == "api" else parse_rss(raw)
        except Exception as e:
            print(f"[{name}] 失败: {type(e).__name__}: {e}"); continue
        new = 0
        fetched = 0
        for r in rows:
            if getattr(args, "fetch_body", False) and fetched < args.body_limit:
                row = c.execute("SELECT id, length(body) FROM docs WHERE url=?", (r["url"],)).fetchone()
                if row is None or (row[1] or 0) < 600:      # 无正文或正文过短才去抓
                    body = extract_body(r["url"])
                    if body and len(body) > 300:
                        if row:
                            c.execute("UPDATE docs SET body=? WHERE id=?", (body, row[0]))
                            c.commit()
                        else:
                            r["body"] = body
                        fetched += 1
            try:
                c.execute("INSERT OR IGNORE INTO docs(source,title,url,body,ts) VALUES(?,?,?,?,?)",
                          (name, r["title"][:300], r["url"], r["body"][:4000], r["ts"]))
                if c.total_changes: pass
                new += c.execute("SELECT changes()").fetchone()[0]
            except Exception:
                pass
        c.commit()
        total_new += new
        print(f"[{name}] {label}：抓 {len(rows)} 条，新增 {new} 条")
    print(f"—— 本次新增 {total_new} 条 ——")
    return 0

def cmd_search(args):
    if not os.path.exists(DB):
        print("索引不存在，先跑 index", file=sys.stderr); return 1
    c = conn()
    q = args.query.strip()
    if not q: print("查询为空", file=sys.stderr); return 1
    # FTS5 MATCH：用引号包裹避免语法错误
    # 多词用 AND 组合：整句短语匹配太严，多语种长短语几乎必空
    terms = [w for w in q.split() if w]
    safe = " AND ".join('"' + w.replace('"', '""') + '"' for w in terms) if terms else '""'
    sql = """SELECT d.title, d.url, d.source, d.ts, bm25(docs_fts) AS rank
             FROM docs_fts JOIN docs d ON d.id = docs_fts.rowid
             WHERE docs_fts MATCH ? ORDER BY rank LIMIT ?"""
    try:
        rows = c.execute(sql, (safe, args.limit)).fetchall()
    except sqlite3.OperationalError:
        rows = []
    if not rows:
        # FTS5 无命中或语法错误 → 退化子串匹配（对 2 字中文等短词必要）
        rows = c.execute("""SELECT title,url,source,ts,-1.0 FROM docs
                            WHERE title LIKE ? OR body LIKE ? LIMIT ?""",
                         (f"%{q}%", f"%{q}%", args.limit)).fetchall()
    if not rows:
        print(f"未命中「{q}」。试试更短的词，或先 index 更新语料。"); return 0
    print(f"=== {len(rows)} 条（本地索引 · 零网络） ===")
    for i,(t,u,s,ts,rk) in enumerate(rows,1):
        print(f"{i}. {t[:88]}")
        print(f"   {u}")
        print(f"   [{s}] {ts[:16]}")
    return 0

def cmd_stats(args):
    if not os.path.exists(DB):
        print("索引不存在，先跑 index"); return 0
    c = conn()
    n = c.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
    print(f"文档总数: {n}")
    for s, cnt in c.execute("SELECT source, COUNT(*) FROM docs GROUP BY source ORDER BY 2 DESC"):
        print(f"  {s:10s} {cnt}")
    sz = os.path.getsize(DB)/1024
    print(f"库大小: {sz:.1f} KB  路径: {DB}")
    return 0

def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("index"); i.add_argument("--source")
    i.add_argument("--fetch-body", action="store_true", help="抓正文（慢，但能搜到正文内容）")
    i.add_argument("--body-limit", type=int, default=10, help="每个源最多抓几条正文")
    i.set_defaults(f=cmd_index)
    s = sub.add_parser("search"); s.add_argument("query"); s.add_argument("--limit", type=int, default=10); s.set_defaults(f=cmd_search)
    st = sub.add_parser("stats"); st.set_defaults(f=cmd_stats)
    a = ap.parse_args()
    return a.f(a)

if __name__ == "__main__":
    sys.exit(main())
