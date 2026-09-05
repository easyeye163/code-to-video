# code-to-video · AI 短剧制作工作流知识库

> 基于 **MiniMax H3 六段式提示词 + RunningHub API + 火山引擎 Seedance + 飞书多维表格** 的 AI 视频制作体系。
>
> 本仓库为**纯代码 + 知识库**版本：所有媒体资源（图片/音频/视频，180 个文件 / 约 586MB）**不入库**，统一由 **MinIO 对象存储**管理，以 URL 链接形式引用。
> 资源总索引：[resources/minio-manifest.json](resources/minio-manifest.json)

## 与 h3-video-coding 的关系

本仓库源自 [easyeye163/h3-video-coding](https://github.com/easyeye163/h3-video-coding)（媒体完整版），剥离全部媒体资源后的知识库版本：

| 对比项 | h3-video-coding（原仓库） | code-to-video（本仓库） |
|---|---|---|
| 代码 / 脚本 / 数据 / 文档 | ✅ | ✅ 完整保留 |
| 图片 / 音频 / 视频 | 直接入库（约 588MB） | ❌ 不入库，存 MinIO 对象存储 |
| 资源引用方式 | GitHub raw URL / jsDelivr CDN URL | MinIO 对象存储 URL |
| 资源索引 | manifest.json（本地目录扫描） | resources/minio-manifest.json（含对象键与访问链接） |

---

## 🔧 资源管理：MinIO 对象存储（必读）

### 设计原则

1. 仓库只保留代码与知识库，克隆秒级完成，不因二进制资源膨胀
2. 媒体资源上传 MinIO 桶，通过公网 URL 引用——对 RunningHub / Seedance API 传素材、网页看板展示，与原 GitHub raw / CDN 链接**完全等价**
3. `resources/minio-manifest.json` 为唯一资源索引：相对路径、类型、大小、MinIO 对象键、访问链接

### 快速开始

```bash
# 1. 安装依赖（仅 sync/presign/check 需要；scan/url 为标准库实现）
pip install -r scripts/requirements.txt

# 2. 准备配置：复制模板并填入你的 MinIO 地址与密钥
cp scripts/minio_config.example.json scripts/minio_config.json
#    （或使用 MINIO_ENDPOINT / MINIO_ACCESS_KEY / MINIO_SECRET_KEY 等环境变量）

# 3. 扫描资源根目录（即包含 audio/ images/ videos/ 的完整目录），生成资源清单
python scripts/minio_sync.py scan <资源根目录>

# 4. 上传 MinIO 并生成公开访问链接（自动建桶 + 设公开只读策略）
python scripts/minio_sync.py sync <资源根目录>
```

### 资源链接格式

```
{MINIO_PUBLIC_URL}/{bucket}/{prefix}/{资源相对路径}

# 示例
https://minio.example.com:9000/code-to-video/code-to-video/images/songkou_characters/lin_xiaoxi_three_view.png
```

查询任意资源的实际链接：

```bash
python scripts/minio_sync.py url images/songkou_characters/lin_xiaoxi_three_view.png
# 输出：https://minio.example.com:9000/code-to-video/code-to-video/images/...
```

私有桶（未开放匿名读）改用临时签名链接，默认 7 天有效：

```bash
python scripts/minio_sync.py presign --expire-days 7
```

校验桶内对象与清单一致性：

```bash
python scripts/minio_sync.py check
```

### URL 替换约定（重要）

原体系中素材通过 GitHub 公网 URL 传递，迁移 MinIO 后按以下规则替换：

| 原引用方式 | 替换为 |
|---|---|
| `https://raw.githubusercontent.com/easyeye163/h3-video-coding/main/{path}` | `{MINIO_PUBLIC_URL}/{bucket}/{prefix}/{path}` |
| `https://cdn.jsdelivr.net/gh/easyeye163/h3-video-coding@main/{path}` | `{MINIO_PUBLIC_URL}/{bucket}/{prefix}/{path}` |
| 本地相对路径 `./images/...`、`./audio/...`、`./videos/...` | 对应的 MinIO URL（用 `minio_sync.py url` 查询） |

> ⚠️ 仓库内 `scripts/ep*_payload.json`、`scripts/yaolu_demo15_*_payload.json`、看板 HTML 与项目主文档中仍保留旧 raw/CDN 链接，**作为历史制作记录**；新制作任务请统一使用 MinIO 链接。
> 中文路径在 URL 中需编码（`python scripts/minio_sync.py url` 输出的链接已自动编码）。

### 新增资源流程

```
[1] 素材放入本地资源根目录（audio/ images/ videos/ 对应子目录）
        ↓
[2] python scripts/minio_sync.py scan <资源根目录>     # 更新资源清单
        ↓
[3] python scripts/minio_sync.py sync <资源根目录>     # 上传 MinIO + 生成链接
        ↓
[4] git add resources/minio-manifest.json
    git commit -m "resources: 新增素材 xxx"
```

> 与原仓库的 manifest.json 更新流程等价：**不更新清单 = 其他协作者/智能体查不到该资源的链接**。

---

## 🚀 制作流水线：项目抽象 + 自动生成 payload

> 用「项目配置 + 分镜数据 + 提示词模板」自动组装 RunningHub payload，取代手工编写 `scripts/ep*_seg*_payload.json`。

### 项目抽象（projects/<项目名>/）

| 文件 | 作用 |
|---|---|
| `project.json` | 项目配置：引擎参数（AppID/画幅/双角色节点布局）、角色库（形象/三视图/音色/不变量）、场景库（参照图/锚点/仙侠化元素/不变量）、风格 |
| `prompt_template_single.txt` | 6段式模板·单角色+场景 |
| `prompt_template_dual.txt` | 6段式模板·双角色（节点分配由 `engine.dual_layout` 决定） |
| `storyboards/epN.json` | 分集分镜：角色/场景/音色/时长/镜头/台词/声景/配乐 |
| `output/` | 生成的 payload（已 gitignore） |

**三个项目实例**：

| 项目 | 定位 | 关键差异配置 |
|---|---|---|
| `projects/songkou` | 写实真实版 · 嵩口20集文化宣传短剧 | 双角色布局：P2=第二角色/P3=场景；提示词含 Audio 音色行 |
| `projects/yaolu` | 3D动漫版 · 镇妖录12集仙侠 | 双角色布局：P2=场景/P3=第二角色（`scene_at_166`）；场景带"仙侠化元素"；默认无 Audio 行（`voice_audio_default: false`）；角色叙述序 P1→P3→P2 |
| `projects/mv` | 古镇 MV（规划中骨架） | 复用写实资产；分镜待音乐创意确定后编写 |

**分段级覆盖**：分镜中可用 `p1_identity` / `p2_identity` / `p1_retention` / `scene_retention` / `style_retention` / `summary` / `drift_clause` / `voice_audio` 等字段覆盖项目默认——同一段戏用简装造型、某段关闭音频行等需求均可在分镜内表达，不动项目配置。

### 使用

```bash
python pipeline.py check   projects/songkou            # 校验配置/分镜/资产可解析
python pipeline.py payload projects/songkou --ep 7     # 生成整集 payload（不消耗币）
python pipeline.py submit  projects/songkou --ep 7 --seg 2 --wait   # 提交并等待成片
python pipeline.py batch   projects/songkou --ep 7 [--continue-on-error]  # 串行批量生成
python pipeline.py render  projects/songkou --ep 7 --title "第7集 时空对话" [--bgm music.mp3]  # 合成成片
python pipeline.py init-project projects/新剧名        # 新剧脚手架（配置+模板+开工清单）
python pipeline.py asset projects/新剧名 --character 某角色 [--three-view --ref-url URL]  # 素材自动生成
```

- 资产（角色图/场景图/音色）在配置中只写仓库相对路径，由资源清单自动解析为 **MinIO URL**
- 分镜级覆盖：如 `"scene_retention"` 可按段定制不变量（ep7 seg4 的"夕阳金光"即用此实现）
- **并发处理（重要）**：RunningHub 并发上限 1，`batch` 串行执行——提交撞 421 自动等待重试（默认 30s×20 次），一段完成**自动提交下一段**；每段成片自动下载到 `output/`（或 `--save-dir` 指定目录），COS 链接 24h 失效的问题一并解决；状态文件 `output/ep<N>_batch_state.json` 支持中断续跑（已成功且成片在手的段自动跳过）
- **验证结果**：songkou ep7 三段与手工版**逐字一致**（seg1 仅 Shot 分行规范化）；yaolu 5 个技能 demo **5/5 全部逐字一致**（含双角色节点布局对调、仙侠化元素、无音频行等全部项目级差异）

### 成片合成（render）

`pipeline.py render projects/songkou --ep 7 --title "第7集 时空对话" --bgm music.mp3`

- 段视频自动查找：`output/epN_segM.mp4`（batch 产出）→ `source_root` 下的手工成片 `EP{N}段{M}_*.mp4`
- 由分镜 `dialogue` 自动生成 SRT 并烧录字幕（时间轴按段视频**实际时长**偏移，不漂移；含片头时自动加偏移）
- BGM 自动循环混音（音量 22%）、可选 2.5s 黑底片头、统一转码 1152×640/24fps
- 产物：`output/epN_final.mp4`（交付级成片）+ `epN.srt`（外挂字幕备用）

### 成本追踪

batch 每段成功后记录 RunningHub 实际消耗（`consumeCoins`），批次结束输出账单（总币数/均值每段）——B 端报价的成本依据。

### 新剧脚手架（init-project）与素材生产（asset）

```bash
python pipeline.py init-project projects/ancient_town_x --title "XX古镇奇缘" \
    [--layout scene_at_166] [--no-voice-audio] [--source-root F:/path/to/assets]
# → 生成 project.json 骨架 + 通用 6 段式模板 + 分镜 schema + 开工清单（checklist）

python pipeline.py asset projects/ancient_town_x --character heroine        # Z-image 生成角色立绘
python pipeline.py asset projects/ancient_town_x --character heroine \
    --three-view --ref-url <上一步输出的立绘URL>                             # KREA 生成三视图
python pipeline.py asset projects/ancient_town_x --scene old_street         # Z-image 生成场景图
```

asset 产物自动入 MinIO + 资源清单 + 回写 project.json 的 `ref_image`——**"换一个古镇"从此是填空题**：填角色设定 → asset 批产形象 → 写分镜 → batch 出片 → render 成片。

### 新建一个短剧项目

1. 复制 `projects/songkou/` 为 `projects/<新项目>/`
2. 修改 `project.json`：角色库（形象/音色/不变量）、场景库、风格与模板措辞
3. 编写 `storyboards/ep1.json` 分镜
4. `python pipeline.py check projects/<新项目>` 通过后即可生成/提交

---

## 短剧必备工作流（自用）

1、 Z-image text-to-image-文生图（完美支持中文字+超自然）【Agent必备】
工作流地址： `https://www.runninghub.cn/post/2088917231601278978/?inviteCode=oga1ahgc`

2、KREA-2-EDIT-One-image-V2 单图编辑工作流【短剧必备】
工作流地址： `https://www.runninghub.cn/post/2088923554007048194/?inviteCode=oga1ahgc`

3、MiniMax H3稳定加速版（全能参考4步加速版本）
工作流地址： `https://www.runninghub.cn/post/2088836712364601345/?inviteCode=oga1ahgc`

4、声音设计（用于短剧多角色声音一致性）
工作流地址： `https://www.runninghub.cn/post/2090434415913689090/?inviteCode=oga1ahgc`

5、Seedance 视频生成（火山引擎/豆包/即梦）【Agent必备】
脚本： `scripts/seedance_video.py`
文档： `docs/seedance_video_README.md` · `docs/seedance_video_SKILL.md`

> **当用户提到"用豆包生成""用即梦做视频""Seedance"时，必须调用 `scripts/seedance_video.py` 技能。**
> 支持：文生视频、首尾帧图生视频、多图全能参考、参考音频音色克隆、音频同步生成。

---

## 必读文档

**所有项目制作都基于以下工具链。开始任何制作前，必须先阅读技能文档：**

**资源管理（本仓库新增）**：本文件「资源管理」章节
- `scripts/minio_sync.py`：MinIO 上传 / 清单生成 / 链接查询
- `resources/minio-manifest.json`：资源总索引

**RunningHub 工作流**：[docs/长期记忆_节点配置总结.md](docs/长期记忆_节点配置总结.md)
- API 使用说明（提交任务/查询结果/文件上传/并发限制）
- 4 个工作流的节点配置（appId + nodeId + fieldName，已验证正确）
- 6 段式提示词标准模板（MiniMax H3 Full-Reference 格式）
- 场景设计表与分镜提示词模板

**Seedance 视频生成**：[docs/seedance_video_README.md](docs/seedance_video_README.md) · [docs/seedance_video_SKILL.md](docs/seedance_video_SKILL.md)
- 文生视频 / 首尾帧图生视频 / 多图全能参考 / 参考音频音色克隆
- 环境变量 `VOLCENGINE_ARK_API_KEY`
- 当用户提到"豆包""即梦""Seedance"时调用此工具

> 不会调用这些工具 = 无法制作任何内容。所有智能体协作前必读。

---

## 项目简介

本项目是"永泰嵩口古镇 20 集 AI 文化宣传短剧"的制作工程，通过 AI 工作流完成从剧本、分镜、角色定妆、视频生成到成片的全链路自动化。

- **目标平台**：MiniMax H3（镜头语言＝6 段式 Full-Reference 英文提示词）
- **规格**：20 集 × 1 分钟（每集 4 段 × 15 秒）
- **角色**：5 人 ｜ **场景**：8 处 ｜ **镜头**：80 段

## 技术栈

| 层级 | 组件 | 用途 |
|---|---|---|
| 编排 | DeepSeek Harness | 任务分解/并行/追踪 |
| 智能体 | GLM 5V-Turbo | 角色/剧情/镜头/数据同步 |
| 图像 | RunningHub Z-image（文生图）/ KREA-2-EDIT（图生图） | 场景图/角色三视图（人物一致性） |
| 视频 | RunningHub AnimateDiff / MiniMax H3 | 6 段式提示词成片 |
| 视频 | 火山引擎 Seedance（豆包/即梦） | 文生视频/图生视频/参考音频，电影级画质 |
| 音频 | RunningHub 多角色声音一致性 | 角色配音 |
| 数据 | 飞书多维表格 | 5 张表结构化存储 |
| **资源** | **MinIO 对象存储** | **图片/音频/视频统一存储与公网链接** |

## 目录结构与功能约束

| 路径 | 功能 | 约束 / 说明 |
|---|---|---|
| `1、【实施中】嵩口宣传项目.md` | **项目主文档（入口）** | 单一权威源，进度/资产状态/瑕疵/版本记录以此为准 |
| `pipeline.py` | **制作流水线入口** | 分镜+项目配置+提示词模板 → payload 自动生成/提交 |
| `projects/` | **项目抽象层** | 各短剧项目的配置/角色库/场景库/分镜（嵩口为首个实例） |
| `scripts/` | Python / Shell 脚本 | 自动化任务；`minio_sync.py` 负责资源上传与链接管理 |
| `resources/` | **资源总索引** | `minio-manifest.json`：全部媒体资源的对象键与 MinIO 链接 |
| `data/` | JSON 数据 | 结构化制作数据（剧本/分镜/批量创建载荷） |
| `docs/` | 项目文档 | 制作单/提示词模板/工作流配置/对话脚本/长期记忆 |
| `audio/`、`images/`、`videos/` | 本地资源目录 | **已 gitignore，不入库**；内容存 MinIO，索引见 `resources/` |
| `微信公众号文章/` | 营销文章 | 微信推文草稿与实战心得 |
| `知识库素材/` | 文化资料 | 嵩口历史/赶集文化/古建筑等背景资料 |
| `.workbuddy/` | 工作记忆 | **已 gitignore**：含 API 状态/taskId 等敏感信息，不入库 |

## .gitignore 规则

- `.workbuddy/` 全部排除（含敏感信息：API key 记录、taskId、lark-cli 凭据）
- **全部媒体扩展名排除**（mp4/png/flac/mp3/wav 等）：资源一律走 MinIO，不入库
- `scripts/minio_config.json` 排除（MinIO 密钥等敏感配置；模板见 `minio_config.example.json`）

## 协作约定

1. **主文档优先**：所有进度/状态/瑕疵更新先写入 [1、【实施中】嵩口宣传项目.md](./1、【实施中】嵩口宣传项目.md)，它是单一权威源
2. **资源引用**：脚本和文档引用媒体资产时统一使用 MinIO 链接（`python scripts/minio_sync.py url <path>` 查询），不再使用本地路径或 GitHub raw/CDN 链接
3. **RunningHub 注意**：
   - COS 云端链接 24h 失效，成片需及时下载到本地目录，再 `sync` 上传 MinIO
   - GET 查询接口坏（`PARAMS_INVALID`），成片需从[控制台](https://www.runninghub.cn/console/task)手动取回
   - 有并发限制，关键任务串行处理，每次调用后 `sleep(10)`
4. **节点配置**：以 [docs/长期记忆_工作流节点配置.md](./docs/长期记忆_工作流节点配置.md) 为准（已实测验证）
5. **提示词规范**：6 段式 Full-Reference
   - `subject_definitions` / `summary` / `retention_analysis` / `detailed_description` / `overall_soundscape` / `non_diegetic_music`
6. **文件命名约定**：
   - 成片：`嵩口短剧_第N集_标题_vX.mp4`
   - 三视图：`xxx_three_view.png`（如 `lin_xiaoxi_three_view.png`）
   - 音色：`songkou_xxx.flac`
7. **资源清单更新（重要）**：每次新增/删除 audio/images/videos 文件后，必须执行 `scan + sync` 并提交 `resources/minio-manifest.json`，否则协作者查不到资源链接
8. **新分镜制作**：优先在 `projects/<项目>/storyboards/` 编写分镜，用 `pipeline.py payload/submit` 生成与提交；`scripts/ep*_payload.json` 为历史手工版本，仅作对照参考

## 标准制作链路（单集 4 步）

```
[1] 文生图（Z-image）            → 场景图/概念图        本地 images/songkou_epN/ → sync 上传 MinIO
        ↓
[2] 图生图（KREA-2-EDIT）        → 角色三视图/定妆图     本地 images/songkou_characters/ → sync 上传 MinIO
        ↓
[3] 图生视频                     → 成片                 本地 videos/songkou_drama/ → sync 上传 MinIO
        ├─ RunningHub AnimateDiff  （6段式提示词，角色一致性）
        └─ Seedance 豆包/即梦       （文生/首尾帧/参考音频，电影级画质）
        ↓
[4] 音频设计                     → 对白+旁白+配乐        本地 audio/voices/ → sync 上传 MinIO
        ├─ RunningHub 多角色声音一致性
        └─ Seedance 2.0 参考音频音色克隆
```

> 向 API 传素材时，一律使用素材的 MinIO 公开链接。

## RunningHub 工作流速查

| 工作流 | App ID | 关键节点 |
|---|---|---|
| Z-image 文生图 | `2088920592350277634` | `17`=prompt |
| KREA-2-EDIT 图生图 | `2088926295186034689` | `1`=prompt |
| AnimateDiff 单图视频 | `2088844222551121921` | `137`首帧/`138`提示词/`157`音频/`156`角色/`165`Audio/`166`Pic2/`132`时长/`115`比例 |
| 多图像视频生成 | `2088878767828717570` | `137`首帧/`157`音频/`156`角色/`138`提示词 |
| 音频生成 | `2090440149267210242` | `3`声音设计/`5`TTS文本 |

## Seedance 视频生成（豆包/即梦）

> **触发规则**：当用户提到"豆包""即梦""Seedance""火山引擎视频"时，必须使用 `scripts/seedance_video.py`。
> 该工具是 RunningHub AnimateDiff 的增强替代方案，支持更多生成模式且画质更高。

### 快速使用

```bash
# 文生视频
python3 scripts/seedance_video.py generate \
  --prompt "描述文本" --ratio 16:9 --duration 5

# 图生视频（首帧，使用 MinIO 资源链接）
python3 scripts/seedance_video.py generate \
  --first-frame "https://<你的MinIO地址>/<bucket>/code-to-video/images/songkou_characters/lin_xiaoxi_three_view.png" \
  --prompt "让画面动起来" --ratio adaptive --duration 5

# 首尾帧图生视频
python3 scripts/seedance_video.py generate \
  --first-frame "url1" --last-frame "url2" --ratio adaptive

# 多图全能参考（角色+场景）
python3 scripts/seedance_video.py generate \
  --reference-image "角色图MinIO链接" --reference-image "场景图MinIO链接" \
  --prompt "参考图1的角色站在参考图2的场景中" --ratio 16:9

# 参考音频（需 2.0 模型，音色克隆）
python3 scripts/seedance_video.py generate \
  --model doubao-seedance-2-0-260128 \
  --first-frame "url" --reference-audio "音色MinIO链接" \
  --prompt "角色说：你好" --generate-audio

# 查询任务状态
python3 scripts/seedance_video.py status --task-id cgt-xxxxx
```

### 可用模型

| 模型 ID | 说明 | 参考音频 |
|---------|------|----------|
| `doubao-seedance-2-0-260128` | 2.0 标准版 | 支持 |
| `doubao-seedance-2-0-fast-260128` | 2.0 快速版 | 支持 |
| `doubao-seedance-1-5-pro-251215` | 1.5 专业版（默认推荐） | 不支持 |

### Seedance vs RunningHub 选择指南

| 场景 | 推荐工具 | 原因 |
|------|----------|------|
| 纯文生视频（无参考图） | Seedance | RunningHub 不支持文生视频 |
| 场景图 → 视频（首帧动起来） | Seedance | 画质更高、速度更快 |
| 角色一致性图生视频 | RunningHub | 节点 `156` 角色参考更精准 |
| 首尾帧控制过渡 | Seedance | 独有首尾帧功能 |
| 多角色对话+音色克隆 | Seedance 2.0 | 参考音频原生支持 |
| 批量分集成片（6段式） | RunningHub | 工作流已调优 |
| 镇妖录仙侠场景视频 | Seedance | 电影级特效更适合仙侠风格 |

> 详细文档：[docs/seedance_video_README.md](./docs/seedance_video_README.md)

## 看板与展示说明

**MinIO 版动态看板（推荐）**：[songkou-dashboard-minio.html](./songkou-dashboard-minio.html)
- 双击本地打开即可浏览全部 MinIO 资源（图片/视频/音频），支持类型筛选与搜索
- 数据源双保险：主 MinIO 桶内清单 `resources/minio-manifest.json`（`sync` 后自动更新到桶），备为页面内置快照
- 素材卡片上的链接即 MinIO URL，可直接复制用于 RunningHub / Seedance API 传参

仓库内另保留了三个历史看板 HTML（`songkou-dashboard.html`、`songkou-dashboard-dynamic.html`、`yaolu-dashboard.html`）与 `index.html`。

> ⚠️ 历史看板内嵌的素材链接仍指向原仓库 h3-video-coding 的 jsDelivr CDN / GitHub Pages 地址，属于历史快照（原仓库为公开仓库，链接仍可访问）。

## 当前进度（2026-08-29 快照，来自原仓库）

- **剧本+提示词**：100%（20 集 × 4 段 6 段式提示词）
- **成片**：5%（仅 EP1 完成 v2）
- **角色定妆图**：林小溪✅ / 神秘旅人⏳已提交 / 陈阿公⏳已提交v2 / 张导演❌ / 小糯米❌
- 详见主文档第三章"项目实施进度看板"

## 关联文档

- [1、【实施中】嵩口宣传项目.md](./1、【实施中】嵩口宣传项目.md) — 项目主文档（进度/资产/瑕疵/版本）
- [2、【规划中】嵩口镇妖录.md](./2、【规划中】嵩口镇妖录.md) — 镇妖录项目规划文档
- [嵩口镇妖录_剧本.md](./嵩口镇妖录_剧本.md) — 12集完整对话剧本
- [resources/minio-manifest.json](./resources/minio-manifest.json) — 媒体资源总索引（MinIO 对象键与链接）
- [docs/seedance_video_README.md](./docs/seedance_video_README.md) — Seedance视频生成使用说明
- [docs/seedance_video_SKILL.md](./docs/seedance_video_SKILL.md) — Seedance Skill定义（触发词）
- [docs/嵩口EP3_鹤形之谜_极简制作单.md](./docs/嵩口EP3_鹤形之谜_极简制作单.md) — EP3 试制链路
- [docs/嵩口提示词优化_v2.md](./docs/嵩口提示词优化_v2.md) — v2 提示词规范
- [docs/长期记忆_工作流节点配置.md](./docs/长期记忆_工作流节点配置.md) — RunningHub + Seedance 节点配置（已验证）
- [docs/runninghub-skill.md](./docs/runninghub-skill.md) — RunningHub API 技能指南
