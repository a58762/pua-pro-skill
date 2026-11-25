#!/usr/bin/env python3
"""逐源自检：每个源抽 2 条，用标题做 query，看能否检索回自己（rank<=5 视为该源可用）。
这才是「源是否真的生效」的正确检验——比统计文章数可靠。
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np

DB = "/sandbox/workspace/.pua/u-0/index/search.db"


def main():
    import qwen3_emb
    from local_search import QI, HARRIER_DIR
    os.environ["QWEN3_EMB_DIR"] = HARRIER_DIR
    os.environ["QWEN3_EMB_FILE"] = "model_q4.onnx"
    c = sqlite3.connect(DB)
    rows = c.execute("SELECT doc_id, vec, dim FROM vectors").fetchall()
    M = np.zeros((len(rows), rows[0][2]), dtype="float32")
    ids = []
    for i, (d, v, _) in enumerate(rows):
        M[i] = np.frombuffer(v, dtype="float32")
        ids.append(d)
    id2row = {d: i for i, d in enumerate(ids)}

    srcs = [r[0] for r in c.execute(
        "SELECT source, COUNT(*) c FROM docs GROUP BY source ORDER BY c DESC").fetchall()]
    print(f"{'源':<16} {'条数':>5} {'被测':>4} {'@1':>4} {'@5':>4}  样例标题")
    print("-" * 92)
    good = 0
    for s in srcs:
        docs = c.execute(
            "SELECT id,title FROM docs WHERE source=? AND length(title)>6 LIMIT 2", (s,)).fetchall()
        if not docs:
            continue
        n = c.execute("SELECT COUNT(*) FROM docs WHERE source=?", (s,)).fetchone()[0]
        r1 = r5 = 0
        for did, title in docs:
            qv = qwen3_emb.embed([QI + title], batch=1)[0]
            order = np.argsort(-(M @ qv))
            gold = id2row[did]
            rank = int(np.where(order == gold)[0][0]) + 1
            r1 += rank == 1
            r5 += rank <= 5
        ok = "OK" if r5 == len(docs) else ("~" if r5 else "XX")
        if r5 == len(docs):
            good += 1
        print(f"{s:<16} {n:>5} {len(docs):>4} {r1:>4} {r5:>4}  {ok} {docs[0][1][:34]}")
    print(f"\n完全可用源: {good}/{len(srcs)}")


if __name__ == "__main__":
    main()
