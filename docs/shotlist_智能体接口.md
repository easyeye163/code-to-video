# shotlist — 分镜结构化编辑层（智能体接口手册）

> 目标读者：**AI 智能体 / 自动化脚本**。shotlist 是对 `projects/<项目>/storyboards/epN.json`
> 的"读-验-改"工具层，全部命令输出 JSON、退出码语义稳定、永不提交任务、不消耗币。
> 提交生成请走 `payload` / `submit` / `batch`。

## 设计原则

1. **机器可读**：stdout 只输出 JSON（人读的提示走 stderr）；`ok` 字段 + 退出码双重表达结果
2. **写前拦截**：`set` 在落盘前做整集全量校验，**带病的修改不落盘**（problems 非空 → 退出码 1，文件保持原样）
3. **指纹驱动**：每段输出 `fingerprint`（内容 sha256 前 16 位）——内容没变指纹不变，智能体据此判断"哪段改了需要重生成"，避免整集重跑烧币
4. **原子写盘**：临时文件 + `replace`，并发读不会读到写一半的文件

## 命令一览

### 1. show — 导出结构化分镜

```bash
python pipeline.py shotlist show projects/example --ep 1            # 整集
python pipeline.py shotlist show projects/example --ep 1 --seg 2    # 单段
python pipeline.py shotlist show projects/example --ep 1 --prompt   # 附每段渲染后的完整提示词
```

返回：`{project, ep, title, segments:[{seg, duration, shots[], fingerprint, ...}]}`。
`--prompt` 时每段多一个 `prompt` 字段（即提交时 node 138 的最终提示词，可直接审查）。

### 2. validate — 严格校验

```bash
python pipeline.py shotlist validate projects/example --ep 1
# 退出码 0 = 通过；1 = 有 problems
```

返回：`{ok, ep, segments, problems[], warnings[]}`。

比 `check` 命令多出的硬校验（problems，阻断）：

| 校验项 | 说明 |
|--------|------|
| seg 编号连续且唯一 | 必须从 1 开始递增，无重复 |
| 镜头时间轴连续闭合 | `[Shot N]` 时段首尾相接（`0s-7s` → `7s-15s`），末尾必须等于段时长 |
| 时长对齐 | 时间轴末尾 ≠ `duration` 时报错（时长节点 132 与提示词时间轴不一致是高频坑） |
| time 格式 | 必须是 `0s-7s` 形式 |
| 必填字段 | summary / soundscape / music / duration / shots |
| 引用解析 | 角色/场景/音色 key 必须存在于 project.json |
| 渲染演练 | 完整跑一遍模板渲染，暴露字段缺失 |

软提醒（warnings，不阻断）：台词预算（约 4.8 字/秒，超预算念不完、不足会幻听）、单段台词句数过密。

### 3. set — 原子化字段编辑

```bash
# 改镜头级字段（time / desc / dialogue）
python pipeline.py shotlist set projects/example --ep 1 --seg 1 --shot 1 \
    --field dialogue --value "新台词内容。"
# 改段级字段（summary / soundscape / music / duration / p1 / p2 / scene / voice 等）
python pipeline.py shotlist set projects/example --ep 1 --seg 1 \
    --field duration --value 20
# 预检不写盘
python pipeline.py shotlist set ... --dry-run
# 清除台词（值传空串）
python pipeline.py shotlist set ... --shot 2 --field dialogue --value ""
```

返回：`{ok, ep, seg, shot, field, old, new, fingerprint, problems[], warnings[]}`。

行为要点：

- **写前全量校验**：任何会导致 problems 的修改直接拒绝（退出码 1），文件不动——智能体可以放心先改后验，不会留下坏状态
- `duration` 自动转整数；`voice_audio` 只接受 true/false
- 值以 `-` 开头时用 `--value=xxx` 形式传参
- `fingerprint` 返回的是**修改后**该段的指纹，与修改前对比即可知道该段是否需要重生成
- `--dry-run` 结果中带 `"dry_run": true`，其余结构一致

## 智能体推荐工作流

```
① show --prompt        读当前分镜 + 渲染结果，理解现状
② set --dry-run        试改，读 problems/warnings 反馈给用户确认
③ set                  确认后落盘（返回新 fingerprint）
④ validate             整集终检（可选，set 已含校验）
⑤ payload --seg N      只为变更段生成 payload（比对 fingerprint 决定哪些段需要）
⑥ submit/batch --seg N 只提交变更段，未变更段复用已有成片
```

**局部重生成的核心**：把每段的 `fingerprint` 存入任务清单；重跑前先 `show` 对比指纹，
指纹未变的段直接跳过提交，实现"改哪跑哪"。

## 字段速查

| 层级 | 字段 | 说明 |
|------|------|------|
| 段级 | `summary` `soundscape` `music` | 段落概要 / 环境音 / 配乐（提示词对应段落） |
| 段级 | `duration` | 段时长（秒），必须与镜头时间轴末尾一致 |
| 段级 | `p1` `p2` `scene` `voice` | 角色/场景/音色 key（须存在于 project.json） |
| 段级 | `style_retention` `drift_clause` `voice_audio` `dialogue_style` | 风格保持句 / 防漂移句 / 是否写音色行 / 台词风格豁免 |
| 镜头级 | `time` | `0s-7s`，全段连续闭合 |
| 镜头级 | `desc` | 镜头画面描述（景别/机位/动作） |
| 镜头级 | `dialogue` | 台词（空串=清除）；受台词预算约束 |

## 错误处理约定

| 退出码 | 含义 |
|--------|------|
| 0 | 成功（validate 的 warnings 不影响退出码） |
| 1 | 校验失败 / 字段或编号不存在 / JSON 解析失败（stderr 给人读的原因） |

智能体解析建议：**先看退出码，再解析 stdout JSON 的 `ok` 与 `problems`**；stderr 仅供日志。
