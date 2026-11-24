# 自建搜索：不依赖任何额度

## 为什么要有这个

Tavily / Exa / Firecrawl 都是「租」来的检索能力：额度用完就停、账单来了就 402。
真正属于自己的检索，需要自己掌握三层：

```
抓取层 → 拿到原始结果
解析层 → 变成结构化数据（标题/链接/摘要）
排序层 → 去重、过滤、融合排序
```

## 机制来源（国外开源做法）

| 方案 | 做法 | 我们借鉴什么 |
|---|---|---|
| **SearXNG**（47k★） | 元搜索：不建索引，聚合上游引擎 | 不自己爬全网，只聚合 |
| SearXNG 的排序 | **RRF（Reciprocal Rank Fusion）**：`score = Σ 1/(k + rank_i)` | 多来源融合排序，抵消单源偏差 |
| 抓取选型实践（英/日/德社区共识） | 优先引擎自带的机器可读输出，其次 HTML，最后浏览器 | **用 RSS 端点而非解析 HTML** |

## 实现：`scripts/own_search.py`

### 核心发现：Bing 支持 RSS 输出

```
https://www.bing.com/search?q=<query>&format=rss&count=10&mkt=en-US
```

返回标准 RSS，每条含 **title / link / description / pubDate**——

- 无 API key
- 无额度
- 无追踪
- 结构比 HTML 干净，不用写脆弱的正则

### 用法

```bash
python3 scripts/own_search.py --query "gemini 4 neon"
python3 scripts/own_search.py --query "コーヒー 淹れ方" --mkt ja-JP
python3 scripts/own_search.py --query "..." --count 20 --json
python3 scripts/own_search.py --query "..." --multi      # 多区域 + RRF 融合
python3 scripts/own_search.py --query "..." --keep-cn    # 不过滤中文站
```

### 内置三层处理

1. **黑名单过滤**（默认开启）：知乎、CSDN、掘金、简书、博客园、51CTO、开源中国、百度百科、36氪、虎嗅、钛媒体、少数派、极客公园、人人都是产品经理等
2. **去重**：按「域名 + 路径」去重，忽略 query/fragment
3. **RRF 融合**（`--multi`）：多区域结果按倒数排名融合

## 实测（2026-11-24）

| 测试 | 结果 |
|---|---|
| `gemini 4 neon` | 10 条原始 → 过滤后 **7 条**，无二手站泄漏 |
| `コーヒー 淹れ方 おすすめ` + ja-JP | **9 条** |
| 同上 + en-US | 9 条（说明技术/生活类内容跨区域差异小） |
| `--multi` 五区域融合 | 正常返回，但各区域结果高度重叠 |

## 边界（诚实说）

- **目前只有 Bing 一个可用引擎**。DDG（html/lite）DNS 不通、Mojeek 403、Brave/Startpage/Qwant 000、various searx 实例 000。所以 RRF 融合**暂时发挥不了多引擎优势**，只在多区域间起作用。
- **质量受限于 Bing 的索引**。搜日文生活类内容时，前排常是维基词典、翻译站，而非本地原创博客。
- **RSS 只给 10 条左右**，深度检索需要换关键词多次查，或用 `--count` 试探上限。
- **Bing 可能改 RSS 端点**。一旦失效，退路是解析 HTML（`b_algo` 块，已实测可行）或用检索 API 兜底。
- **没有正文抓取**。要读全文仍需请求目标页，而目标页可能反爬——这时用 `fetch_community.py` 的官方通道或检索 API。

## 与检索 API 的分工

| 场景 | 用什么 |
|---|---|
| 日常检索、关键词探索 | **own_search.py（零成本）** |
| 需要高质量摘要 / 语义检索 | Tavily（有额度时） |
| 目标站点被封 | `fetch_community.py --source <site>`（检索 API 代抓） |
| 已知站点的官方数据 | `fetch_community.py --source hn/se/qiita/...` |

**原则**：先用零成本的，不够再用付费的。这样额度只在真正需要时才消耗。
