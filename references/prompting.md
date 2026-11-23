# 提示词手段（按实证校准）

## 有效（用）

### 1. 重复关键约束
最重要的 1–2 条约束（格式、禁止项、验收标准）在提示词**开头和结尾各写一次**。
依据：Google Research《Prompt Repetition Improves Non-Reasoning LLMs》arXiv:2512.14982，47/70 测试胜、0 负，某难题 21.33% → 97.33%。

### 2. 受众定义
开头写明"给谁看、他关心什么、看不懂什么"。这一句会自动校准术语密度、详略、举例方式（MBZUAI 26 项原则研究称"audience definition magic"）。

### 3. 去寒暄
删掉"请""谢谢""麻烦""辛苦了"。Google Cloud 官方把奉承列入应移除项；日文实测报酬与客套会稀释指令清晰度。

### 4. 上下文工程 > 措辞打磨
纠结"这句话怎么说更好"时，说明该补三样：
- **资料**：相关文档/日志/数据直接给它
- **工具**：能用命令验证的就让它跑，而不是"回忆"
- **前序状态**：之前试过什么、失败在哪、已排除了什么

### 5. 用指令，不要用信息
Phil Schmid 的 agent skill 评测实践：**Models follow instructions, not information**。
- ❌ "这个技能用于处理文件冲突的情况"
- ✅ "冲突时先备份再覆盖，备份命名 `.bak.<时间戳>`"

## 无效（别用，省 token）

| 做法 | 证据 |
|---|---|
| 情感施压、威胁、失望表达 | Google Cloud Vertex AI 官方文档：`Remove prompt language that uses emotional appeals, flattery, or artificial pressure.`；Wharton GAIL 实测难基准无显著提升 |
| 给钱/许诺奖励（非创意任务） | 日文 Qiita 六种说话方式实测：报酬稀释指令清晰度 |
| 奉承（"你是最棒的工程师"） | 同上，官方列入应移除项 |

**例外**：发散型任务（起名、金句、头脑风暴、文案）加一句"多给 5 个方向，不必求稳"确有正作用。

## 触发机制（skill description）

Phil Schmid 的第一条：**name 和 description 就是触发机制**。
- 描述模糊 → 该用的时候不触发，不该用的时候乱触发
- 必须写**具体触发词**（"又错了""证据呢""验收"），而不只是抽象场景
- 同时写**不该触发的场景**（"不用于平静的首次简单请求"），防止误触发
