# 本地索引搜索：自建语料，不借任何搜索 API

## 认知转变

之前我做的是「抓别人的搜索结果」——不管抓 Bing 还是调 Tavily，本质都是**借别人的索引**。

agent 社区真正的做法是另一种：**选定自己关心的源，抓下来存本地，自己建索引。**

> Jean Galea：*"Pick the five sites you actually care about, scrape them on a schedule, store the results."*
> openclaw-memory：*"FTS5 has no external dependencies and ships with every standard SQLite build since 3.9.0"*
> strands agents：BM25 全文检索直接用 SQLite FTS5 做后端
> 日文 Zenn 实践：`LIKE` 慢到不可用，FTS5 快几个数量级

## 为什么这条路更对

| | 借别人的索引 | 自建语料 |
|---|---|---|
| 额度 | 有，用完就 402 | 无 |
| 质量 | 由别人决定（含大量 SEO 垃圾） | 由你选的源决定 |
| 离线 | 不行 | 行 |
| 速度 | 受网络影响 | 毫秒级 |
| 可控性 | 低 | 高（可自定义源） |

## 实现：`scripts/local_search.py`

```
抓取层：内置源（HN / Qiita / Zenn / Habr）× RSS 或官方 API
存储层：SQLite（docs 表，URL 唯一，INSERT OR IGNORE 增量）
索引层：FTS5 虚拟表 + trigram 分词（对中/日/英都能命中）
排序层：BM25（FTS5 内建，rank 越小越相关）
```

### 用法

```bash
python3 scripts/local_search.py index                 # 增量抓取全部源
python3 scripts/local_search.py index --source zenn   # 只抓一个源
python3 scripts/local_search.py search "gemini 4 neon"
python3 scripts/local_search.py search "エージェント"
python3 scripts/local_search.py stats
```

### 实测（2026-11-24）

```
建索引：hn 30 + qiita 30 + zenn 20 + habr 40 = 120 条，库 1.4 MB
搜 "gemini"      → 命中俄文 Habr 的 Gemini 4 Neon 分析
搜 "エージェント"  → 命中日文 Qiita 的 AI agent 教程
搜 "AI"（2 字符）  → trigram 失效，自动退化 LIKE 兜底（噪音略大）
```

## 关键设计点

1. **trigram 分词**：默认的 `unicode61` 对中日文无效（整句当一个 token）。`trigram` 按 3 字符滑窗切分，中/日/英通吃。代价是索引变大。
2. **2 字符查询走 LIKE 兜底**：trigram 需要 ≥3 字符，短词必须退化。
3. **URL 唯一 + INSERT OR IGNORE**：可以反复跑 `index`，不会重复入库。
4. **trigram 对中文需要 ≥3 字**：「人工智能」能命中，「模型」（2 字）只能走 LIKE。

## 边界（诚实说）

- **能力上限 = 语料上限**。没抓的源就搜不到。这是设计取舍，不是缺陷。
- **中文语料目前为零**：内置源是英/日/俄。要搜中文，得自己加中文源（但按一手原则，中文二手站不在推荐范围）。
- **只有标题 + 摘要**，没有全文。要读全文仍需抓页面。
- **需要定期跑 `index`**（可配合 cron 或 GitHub Actions）。不跑就永远是最旧的快照。
- **trigram 索引比普通 FTS5 大 2–3 倍**，语料上万条后要注意库体积。

## 与其它通道的分工

```
已知源的最新动态      → local_search.py（自建索引，毫秒级）
任意主题的全网检索     → own_search.py（零成本，但受 Bing 质量限制）
精确技术问题          → Tavily（付费，语义理解好）
目标站点被封           → fetch_community.py --source X（检索 API 代抓）
```

**顺序**：先查本地（免费且快），没有再用外部。
