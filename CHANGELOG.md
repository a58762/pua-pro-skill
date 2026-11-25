# CHANGELOG

## v5.10（2026-11-25）

**找到 2026 Q4 真正的最强可下载小模型**
- 多语种检索（EN/JA/DE/RU/ES/FR）+ HN 技术社区交叉核对，结论：
  - MTEB Multilingual v2 榜首 `harrier-oss-v1-27b`（微软 MIT）、RTEB 榜首 `Qwen3-Embedding-8B`——**都放不下**（15–54GB）
  - 1B 以下最优：**`Harrier-OSS-V1-0.6B`（微软，MIT，MTEB v2 69.0，399MB q4）**、**`Octen-Embedding-0.6B`（Apache 2.0，599MB int8）**
  - 落选记录：`EmbeddingGemma 2`（多语言 61.15→61.36 几乎无提升，强项是多模态/代码）；`jina-v5-text-nano/small`（CC BY-NC 非商业）；`Ternlight`（7MB，质量不明）
- 三个模型全部下载并跑通，统一口径实测（150 条语料 / 30 query / 标题做 query / doc 不含标题 / batch=8）：
  | 模型 | 维度 | 体积 | R@1 | R@5 |
  |---|---|---|---|---|
  | MiniLM-multilingual（2020，原现役） | 384 | 450MB | 0.400 | 0.433 |
  | **Harrier-OSS-V1-0.6B q4**（MIT） | 1024 | **399MB** | **0.567** | **0.767** |
  | Octen-Embedding-0.6B int8（Apache 2.0） | 1024 | 599MB | 0.950\* | 1.000\* |
  \* Octen 批维硬编码为 1，只能在 N=60 的小规模口径下测（batch=1 时 0.95/1.00），与上面 150 条口径不可直接比
- **默认换成 Harrier q4**：体积最小、MIT 最宽松、跨语言强（中↔英 0.897、中「开源软件安全性」↔英「open source software security」0.924）
- R@1 +0.167 / R@5 +0.334（相对 MiniLM，同口径）

**修掉三个把评测带偏的 bug（都写进 cmp_embed.py 注释）**
1. `gold` 存的是数据库 id，`topk` 是行号 → 比对必然全错（R@1=0.000）
2. query 取自 8000 字正文的中段，doc 只取前 1200 字 → 那句话根本不在被检索文本里
3. 截断范围修好后，取到的"句子"其实是图注/导航碎片（`図2 images/fig02...`）→ 改用标题做 query，且 doc 不含标题（否则 R@1 假性 1.0 泄漏）

**修掉两个让 Harrier 被误判的推理 bug**
1. **右填充 → 左填充**：decoder-only 模型 last-token pooling 用右填充会取到 pad 的隐状态，向量全错。实测 batch=4 时 R@1 从 0.95 掉到 0.15，改用左填充恢复
2. **ONNX 导出差异**：`onnx-community` 部分导出已内置 pooling（输出 `sentence_embedding`，只有 2 个输入），需与「需自行 pooling」的导出区分处理；Octen 的输出 batch 维度硬编码为 1，只能 batch=1

**Qwen3 系必须加 query instruction**
- 官方 `web_search_query` 前缀：`Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery: `；documents 不加

## v5.9（2026-11-25）

