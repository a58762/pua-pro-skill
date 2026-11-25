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


## 多语种源（2026-11-24 实测可达）

| 语种 | 源 | 状态 |
|---|---|---|
| 英 | Hacker News(API) / The Register / LWN / Phoronix / OSNews | ✅ |
| 日 | Qiita(API) / Zenn(RSS) / 技術評論社(RSS) | ✅ |
| 俄 | Habr（ru / en 双通道） | ✅ |
| 德 | Golem / Born's Tech | ✅ |
| 法 | Next / LinuxFr | ✅ |
| 西 | Hipertextual | ✅ |
| 葡(巴西) | TabNews | ✅ |

不可达：Heise（DNS 污染）、Tweakers（403）、OKKY（403）、Velog（404）

## 正文抓取：解决"搜不到正文里的词"

**问题**：RSS 只给标题 + 摘要。实测搜 `machine learning`、`Künstliche Intelligenz` 全部 0 命中——因为这些词只出现在正文里。

**解法**（社区评测结论）：用 **Trafilatura** 抽正文。
- OSTI 论文评测：Trafilatura F1 **0.937** 最高，Readability / Newspaper3k 次之
- **Newspaper3k 已被淘汰**（维护停滞、依赖过时、现代站点频繁失败）
- 另有 FiveFilters Full-Text RSS 托管服务（把部分 feed 转全文）

用法：
```bash
python3 scripts/local_search.py index --fetch-body --body-limit 6
```

实测：Zenn 单篇 HTML 122KB → 正文 8440 字；Qiita 282KB → 12657 字。
抓完后 `リリース` 从"标题命中 1"变成"正文命中 4"，能搜到真正的内容了。

**代价**：每篇 1–3 秒，全源抓一遍很慢。所以 `--body-limit` 默认 10，建议按需对重点源抓。

## 与 Tavily 的真实差距（不粉饰）

| 维度 | local_search | Tavily |
|---|---|---|
| 语料范围 | 我选的 14 个源 / 410 条 | 全网 |
| 正文 | 需显式 `--fetch-body` | 默认有 |
| 时效 | 手动 index，可能滞后 | 实时 |
| 速度 | 毫秒 | 秒级 |
| 成本 | 0 | 付费 |
| 语义理解 | 无（纯词匹配） | 有 |

**结论**：local_search 是"**我关心的源的快速检索**"，不是"全网搜索"。它替代不了 Tavily，但能把"反复查同样几个源"这件事的成本降到零。

**正确的组合**：
```
日常追我关心的源 → local_search（免费、毫秒）
碰到了不认识的领域 → Tavily（付费、懂语义）
```


## 语义检索：跨语言找内容（2026-11-25 落地）

**解决什么**：词面匹配救不了同义与跨语言——搜「大语言模型」找不到只写了「LLM」的文章。

**方案**：fastembed + `BAAI/bge-small-en-v1.5`（384 维）
- 模型下载走 `HF_ENDPOINT=https://hf-mirror.com`（HuggingFace 直连不通）
- 向量存 SQLite BLOB，余弦相似度用 numpy 算（400 条毫秒级）
- 批量 embed（每批 50 条），一次 411 条约 1 分钟

**三种检索模式**：

| 命令 | 原理 | 适合 |
|---|---|---|
| `search` | FTS5 + BM25 | 关键词明确 |
| `sem` | 纯向量余弦 | 描述性/模糊查询 |
| `hybrid` | BM25 + 向量，RRF 融合 | **默认推荐** |

**实测跨语言能力**：
```
中文查询「大语言模型」→ 命中日文「OpenAI の dots」「ChatGPT の AI エージェント」
英文查询「artificial intelligence model」→ 命中日文「ローカルLLM入門」
```
词面匹配绝对做不到这件事。

## 并发抓取

`--workers 12`（默认 8）。120 篇正文从串行 6 分钟降到约 1 分钟。

## crawl / map：补齐 Firecrawl 的能力

```bash
python3 scripts/local_search.py map https://lwn.net --limit 50    # 列站点 URL（sitemap 优先）
python3 scripts/local_search.py crawl https://lwn.net/Articles/ --limit 3 --depth 1
```

- `map`：先试 `/sitemap.xml`，取不到就解析首页链接
- `crawl`：BFS 抓同域页面，正文用 trafilatura 提取，入库时源标记为 `crawl:<域名>`

## 定时更新

```bash
bash scripts/update_index.sh          # 抓源 + 抓正文 + 生成向量 + 统计
# cron: 0 7 * * * bash /path/to/scripts/update_index.sh
```

## 与 Firecrawl 的对比（402 的那个）

| 能力 | Firecrawl | local_search |
|---|---|---|
| search | ✅ 额度受限 | ✅ 本地 BM25+向量，无限 |
| scrape（单页正文） | ✅ | ✅ Trafilatura |
| crawl（整站） | ✅ 额度受限 | ✅ 无限制（自己控速） |
| map（列 URL） | ✅ | ✅ sitemap/首页 |
| 语义检索 | ❌ 无 | ✅ 跨语言 |
| 成本 | 402 后停摆 | **0** |
| 数据归属 | 在对方服务器 | **本地 SQLite，自己拥有** |

**超越点**：语义检索（Firecrawl 没有）、无限额度、数据自主。
**不如它**：全网覆盖（它有自己的抓取基础设施与代理池）、JS 渲染、反爬对抗。

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
