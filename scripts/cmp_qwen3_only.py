#!/usr/bin/env python3
"""只算 Qwen3 的 self-retrieval recall（与 MiniLM 分进程跑，避免两个 onnxruntime session 互相干扰）"""
import os
import sqlite3
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cmp_embed import load_docs, pick_sentence, recall  # noqa: E402

N_QUERY = int(os.environ.get("N_QUERY", "20"))
N_DOC = int(os.environ.get("N_DOC", "150"))

rows = load_docs(N_DOC)
pos = {r[0]: i for i, r in enumerate(rows)}
rng = np.random.RandomState(42)
idx = rng.choice(len(rows), size=min(N_QUERY, len(rows)), replace=False)
docs = [rows[i] for i in idx]
gold = [pos[d[0]] for d in docs]
queries = [pick_sentence(d[2]) for d in docs]
texts = [(r[1] or "") + " " + (r[2] or "")[:1200] for r in rows]
print(f"语料 {len(rows)} 条 / query {len(queries)} 条", flush=True)

import qwen3_emb  # noqa: E402
B = qwen3_emb.embed(texts, batch=4)
print(f"文档向量 {B.shape} 完成", flush=True)
INSTR = ("Instruct: Given a web search query, retrieve relevant passages "
         "that answer the query\nQuery: ")
Bq = qwen3_emb.embed([INSTR + q for q in queries], batch=4)   # Qwen3 官方要求 query 加 instruct
r1, r5 = recall(B, Bq, gold, 1), recall(B, Bq, gold, 5)
print(f"Qwen3-Embedding-0.6B(+instruct)  R@1={r1:.3f}  R@5={r5:.3f}", flush=True)
print("对照（MiniLM 同设置）: R@1=0.200  R@5=0.300")
print(f"Δ R@1 = {r1-0.200:+.3f}   Δ R@5 = {r5-0.300:+.3f}")
