#!/usr/bin/env python3
"""dl_chunks.py — 固定小块高并发下载，逐块校验大小、失败多轮重试，最后拼接 + sha256 校验。
用法: dl_chunks.py <url> <out> <sha256|-> <TOTAL> <chunk_MB> <PAR> [rounds]
"""
import os, sys, subprocess, hashlib, math, glob

url, out, sha, TOT, CH_MB, PAR = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6])
ROUNDS = int(sys.argv[7]) if len(sys.argv) > 7 else 6
CH = CH_MB * 1024 * 1024
workdir = out + '.chunks'
os.makedirs(workdir, exist_ok=True)

chunks = []
a = 0; idx = 0
while a < TOT:
    b = min(a + CH - 1, TOT - 1)
    chunks.append((idx, a, b))
    a = b + 1; idx += 1
print('chunks=%d chunk=%dMB' % (len(chunks), CH_MB))

def fname(i): return os.path.join(workdir, 'c%05d' % i)

for rnd in range(1, ROUNDS + 1):
    todo = []
    for i, a, b in chunks:
        f = fname(i)
        need = b - a + 1
        got = os.path.getsize(f) if os.path.exists(f) else 0
        if got != need:
            if os.path.exists(f):
                os.remove(f)
            todo.append((i, a, b))
    if not todo:
        break
    print('round %d: todo=%d' % (rnd, len(todo)))
    from concurrent.futures import ThreadPoolExecutor

    def one(job):
        i, a, b = job
        need = b - a + 1
        for _ in range(3):
            try:
                subprocess.run(['curl', '-sL', '--max-time', '300', '--retry', '2',
                                '-r', '%d-%d' % (a, b), '-o', fname(i), url],
                               check=False, timeout=330)
            except Exception:
                pass
            if os.path.exists(fname(i)) and os.path.getsize(fname(i)) == need:
                return
            if os.path.exists(fname(i)):
                os.remove(fname(i))

    with ThreadPoolExecutor(max_workers=PAR) as ex:
        list(ex.map(one, todo))

missing = [i for i, a, b in chunks
           if (os.path.getsize(fname(i)) if os.path.exists(fname(i)) else 0) != (b - a + 1)]
print('missing_after=%d' % len(missing))

with open(out, 'wb') as w:
    for i, a, b in chunks:
        with open(fname(i), 'rb') as r:
            while True:
                c = r.read(1 << 20)
                if not c: break
                w.write(c)
sz = os.path.getsize(out)
ok = (sz == TOT)
if sha and sha != '-':
    h = hashlib.sha256()
    with open(out, 'rb') as r:
        for c in iter(lambda: r.read(1 << 20), b''):
            h.update(c)
    ok = ok and h.hexdigest() == sha
    print('sha256=%s expect=%s' % (h.hexdigest(), sha))
print('size=%d expect=%d ok=%s' % (sz, TOT, ok))
