#!/usr/bin/env python3
"""单模型 self-retrieval 评测，输出 JSON。
分进程跑不同模型——两个 onnxruntime session 同进程会互相干扰（实测有一次静默被杀）。

用法：
  python3 bench_one.py minilm
  python3 bench_one.py harrier
  python3 bench_one.py octen
固定 seed=42、N_DOC=150、N_QUERY=20，保证三个模型面对完全相同的 query 与语料子集。
"""
import json
import os
import sqlite3
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cmp_embed import load_docs, pick_sentence, recall  # noqa: E402

N_QUERY = int(os.environ.get("N_QUERY", "20"))
N_DOC = int(os.environ.get("N_DOC", "150"))

# Qwen3 系（Harrier/Octen/Qwen3）官方要求 query 加 instruction 前缀，documents 不加。
# 不加前缀会让短 query 对长 doc 的匹配明显退化（实测 Harrier 无前缀 R@1=0.15）。
QI = ("Instruct: Given a web search query, retrieve relevant passages "
      "that answer the query\nQuery: ")
MODELS = {
    "minilm":  {"dim": 384,  "kind": "fastembed", "prompt": ""},
    "harrier": {"dim": 1024, "kind": "onnx", "prompt": QI,
                "dir": "/sandbox/workspace/models/harrier-0.6b", "file": "model_q4.onnx"},
    "octen":   {"dim": 1024, "kind": "onnx", "prompt": QI,
                "dir": "/sandbox/workspace/models/octen-0.6b", "file": "model.int8_full.onnx"},
    "qwen3":   {"dim": 1024, "kind": "onnx", "prompt": QI,
                "dir": "/sandbox/workspace/models/qwen3-emb-0.6b", "file": "model_int8.onnx"},
}


def main():
    name = sys.argv[1]
    cfg = MODELS[name]
    rows = load_docs(N_DOC)
    pos = {r[0]: i for i, r in enumerate(rows)}
    rng = np.random.RandomState(42)
    idx = rng.choice(len(rows), size=min(N_QUERY, len(rows)), replace=False)
    docs = [rows[i] for i in idx]
    gold = [pos[d[0]] for d in docs]
    queries = [pick_sentence(d[2], d[1]) for d in docs]
    texts = [(r[2] or "")[:1200] for r in rows]   # 不含标题：标题做 query，正文做 doc，无泄漏

    if cfg["kind"] == "fastembed":
        from fastembed import TextEmbedding
        m = TextEmbedding(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
                          specific_model_path="/sandbox/workspace/models/multilingual-minilm")
        V = np.array(list(m.embed(texts)))
        Vq = np.array(list(m.embed(queries)))
    else:
        os.environ["QWEN3_EMB_DIR"] = cfg["dir"]
        os.environ["QWEN3_EMB_FILE"] = cfg["file"]
        import qwen3_emb
        V = qwen3_emb.embed(texts, batch=int(os.environ.get("BATCH", "4")))
        pq = [cfg.get("prompt", "") + q for q in queries]
        Vq = qwen3_emb.embed(pq, batch=int(os.environ.get("BATCH", "4")))

    V /= np.linalg.norm(V, axis=1, keepdims=True)
    Vq /= np.linalg.norm(Vq, axis=1, keepdims=True)
    r1, r5 = recall(V, Vq, gold, 1), recall(V, Vq, gold, 5)
    res = {"model": name, "dim": V.shape[1], "corpus": len(rows), "queries": len(queries),
           "R@1": round(r1, 3), "R@5": round(r5, 3)}
    print(json.dumps(res, ensure_ascii=False))
    with open(f"/sandbox/workspace/output/bench_{name}.json", "w") as f:
        json.dump(res, f, ensure_ascii=False)


if __name__ == "__main__":
    main()
