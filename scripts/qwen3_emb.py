#!/usr/bin/env python3
"""Qwen3-Embedding-0.6B (int8 ONNX) 独立推理器。
fastembed 未收录该模型，故直接用 onnxruntime + tokenizers 跑：
  · decoder-only 架构 → 用最后一个 token 的隐状态做 pooling（官方用法）
  · L2 归一化后余弦相似度即点积
"""
import os
import sys
import numpy as np

D = os.environ.get("QWEN3_EMB_DIR", "/sandbox/workspace/models/qwen3-emb-0.6b")
_sess = None
_tok = None


def _load():
    global _sess, _tok
    if _sess is not None:
        return
    import onnxruntime as ort
    from tokenizers import Tokenizer
    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    _sess = ort.InferenceSession(os.path.join(D, "onnx", "model_int8.onnx"),
                                 sess_options=so, providers=["CPUExecutionProvider"])
    _tok = Tokenizer.from_file(os.path.join(D, "tokenizer.json"))
    _tok.enable_truncation(max_length=512)
    _tok.enable_padding(direction="right", pad_id=0, pad_token="<|endoftext|>")


def embed(texts, batch=16):
    """返回 (N, 1024) L2 归一化向量"""
    _load()
    names = {i.name for i in _sess.get_inputs()}
    out = []
    for s in range(0, len(texts), batch):
        enc = _tok.encode_batch(texts[s:s + batch])
        n = len(enc)
        L = max(len(e.ids) for e in enc)
        ids = np.zeros((n, L), dtype=np.int64)
        mask = np.zeros((n, L), dtype=np.int64)
        for i, e in enumerate(enc):
            k = len(e.ids)
            ids[i, :k] = e.ids
            mask[i, :k] = 1
        feed = {"input_ids": ids, "attention_mask": mask}
        if "position_ids" in names:
            feed["position_ids"] = np.tile(np.arange(L, dtype=np.int64), (n, 1))
        # 该 ONNX 是带 KV-cache 的解码版：空 past（past_len=0）即等价于纯前向
        for nm in names:
            if nm.startswith("past_key_values"):
                feed[nm] = np.zeros((n, 8, 0, 128), dtype=np.float32)
        h = _sess.run(None, feed)[0]
        idx = mask.sum(1) - 1                     # 最后一个真实 token
        v = h[np.arange(n), idx].astype("float32")
        v /= (np.linalg.norm(v, axis=1, keepdims=True) + 1e-12)
        out.append(v)
    return np.vstack(out)


if __name__ == "__main__":
    qs = ["大语言模型", "大規模言語モデル", "large language model",
          "开源软件的安全性", "open source software security", "Künstliche Intelligenz"]
    import time
    t = time.time()
    V = embed(qs)
    print(f"加载+{len(qs)}条: {time.time()-t:.1f}s  维度 {V.shape[1]}")
    S = V @ V.T
    print(f"中LLM vs 日大規模言語モデル: {S[0][1]:.3f}")
    print(f"中LLM vs 英large language model: {S[0][2]:.3f}")
    print(f"中开源安全 vs 英OSS security: {S[3][4]:.3f}")
    print(f"中LLM vs 德KI(不同义，应偏低): {S[0][5]:.3f}")
    print(f"日LLM vs 英LLM: {S[1][2]:.3f}")
