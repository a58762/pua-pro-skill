#!/usr/bin/env python3
"""多语种覆盖实测 v2：20 种语言查询，看实际命中哪些国家的内容。
检验「语义检索跨语言」是否真管用，而不只是源表配了几个国家。
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np

DB = "/sandbox/workspace/.pua/u-0/index/search.db"

QUERIES = [
    ("中文", "人工智能和大语言模型", "中国"),
    ("日文", "人工知能と大規模言語モデル", "日本"),
    ("韩文", "인공지능과 대규모 언어 모델", "韩国"),
    ("德文", "Künstliche Intelligenz und große Sprachmodelle", "德国"),
    ("法文", "intelligence artificielle et grands modèles de langage", "法国"),
    ("俄文", "искусственный интеллект и большие языковые модели", "俄罗斯"),
    ("西文", "inteligencia artificial y grandes modelos de lenguaje", "西班牙"),
    ("葡文", "inteligência artificial e grandes modelos de linguagem", "巴西"),
    ("意文", "intelligenza artificiale e grandi modelli linguistici", "意大利"),
    ("荷文", "kunstmatige intelligentie en grote taalmodellen", "荷兰"),
    ("土文", "yapay zeka ve büyük dil modelleri", "土耳其"),
    ("乌克兰文", "штучний інтелект і великі мовні моделі", "乌克兰"),
    ("印尼文", "kecerdasan buatan dan model bahasa besar", "印尼"),
    ("印地文", "कृत्रिम बुद्धिमत्ता और बड़े भाषा मॉडल", "印度"),
    ("阿拉伯文", "الذكاء الاصطناعي ونماذج اللغة الكبيرة", "阿联酋"),
    ("瑞典文", "artificiell intelligens och stora språkmodeller", "瑞典"),
    ("匈牙利文", "mesterséges intelligencia és nagy nyelvi modellek", "匈牙利"),
    ("英文", "artificial intelligence and large language models", "美国"),
]

SRC_COUNTRY = {
    "gihyo": "日本", "qiita": "日本", "qiita_ai": "日本", "zenn": "日本", "zenn_ai": "日本",
    "nextink": "法国", "linuxfr": "法国",
    "habr": "俄罗斯", "habr_en": "俄罗斯",
    "golem": "德国", "borncity": "德国",
    "hipertextual": "西班牙", "tabnews": "巴西",
    "viblo": "韩国", "leganerd": "意大利", "webrazzi": "土耳其", "dou": "乌克兰",
    "bright": "荷兰", "detikinet": "印尼", "aim": "印度", "aitnews": "阿联酋",
    "idgse": "瑞典", "bitport": "匈牙利", "digi": "挪威", "mikrobitti": "芬兰",
    "hn": "美国", "hn_ai": "美国", "phoronix": "美国", "osnews": "美国", "lwn": "美国",
    "thereg": "英国", "simonw": "英国", "arxiv_ai": "国际", "arxiv": "国际",
}


def country_of(src):
    if src.startswith("crawl:"):
        return "网页"
    return SRC_COUNTRY.get(src, "?")


def main():
    from local_search import _model, _query_prefix, EMB_MODEL_TAG
    m = _model()
    QP = _query_prefix()
    print(f"模型: {EMB_MODEL_TAG()}")
    c = sqlite3.connect(DB)
    rows = c.execute("SELECT doc_id, vec, dim FROM vectors").fetchall()
    M = np.zeros((len(rows), rows[0][2]), dtype="float32")
    ids = []
    for i, (d, v, _) in enumerate(rows):
        M[i] = np.frombuffer(v, dtype="float32")
        ids.append(d)
    src_of = dict(c.execute("SELECT id, source FROM docs").fetchall())
    print(f"索引 {len(ids)} 条 / {M.shape[1]} 维\n")

    print(f"{'查询语言':<10} {'Top5 命中地区':<34} {'本国内容'}")
    print("-" * 74)
    tally = {}
    hit_own = 0
    for tag, q, want in QUERIES:
        qv = list(m.embed([QP + q]))[0]
        top = np.argsort(-(M @ qv))[:5]
        got = [country_of(src_of[ids[t]]) for t in top]
        for g in got:
            tally[g] = tally.get(g, 0) + 1
        ok = "✅" if want in got else "—"
        if want in got:
            hit_own += 1
        print(f"{tag:<10} {','.join(got):<34} {ok}")

    print(f"\n命中本国内容: {hit_own}/{len(QUERIES)}")
    print("\n=== 全部命中地区分布（18 × Top5 = 90 个位置）===")
    for k, v in sorted(tally.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
