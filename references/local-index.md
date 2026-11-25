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
| AI 专源 | arXiv cs.AI（`rss.arxiv.org`）/ Zenn AI 主题 / Qiita AI 标签 / Simon Willison / HN 搜 LLM | ✅ |

不可达：Heise（DNS 污染）、Tweakers（403）、OKKY（403）、Velog（404）、
`huggingface.co/blog/feed.xml`（000 超时）、`news.ycombinator.com/rss`（000，改走 Algolia API）

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

**模型选型（按实证选，不按名气压）**：

| 模型 | 可下载 | 维度 | 体积 | 结论 |
|---|---|---|---|---|
| `BAAI/bge-small-en-v1.5` | ✅ | 384 | 130MB | 纯英文，中↔日仅 0.488，**淘汰** |
| `paraphrase-multilingual-MiniLM-L12-v2` | ✅ | 384 | 450MB | 2020 年的老将，R@1=0.400，**降为回退** |
| **`Harrier-OSS-V1-0.6B` q4 ONNX** | ✅ | 1024 | **399MB** | **现役默认**：微软，MIT，MTEB v2 69.0，R@1=0.567 |
| `Octen-Embedding-0.6B` int8 | ✅ | 1024 | 599MB | Apache 2.0，batch=1 时 0.95/1.00（N=60），但批维硬编码为 1，速度差 |
| `Qwen3-Embedding-0.6B` int8 | ✅ | 1024 | 585MB | 同家族但弱一档，已被 Harrier 取代 |
| `EmbeddingGemma 2` | ✅ | 768 | ~1.5GB | 强在多模态/代码，**多语言 61.15→61.36 几乎无提升**，落选 |
| `jina-embeddings-v5-text-nano/small` | ✅ | 768/1024 | ~1GB | **CC BY-NC 非商业许可**，落选 |
| `Qwen3-Embedding-8B` / `harrier-oss-v1-27b` | ✅ 但 15–54GB | 7168/5376 | — | 榜单第一，本机放不下 |
| Gemini Embedding | ❌ **专有，官方 Self-host: No** | 3072 | — | 只能调 API |

**"某榜第一"不可信**：同一个 gemini-embedding-2，在一篇日文实测里跨语言排名第 1，在另一份 Borda 综合榜里排第 10。榜单构造、任务集、top-k 都会改结论。
**余弦绝对值不能跨模型比较**：老模型的向量空间容易塌缩在 0.9+，看着"相似度高"，实际区分度差。

**唯一可靠比较方式**：self-retrieval recall@k，见 `scripts/bench_one.py`（单模型）/ `scripts/cmp_embed.py`（双模型）。

**本机实测（150 条语料 / 30 query / 标题做 query / doc 不含标题 / batch=8）**：

| 模型 | 维度 | R@1 | R@5 |
|---|---|---|---|
| MiniLM-multilingual（原现役） | 384 | 0.400 | 0.433 |
| **Harrier-OSS-V1-0.6B q4** | 1024 | **0.567** | **0.767** |

**R@1 +0.167、R@5 +0.334**。代价：维度 384→1024（存储 ×2.7），单条推理更慢。

**评测设计必须避开的四个坑**（都踩过）：
1. `gold` 存数据库 id 而 `topk` 是行号 → 比对全错，R@1 恒为 0
2. query 取自长正文中段，doc 只取前 1200 字 → 那句话根本不在被检索文本里
3. 修好截断后，取到的"句子"是图注碎片（`図2 images/fig02...`）→ 改用标题做 query
4. doc 里含标题 → R@1 假性 1.0 泄漏 → doc 必须剔除标题

**Qwen3 系必须加 query instruction**：`Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery: `，documents 不加。

**decoder-only 模型必须左填充**：右填充会让 last-token pooling 取到 pad 的隐状态，向量全错（实测 R@1 从 0.95 掉到 0.15）。

## JS 渲染：抓 React/Vue 空壳站（2026-11-25 落地）

**问题**：现代站点正文由 JS 渲染，`requests` 拿到的 HTML 只有 `<div id="root"></div>`，trafilatura 提取出 0 字。

**社区怎么解**（多语种核对）：
- 德/俄/英三个语种的检索结果指向同一结论：**纯 HTTP 客户端看不到 JS 内容，必须渲染**。
- 商用方案是 API 代渲染（Firecrawl、olostep、browserless），要钱。
- 开源自托管两条路：**Crawl4AI**（Apache 2.0，但依赖 Playwright/Chromium ~2GB）、**fastCRW**（Rust 单二进制，渲染器自动档 `chrome → lightpanda → http`）。
- 关键发现是 **lightpanda**：Zig 从零写的 headless 浏览器，**75MB（Chromium 约 2GB）、快 9–16 倍、省 10–16 倍内存**，走 CDP 协议。

**落地**：`bin/lightpanda`（1.0.5）+ 三级抓取
```
trafilatura（HTTP，F1 0.937，最快）
   ↓ 正文 < 300 字
lightpanda fetch --dump markdown（真渲染）
   ↓ 仍失败
空
```
绝大多数站第一级就够，只有 React/Vue 空壳站才进第二级，不会为了少数站拖慢整体。

**实测**：`https://react.dev/learn` → 7,967 字正文（含标题/列表/代码块）；trafilatura 对同一页只能拿到 0 字。

**另一条零成本路**：SSR 框架会把数据序列化进 HTML（`__NEXT_DATA__`、`window.__INITIAL_STATE__`、`__APOLLO_STATE__`、Nuxt payload），直接从 HTML 里抠 JSON 就能拿到内容，不需要渲染。这条路对本仓库的「只取正文」目标收益有限，但可用于结构化数据抽取。

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
bash scripts/refresh.sh          # 抓源 + 补正文 + 生成向量；目录锁防叠跑，日志 refresh.log
# cron: 17 7 * * * bash /path/to/scripts/refresh.sh     （分钟数用非整点，避开高峰）
```
环境变量：`PUA_BODY_LIMIT`（本次补抓正文条数，默认 10）、`PUA_WORKERS`（并发，默认 12）。
**注意**：`--fetch-body` 走真实网络，20+ 源全跑完需要数分钟，cron 里建议放后台或直接由 cron 承担。

## 与 Firecrawl 的对比（402 的那个）

| 能力 | Firecrawl | local_search |
|---|---|---|
| search | ✅ 额度受限 | ✅ 本地 BM25+向量，无限 |
| scrape（单页正文） | ✅ | ✅ Trafilatura |
| crawl（整站） | ✅ 额度受限 | ✅ 无限制（自己控速） |
| map（列 URL） | ✅ | ✅ sitemap/首页 |
| 语义检索 | ❌ 无 | ✅ 跨语言 |
| JS 渲染 | ✅ 云端浏览器集群 | ✅ lightpanda（75MB 本地，无额度） |
| 成本 | 402 后停摆 | **0** |
| 数据归属 | 在对方服务器 | **本地 SQLite，自己拥有** |

**超越点**：语义检索（Firecrawl 没有）、无限额度、数据自主、JS 渲染不消耗外部额度。
**仍不如它**：全网覆盖与代理池（它有自建抓取基础设施）、强反爬站点（Cloudflare 挑战页等）、SERP 级搜索广度。

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