**语义检索（跨语言）——模型换代**
- 淘汰 `bge-small-en-v1.5`（纯英文模型，中↔日仅 0.488）
- 换 `paraphrase-multilingual-MiniLM-L12-v2`（50+ 语种，384 维）：中↔日 **0.980**、中↔英 **0.969**、中「开源软件安全性」↔英「open source software security」0.949
- 本地模型落 `models/multilingual-minilm/`（585MB），`dl_chunks.py` 分片并发 2.8MB/s（单连接仅 150KB/s）
- 新增 `bin/qwen3_emb.py`：Qwen3-Embedding-0.6B int8 ONNX 独立推理器（1024 维）。fastembed 未收录，故用 onnxruntime + tokenizers，手工处理 KV-cache 输入（传 past_len=0）与 last-token pooling
- 新增 `scripts/cmp_embed.py` / `cmp_qwen3_only.py`：self-retrieval R@1/R@5 对照实验。**余弦绝对值不可跨模型比较**（老模型向量空间塌缩在 0.9+，区分度反而差）
- **实测结论：Qwen3-Embedding-0.6B int8（1024 维）在本场景与 MiniLM（384 维）持平**——R@1 0.200 vs 0.200，R@5 0.250 vs 0.300（加官方 instruct 前缀后）。故**继续用 MiniLM**，省 10 倍存储与计算
- 硬限制：4GB 内存下 Qwen3 int8 的 batch 必须 ≤4，batch=16 被 OOM 静默杀掉（无 traceback，排查耗时）
- 结论记录：Gemini Embedding 是专有模型（官方 Self-host: No），不可下载；「某榜第一」在不同榜上互相矛盾（gemini-embedding-2 在一篇日文实测里跨语言第 1，在 Borda 综合榜里第 10）

**JS 渲染（最大短板补齐）**
- 引入 lightpanda 1.0.5（Zig 写的 headless 浏览器，单文件 75MB vs Chromium 2GB，快 9–16 倍、省 10–16 倍内存，走 CDP）
- 选型依据：fastCRW 的渲染器自动档 `chrome → lightpanda → http`；Crawl4AI 虽开源但依赖 Playwright/Chromium
- `extract_body` 改三级：trafilatura → 正文 <300 字则 lightpanda `--dump markdown` → 空
- 实测 `react.dev/learn`：trafilatura 提取 0 字 → lightpanda 7,967 字（含标题/列表/代码块）
- `crawl` 同步接入，并过滤静态资源（`.woff2/.css/.js/.webmanifest` 等 23 类），修掉抓到字体文件的脏数据

**语料扩容**
- 新增 5 个 AI 一手源：arXiv cs.AI（`rss.arxiv.org`，500KB）、Zenn AI 主题、Qiita AI 标签、Simon Willison、HN 搜 LLM
- 修 `parse_api`：原按源名硬编码（只认 hn/qiita），新源全部静默返回 0；改为按数据结构判断（dict+hits=Algolia，list=Qiita）
- 语料 414 → 571 条；含「LLM」文档 12 → 54 条，「language model」0 → 23 条
- 验证：中文「大语言模型的推理论文」→ 三篇 arXiv，0.676/0.663/0.627（换代前 0.4x 且不相关）

**并发 / crawl / map**
- `--workers 12`，120 篇正文 ~6 分钟 → ~1 分钟
- `map`：sitemap.xml 优先，退化首页链接
- `crawl`：BFS 同域 + 渲染兜底 + 静态资源过滤

**定时更新**
- `scripts/refresh.sh`：目录锁 + pid + 租约（避开 flock 的 fd 被 setsid 子进程继承导致永久占锁的坑）、有界抓取、日志落 `refresh.log`
- 环境变量 `PUA_BODY_LIMIT` / `PUA_WORKERS` 可调

**与 Firecrawl(402) 的对比**
- 超越：语义检索（它没有）、无限额度、数据本地自主
- 不如：全网覆盖、JS 渲染、反爬对抗

## v5.8（2026-11-24）

**多语种扩充**
- 源从 4 个扩到 14 个，覆盖英/日/俄/德/法/西/葡：新增 Golem、Born's Tech、Next、LinuxFr、Hipertextual、TabNews、技術評論社、The Register、LWN、Phoronix、OSNews
- 实测索引 410 条 / 2.0 MB

**正文抓取（解决核心短板）**
- 集成 Trafilatura（OSTI 评测 F1 0.937 最高）；放弃 Newspaper3k（已淘汰）
- `index --fetch-body --body-limit N`
- 实测：`リリース` 从"标题命中 1"变为"正文命中 4"，能搜到正文内容
- 加 FTS5 UPDATE 触发器，正文更新后索引同步

