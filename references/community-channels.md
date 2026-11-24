# 社区数据通道：403 不等于不可用

## 核心认知

**网站返回 403，通常只说明"它不喜欢裸 curl"，不说明"它不给你数据"。**
绝大多数技术社区都提供官方 API 或 RSS——那条路合规、稳定、不限速到死。

按此优先级找数据：

```
1. 官方 API（最稳）        → 有 token/key 的用它
2. 官方 RSS/Atom          → 只看最新流，不能搜索
3. 检索 API 缓存           → Tavily / Firecrawl（它们已抓过，绕过反爬）
4. 代理 + 浏览器           → 最后手段，成本高、易变
```

**不要做**：轮换 User-Agent 硬刷、伪造指纹、商业代理池轮询。既不合规，也会在站点升级后一夜失效。

## 已验证可用的官方通道（2026-11-24 实测）

| 社区 | 端点 | 状态 | 说明 |
|---|---|---|---|
| **Hacker News** | `https://hn.algolia.com/api/v1/search?query=X&tags=story` | ✅ 200 | 免 key，返回 JSON，支持全文搜索 |
| **Stack Exchange** | `https://api.stackexchange.com/2.3/search/advanced?order=desc&sort=relevance&q=X&site=stackoverflow` | ✅ 200 | 免 key（限 300 次/天），`site=` 可切各语言站 |
| **Zenn** | `https://zenn.dev/feed` | ✅ 200 | RSS，**只有最新流，不支持关键词** |
| **Qiita** | `https://qiita.com/api/v2/items?per_page=5&query=X` | ✅ 200 | 免 key（限 60 次/小时），支持 `query` |
| **Habr** | `https://habr.com/ru/rss/all/all/`（`/en/` 亦有） | ✅ 200（需跟随 301） | RSS，**需 3 次重试**，偶发读超时 |

## 需绕过的源

| 社区 | 现象 | 替代路径 |
|---|---|---|
| Reddit | 直连超时（r/xxx.json、rss、old. 全部 000） | 用 Tavily 取摘要；或起代理 |
| Heise | 直连超时 | 起代理；或 Tavily |
| dev.to | 直连超时 | Tavily |
| Lobsters | 直连超时 | Tavily |
| Tweakers | 403 | Tavily |

## 附带发现

- **Stack Overflow 语言站只剩 es / pt / ru / ja**：it、pl、tr、uk 实测连不上（000）
- **HTML.it 返回 451**（地区法律限制）
- **`sort=votes` 会返回高票无关旧帖**，搜索必须用 `sort=relevance`

## 用法

```bash
# 列出所有源与状态
python3 scripts/fetch_community.py --list

# 单源
python3 scripts/fetch_community.py --source hn --query "gemini 4"
python3 scripts/fetch_community.py --source se --query "gemini" --site stackoverflow
python3 scripts/fetch_community.py --source qiita --query "gemini"
python3 scripts/fetch_community.py --source zenn
python3 scripts/fetch_community.py --source habr --lang en

# 全源并行
python3 scripts/fetch_community.py --source all --query "gemini 4" --limit 3
```

## 边界

- **脚本用诚实 UA**（`pua-pro-skill/1.0`），不伪装浏览器——伪装会被站点的指纹检测识别，且长期看更容易被封
- **rate limit**：StackExchange 300/天、Qiita 60/小时，批量前先估算
- **Zenn 只能看最新**，要按关键词搜只能走 Tavily
- **网络环境相关**：本次实测在国内网络下，Reddit/Heise/dev.to/Lobsters 直连不通；换环境（代理或海外机器）结论会变
- **站点会变**：任何端点都可能被改，脚本失败时先看错误类型（超时 vs 403 vs 404），再决定是重试、换源还是换通道
