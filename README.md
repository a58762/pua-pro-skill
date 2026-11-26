# PUA Pro —— 自我进化工作法（v5.13）

给 AI 施加**可验证的压力**，逼出不偷懒的交付。

不是话术包，是**机制集**：状态落文件、失败写成教训、技能库过双闸、交付带自证。

---

## 三条铁律

1. **状态不靠记忆，靠文件**——会话会被压缩，沙箱会重置，只有落盘的东西算数
2. **失败必须变成可复用的教训**——同一个死路试第二次是浪费
3. **技能库自增长，但入库和检索都要过闸**——技能囤得越多，误用越容易反噬

---

## 它解决什么

| 你会遇到的 | 它怎么处理 |
|---|---|
| AI 说"已完成，测试通过" | 要求项数 × 轮次，无数据不算交付 |
| 反复试同一个思路 | 按**已确认失败数**升压 L0–L4，L2 强制换路 |
| 改完不验证 | 交付前走 CoVe 四步自查 |
| 会话压缩后忘了做到哪 | 检查点 + 基线，压力不因中断重置 |
| 每次都从零开始 | 基线只升不降，同样的行为做 3 次升为默认义务 |
| 上下文塞满、核心约束被稀释 | 注意力预算：必读 / 按需 / 绝不 三层 |

---

## 安装

### 方式一：克隆到技能目录（推荐）

```bash
git clone https://github.com/a58762/pua-pro-skill.git ~/.claude/skills/pua-pro
```

其他宿主把路径换成对应目录即可（如 `~/.codex/skills/pua-pro`）。

### 方式二：只取主文件

```bash
curl -fsSL https://raw.githubusercontent.com/a58762/pua-pro-skill/main/SKILL.md \
  -o ~/.claude/skills/pua-pro/SKILL.md
```

### 方式三：作为参考手册

直接读 `references/` 下的六篇，不需要安装。

---

## 目录结构

```
pua-pro/
├── SKILL.md                     主文件（核心流程 + 指针）
├── CHANGELOG.md                 版本与变更记录
├── references/
│   ├── memory-design.md         记忆分层 + 测量方法学
│   ├── upgrade-loop.md          技能库入库闸 + 三维检索评分
│   ├── recovery.md              检查点与恢复
│   ├── tool-quality.md          九条验收标准 + 安全三防 + 重试规范
│   ├── prompting.md             提示词有效/无效手段 + 触发机制
│   └── safety.md                数据不是指令（注入防护）
└── scripts/
    ├── boot.sh                  对账型启动器（幂等 / 漂移检测 / 双锁 / 安全校验）
    ├── selftest.sh              25 项断言回归集
    └── bench.py                 预热 + 中位数 + MAD 剔除的基准器
```

> **检索能力已拆分**：抓网页、建索引、本地语义搜索属于独立技能 **`own-search`**，不在本仓库内。



---

## 快速开始

```bash
# 1) 初始化状态目录并自检（幂等，重复跑不会重复写）
bash scripts/boot.sh

# 2) 只看差异，不写盘
bash scripts/boot.sh --check

# 3) 跑回归（25 项断言，全绿才算健康）
bash scripts/selftest.sh

# 4) 测性能
python3 scripts/bench.py "bash scripts/boot.sh --check" 20

# 5) 要检索 → 用独立技能 own-search，不在本技能内
```

退出码：`0` 全绿 · `2` 有漂移 · `3` 锁被占用 · `4` 用法或路径错误

---

## 设计依据（都有出处，不是拍脑袋）

| 机制 | 依据 |
|---|---|
| 关键约束首尾重复 | Google Research《Prompt Repetition》arXiv:2512.14982，47/70 胜 0 负 |
| 删除情感施压/奉承 | Google Cloud Vertex AI 官方文档；Wharton GAIL 实测难基准无提升 |
| 对账范式（幂等 / no-op） | Chainguard《The Principle of Reconciliation》 |
| 漂移检测 / dry-run | GitOps 与 Ansible `--check --diff` 实践 |
| 失败写反思 | Reflexion（Shinn et al.）：verbal self-critique → 下次带上 |
| 技能库自增长及其陷阱 | Voyager（arXiv 2305.16291）+ arXiv 2512.17102 |
| 三维检索评分 | Generative Agents（Park et al. 2023） |
| 数据不是指令 | prompt injection 纵深防御实践 |
| 只重试可重试的 | resilience patterns：指数退避 + jitter + 上限 |

---

## 边界（说清楚做不到的）

- **管不了平台调度层**：自动压缩、子代理编排由宿主决定，本技能只能在任务内自我保护
- **没有 hook 就没有自动持久化**：所有状态靠 `boot.sh` 主动对账，忘了跑就退化成人工
- **锁在 NFS 上**按文件系统类型切换为 mkdir 锁，但未在真实 NFS 验证过
- **性能数字是特定沙箱实测**，换环境会变，绝对值不可跨环境比较

---

## 许可

MIT