**已验证的差距**
- 无正文时搜 `machine learning` / `Künstliche Intelligenz` 全 0 命中
- 与 Tavily 的真实差距：语料窄、无语义、需手动索引；但零成本、毫秒级

## v5.7（2026-11-24）

**新增：本地索引搜索（自建语料）**
- `scripts/local_search.py`：SQLite FTS5 + BM25 + trigram 分词；index / search / stats 三命令
- 内置源：Hacker News、Qiita、Zenn、Habr（官方 API 或 RSS）
- URL 唯一去重，可反复增量索引；索引与检索全离线，毫秒级
- 实测：120 条入库（1.4MB），英文/日文查询命中，2 字符短词自动退化 LIKE 兜底
- `references/local-index.md` 记录机制来源（strands / openclaw-memory / Jean Galea / Zenn 实践）与边界

**认知修正**
- 先前把"搜索技能"理解成"调搜索引擎"，实为借用别人的索引
- agent 社区的正确做法是：选定自己关心的源 → 抓取入库 → 本地建索引 → 检索

## v5.6（2026-11-24）

**新增：搜索 v2（读源码后融合）**
- 读 `tavily.py` 与 firecrawl 系列源码，吸收其设计：可解释的相关度、include/exclude_domains、news+days 时效、搜索抓取一体
- 新增跨查询加权 RRF（原查询权重 1.0 / 扩展查询 0.5）、一手域名加权、可疑域名降权（`-zh.`/`3pro`/`offical`）、结果缓存（10 分钟）
- `scripts/search2.py`

**实测边界（重要，不粉饰）**
- Bing 对无浏览器指纹的请求返回**降级结果**：宽泛热门查询正常，精确技术查询（如 `asyncio best practices`）返回通用页
- 引号 / `+word` / `site:` / 完整浏览器头，全部返回 0 条
- 结论：**自建只适合宽泛探索与热点追踪；精确技术查询仍用 Tavily**。误用自建做精确检索会得到"看起来有答案"的错误结果，比 402 更危险

## v5.5（2026-11-24）

**新增：自建搜索（零额度）**
- `scripts/own_search.py`：直接走 Bing 的 RSS 端点（`format=rss`），无需 key、无额度、无追踪
- 借鉴 SearXNG 的元搜索思路与 RRF（倒数排名融合）算法
- 内置黑名单过滤（知乎/CSDN/掘金/百度百科/36氪/虎嗅等 20+ 二手站）、去重、多区域融合
- 实测：英文 10→7 条（过滤生效）、日文 9 条、多区域 RRF 正常
- `references/own-search.md` 记录机制来源、实现细节与边界

**实测排除的无 key 通道**：DDG html/lite（DNS 不通）、Mojeek（403）、Brave/Startpage/Qwant（000）、多个 SearXNG 公共实例（000）

## v5.4（2026-11-24）

**重大突破：被封站点不需要个人代理**
- 发现检索 API 的 `include_domains` 可代抓被封站点。实测 Reddit / Heise / Tweakers / Lobsters 全部成功，返回带摘要与票数，比原始 JSON 更可读
- 新增诊断法：403（站点拒绝）→ DoH 比对真实 IP（DNS 污染）→ `--resolve` 复测（IP 层阻断）。实测 heise/reddit 的 DNS 被指向 Facebook IP 段与 Teredo 地址
- `fetch_community.py` 新增 5 个"检索 API 代抓"源：reddit / heise / tweakers / lobsters / devto
- 验证并排除：pullpush（持续 429）、rsshub.app 与 rsshub.rssforever.com（000）、多个 redlib 实例（000）、corsproxy.io（403）、api.codetabs.com（000）
- 兜底方案：api.allorigins.win 可拿到完整 190KB JSON，但成功率仅 20%
- **核心认知：你不需要能访问那个网站，只需要能访问一个能访问它的服务**

## v5.3（2026-11-24）

