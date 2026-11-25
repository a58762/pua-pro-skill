#!/usr/bin/env python3
"""embedding 模型对照实验：self-retrieval recall@1/@5。
方法：拿库里带正文的文档，用其标题做 query，看能否把原文自身检索回前 k。
这是 embedding 选型的标准 sanity check——比余弦绝对值可靠，因为不同模型向量尺度不可比。
"""
import os
import sqlite3
import sys
import numpy as np

DB = "/sandbox/workspace/.pua/u-0/index/search.db"
sys.path.insert(0, "/sandbox/workspace/bin")
N_QUERY = int(os.environ.get("N_QUERY", "20"))
N_DOC = int(os.environ.get("N_DOC", "150"))   # 语料抽样上限：全量 398 条 int8 推理需 8 分钟以上


def load_docs(limit=None):
    c = sqlite3.connect(DB)
    rows = c.execute(
        "SELECT id, title, body FROM docs WHERE length(body)>400 ORDER BY id"
    ).fetchall()
    return rows[:limit] if limit else rows


def recall(V_doc, V_q, gold, k):
    S = V_q @ V_doc.T
    topk = np.argsort(-S, axis=1)[:, :k]
    hits = [(gold[i] in topk[i]) for i in range(len(gold))]
    return sum(hits) / len(hits)


def pick_sentence(body, title=""):
    """用标题当 query。
    走过的弯路（都作废）：
      ① 用标题 → 短对长，全 0 命中
      ② 用正文中段句 → 句子来自 8000 字正文却只检索前 1200 字，必然失败
      ③ 修正截断后 → 取到的"句子"其实是图注/导航碎片（"図2 images/fig02..."、"This page explains..."）
    结论：标题是人工精炼的主题描述，与正文是同一内容的不同表述，最接近真实检索场景。
    """
    t = (title or "").strip()
    return t if len(t) >= 8 else (body or "")[:60]


def main():
    rows = load_docs(N_DOC)
    pos = {r[0]: i for i, r in enumerate(rows)}     # doc id → 行号（关键：topk 给的是行号）
    rng = np.random.RandomState(42)
    idx = rng.choice(len(rows), size=min(N_QUERY, len(rows)), replace=False)
    docs = [rows[i] for i in idx]
    gold = [pos[d[0]] for d in docs]
    queries = [pick_sentence(d[2], d[1]) for d in docs]
    DL = int(os.environ.get("DOCLEN", "1200"))
    texts = [(r[2] or "")[:DL] for r in rows]   # 不含标题：标题做 query，正文做 doc，无泄漏
    print(f"语料 {len(rows)} 条，query {len(queries)} 条（正文中段句）")
    print(f"样例 query: {queries[0][:70]}\n")

    # —— A: 现网模型 MiniLM multilingual ——
    from fastembed import TextEmbedding
    m1 = TextEmbedding(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
                       specific_model_path="/sandbox/workspace/models/multilingual-minilm")
    A = np.array(list(m1.embed(texts)))
    Aq = np.array(list(m1.embed(queries)))
    A /= np.linalg.norm(A, axis=1, keepdims=True)
    Aq /= np.linalg.norm(Aq, axis=1, keepdims=True)
    r1, r5 = recall(A, Aq, gold, 1), recall(A, Aq, gold, 5)
    print(f"MiniLM-multilingual   R@1={r1:.3f}  R@5={r5:.3f}", flush=True)

    # —— B: Qwen3-Embedding-0.6B int8 ——
    import qwen3_emb
    B = qwen3_emb.embed(texts, batch=4)   # 4GB 内存下 batch>8 会被 OOM 杀掉
    Bq = qwen3_emb.embed(queries, batch=4)
    r1b, r5b = recall(B, Bq, gold, 1), recall(B, Bq, gold, 5)
    print(f"Qwen3-Embedding-0.6B  R@1={r1b:.3f}  R@5={r5b:.3f}", flush=True)
    print(f"\nΔ R@1 = {r1b-r1:+.3f}   Δ R@5 = {r5b-r5:+.3f}")


if __name__ == "__main__":
    main()
