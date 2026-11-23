# CHANGELOG

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