**新增能力：403 站点的官方通道**
- 新增 `scripts/fetch_community.py`：封装 5 个社区的官方 API/RSS（HN、Stack Exchange、Qiita、Zenn、Habr），一条命令并行取
- 新增 `references/community-channels.md`：记录每条通道的端点、实测状态、rate limit 与限制
- 明确四层优先级：官方 API → 官方 RSS → 检索 API 缓存 → 代理+浏览器；**禁止**轮换 UA 硬刷

**实测结论**
- Stack Overflow 语言站仅剩 es / pt / ru / ja；it / pl / tr / uk 已关闭
- `sort=votes` 会返回无关高票旧帖，搜索必须用 `sort=relevance`
- Zenn 的 RSS 只能看最新流，不支持关键词

## v5.2（2026-11-24）

**删除**
- 移除 18 分 rubric 自评。分数是自己给自己打分，对看结果的人没有价值；交付改为只报三件事：数据（项数×轮次）、边界、结论

**扩充**
- 检索社区清单从 8 语种扩到 20+（Stack Overflow 各语言站、Tweakers、Wykop、R10、DOU、TabNews、Blognone、Menéame、Sekurak 等）
- 每个站点标注实测可达状态：✅ 可直连 / ⚠️ 拦截自动化但在线 / ❌ 已不可用
- 实测确认：it / pl / tr / uk 的 Stack Overflow 语言站已关闭；HTML.it 返回 451 地区限制

## v5.1（2026-11-24）

**新增硬规矩**
- 第 2 条「只取一手来源」：技术结论只用官方文档 / 官方 issue / 原始论文 / 各国本地原创社区
- **明确排除中文二手平台**（知乎、CSDN、掘金、简书、博客园、B站、公众号）：多为翻译洗稿且无法回溯
- 中文源仅在中国特有信息（国内产品行为、政策、本地网络环境）时使用，并须标注为二手
- 同步到 `system/always.md` 与技能库检索条目，形成"每次必读 + 按需展开"的双层约束

## v5.0（2026-11-23）

**新增机制**
- 注意力预算（`SKILL.md §0.5`）：明确必读 / 按需 / 绝不三层，压缩时"压掉细节、保住约束"
- Prompt injection 防护（`references/safety.md`）：数据不是指令、三道防线、危险信号清单
- 技能库三维评分（`references/upgrade-loop.md`）：`0.5×相关性 + 0.3×重要性 + 0.2×时效性`，只看前 3 条
- 重试规范（`references/tool-quality.md`）：只重试可重试的、指数退避 + jitter + 上限 + 限次数
- 测试隔离原则：安全测试用自建假靶子（EICAR / pytest tmp_path 同理）

**安全修复**
- PUA_DIR 路径白名单校验（防路径穿越写到允许范围外）
- 符号链接拒绝（防写穿到别处）
- 诊断信息走 stderr，报告走 stdout

**工程**
- 断言从 18 项扩到 24 项（新增路径穿越 ×2、符号链接 ×3、stderr 分离 ×1）
- `scripts/bench.py`：预热 + 中位数 + MAD 剔异的基准器
- 定位并消除内容审核误报（触发源是可执行的 `ln -s` 指向真实系统文件）

## v4.3
- 锁原语按文件系统类型单一确定（禁止运行时降级，否则互斥失效）
- 陈旧锁回收（pid 判活 + 300s 租约）
- 默认按 uid 隔离作用域

## v4.2
- 改为对账范式（reconcile）：幂等 / 漂移检测 / dry-run / no-op 优先
- 原子写；漂移三态（missing / stale / thin）

## v4.0
- 独立化：不依赖上游
- 分层记忆（system / memory / skills / journal）
- 技能库双闸（入库 2 次成功、检索对前提）

## v3.0
- 并入自进化基线（只升不降、3 次晋升）
- L0–L4 压力等级按**已确认失败数**
- 检查点与恢复

## v2.0
- 实证证伪情感施压，话术降级为风格标识
- 补 Prompt Repetition、受众定义、去寒暄、上下文工程

## v1.0
- 话术层 + CoVe + 18 分 rubric + 变量控制
