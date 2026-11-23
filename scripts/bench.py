#!/usr/bin/env python3
"""严谨基准器：warmup + median + MAD 异常剔除 + 每秒次数
依据：hyperfine 的方法论（预热/中位数/MAD 鲁棒异常检测），
      日本社区计数法（短命令用"每秒执行次数"而非"单次秒数"）。
用法：python3 bench.py "<命令>" [次数]
"""
import subprocess, sys, time, statistics

def measure(cmd, n=20, warmup=3):
    for _ in range(warmup):
        subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ts = []
    for _ in range(n):
        s = time.perf_counter()
        subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ts.append((time.perf_counter() - s) * 1000)
    return ts

def report(name, ts):
    med = statistics.median(ts)
    mad = statistics.median([abs(t - med) for t in ts]) or 1e-9
    # MAD 判定：偏离中位数超过 3.5 个 MAD 视为异常（鲁棒于均值/标准差）
    kept = [t for t in ts if abs(t - med) / mad <= 3.5]
    out = len(ts) - len(kept)
    k_med = statistics.median(kept) if kept else med
    print(f"{name}")
    print(f"  n={len(ts)} 剔除异常={out}")
    print(f"  median={med:8.1f}ms  mean={statistics.mean(ts):8.1f}ms  "
          f"min={min(ts):7.1f}  max={max(ts):7.1f}  MAD={mad:6.1f}")
    print(f"  鲁棒中位数={k_med:8.1f}ms   吞吐={1000/k_med:6.1f} 次/秒")
    return k_med

if __name__ == "__main__":
    cmd = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    print(f"命令: {cmd}")
    report("结果", measure(cmd, n))
