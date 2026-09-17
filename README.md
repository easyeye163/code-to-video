# code-to-video · AI 短剧制作工作流知识库

> 基于 **6 段式 Full-Reference 提示词 + RunningHub API + 火山引擎 Seedance + MinIO 对象存储** 的 AI 短剧/短视频制作体系。
>
> 本仓库为**纯代码 + 脚本 + 文档**的知识库：媒体资源（图片/音频/视频）**不入库**，统一由 **MinIO 对象存储**管理，以 URL 链接形式引用，克隆秒级完成。换一个题材 = 复制项目骨架填空。

## 目录结构

| 路径 | 功能 | 约束 / 说明 |
|---|---|---|
| `pipeline.py` | **制作流水线入口** | check / payload / submit / batch / render / verify / init-project / asset / backup / shotlist 十大命令；`shotlist` 为智能体结构化编辑层（详见 [docs/shotlist_智能体接口.md](docs/shotlist_智能体接口.md)） |
| `workflow/` | **RunningHub API 调用 JSON 案例** | 文生图/图生图/图生视频/音乐四类请求体 + 一键脚本，密钥一律环境变量 |
| `projects/` | **项目抽象层** | 每个短剧项目一份自包含配置；`example/` 为可跑通的模板骨架 |
| `scripts/` | Python / Shell 脚本 | 对话音频、音乐生成、Seedance、MinIO 同步、飞书同步等 |
| `docs/` | 知识文档 | 节点配置/提示词模板/工作流分析/制作链路经验 |
| `resources/` | 资源清单（生成物，不入库） | `minio-manifest.json` 由 `minio_sync.py scan` 生成 |
| `微信公众号文章/` | 方法论文章 | AI 视频制作实战复盘 |

## 快速开始

### 0) 环境准备

```bash
export RUNNINGHUB_API_KEY="你的RunningHub Key"     # workflow/ 与 pipeline 提交任务用
export VOLCENGINE_ARK_API_KEY="你的火山引擎Key"     # Seedance（豆包/即梦）视频生成用
cp scripts/minio_config.example.json scripts/minio_config.json   # 填入 MinIO 地址与密钥
pip install -r scripts/requirements.txt
```

### 1) 跑通一个生成任务（workflow/）

```bash
bash workflow/run_example.sh workflow/img2video_minimax_h3.json
# 提交 → 轮询 → 自动下载；四类案例与 API 细节见 workflow/README.md
```

### 2) 新建一个短剧项目

```bash
# 方式一：脚手架（推荐，自动生成配置+模板+分镜说明+开工清单）
python pipeline.py init-project projects/ancient_town_x --title "XX古镇奇缘"

# 方式二：复制 example 骨架手改
cp -r projects/example projects/ancient_town_x
```

素材不用手工准备：`asset` 命令直接文生图产角色立绘/三视图/场景图，自动入 MinIO 并回写 `project.json` 的 `ref_image`——**换一个题材从此是填空题**：填角色设定 → asset 批产形象 → 写分镜 → batch 出片 → render 成片。

### 3) 流水线九命令

```bash
python pipeline.py check   projects/ancient_town_x            # 校验配置/分镜/资产可解析
python pipeline.py payload projects/ancient_town_x --ep 1     # 生成整集 payload（不消耗币）
python pipeline.py submit  projects/ancient_town_x --ep 1 --seg 2 --wait   # 提交并等待成片
python pipeline.py batch   projects/ancient_town_x --ep 1 [--continue-on-error]  # 串行批量（421等待+断点续接+URL重下）
python pipeline.py render  projects/ancient_town_x --ep 1 --title "第1集" [--bgm music.mp3]  # 拼接+字幕+BGM混音成片
python pipeline.py verify  projects/ancient_town_x --ep 1     # 台词保真验收：ASR 回读 vs 剧本逐字比对
python pipeline.py asset   projects/ancient_town_x --character heroine [--three-view --ref-url URL]  # 素材自动生成入 MinIO
python pipeline.py backup  projects/ancient_town_x --ep 1     # 出海素材包：无字幕段+SRT+无字幕成片 → MinIO
python pipeline.py shotlist show projects/ancient_town_x --ep 1 --prompt  # 智能体：读分镜+指纹+渲染预览（零消耗）
python pipeline.py shotlist set  projects/ancient_town_x --ep 1 --seg 2 --shot 1 --field dialogue --value "新台词。"  # 智能体：改单个镜头字段（写前校验，带病不落盘）
```

### 4) 媒体资源上 MinIO（不入库原则）

```bash
python scripts/minio_sync.py scan <资源根目录>   # 扫描 audio/ images/ videos/ → resources/minio-manifest.json（gitignore）
python scripts/minio_sync.py sync  <资源根目录>   # 上传 MinIO（自动建桶+公开只读），产出公网 URL
python scripts/minio_sync.py url   <相对路径>     # 查询任意资源链接（传 API 时一律用 MinIO 链接）
python scripts/minio_sync.py presign --expire-days 7   # 私有桶临时签名链接
```

**设计原则**：仓库只保留代码与知识库；素材通过公网 URL 传给 RunningHub / Seedance API，与本地文件引用完全等价。

## 项目目录结构

| 文件 | 作用 |
|---|---|
| `project.json` | 引擎参数（AppID/画幅/双角色布局 `engine.dual_layout`/`asset_style`）、角色库（形象/音色/不变量）、场景库（参照图/锚点/不变量）、风格 |
| `prompt_template_single.txt` | 6 段式模板·单角色+场景 |
| `prompt_template_dual.txt` | 6 段式模板·双角色（节点分配由 `engine.dual_layout` 决定：缺省 P2=第二角色，`scene_at_166` 则 P2=场景） |
| `storyboards/epN.json` | 分集分镜：角色/场景/音色/时长/镜头/台词/声景/配乐 |
| `output/` | 生成的 payload/状态/成片（已 gitignore） |

详见 [projects/README.md](projects/README.md)。

## 核心概念：6 段式 Full-Reference 提示词

`subject_definitions → summary → retention_analysis → detailed_description → overall_soundscape → non_diegetic_music`，通过 `<Picture N>` / `<Subject N>` / `<Audio N>` 引用标签锁定角色一致性与场景锚点。

- 模板与 Rewrite 规则：[docs/提示词模板_FullReference.md](docs/提示词模板_FullReference.md) · [docs/长期记忆_分镜提示词模板.md](docs/长期记忆_分镜提示词模板.md)
- ⚠️ MiniMax H3 图生视频工作流的音频节点未连接，提示词中**不要引用 `<Audio 1>`**；配音后期用 edge-tts / 多角色声音一致性工作流 + ffmpeg 叠加

## RunningHub 工作流速查

| 工作流 | App ID | 关键节点 |
|---|---|---|
| Z-image 文生图 | `2088920592350277634` | `17`=prompt |
| KREA-2-EDIT 图生图 | `2088926295186034689` | `160`=text / `104`=image |
| AnimateDiff 单图视频 | `2088844222551121921` | `137`首帧/`138`提示词/`157`音频/`156`角色/`165`Audio/`166`Pic2/`132`时长/`115`比例 |
| 多图像视频生成 | `2088878767828717570` | `137`首帧/`157`音频/`156`角色/`138`提示词 |
| 音频生成（声音设计/TTS） | `2090440149267210242` | `3`声音设计/`5`TTS文本 |
| MiniMax H3 音乐（三节点） | `2094807049065558018` | `55`歌词/`49`cfg/`56`曲风 |

请求体 JSON 案例见 [workflow/](workflow/README.md)；节点配置详解见 [docs/长期记忆_工作流节点配置.md](docs/长期记忆_工作流节点配置.md) / [docs/长期记忆_节点配置总结.md](docs/长期记忆_节点配置总结.md)。

## Seedance 视频生成（豆包/即梦）

使用 `scripts/seedance_video.py`（文档：[docs/seedance_video_README.md](docs/seedance_video_README.md)）：

```bash
# 文生视频
python3 scripts/seedance_video.py generate --prompt "描述文本" --ratio 16:9 --duration 5
# 图生视频（首帧用 MinIO 资源链接）
python3 scripts/seedance_video.py generate --first-frame "https://<MinIO>/images/xxx.png" --prompt "让画面动起来" --ratio adaptive
# 首尾帧 / 多图全能参考 / 参考音频音色克隆（2.0 模型）详见文档
```

### Seedance vs RunningHub 选择指南

| 场景 | 推荐工具 | 原因 |
|------|----------|------|
| 纯文生视频（无参考图） | Seedance | RunningHub 不支持文生视频 |
| 场景图 → 视频（首帧动起来） | Seedance | 画质更高、速度更快 |
| 角色一致性图生视频 | RunningHub | 节点 `156` 角色参考更精准 |
| 首尾帧控制过渡 | Seedance | 独有首尾帧功能 |
| 多角色对话+音色克隆 | Seedance 2.0 | 参考音频原生支持 |
| 批量分集成片（6段式） | RunningHub | 工作流已调优 |

## 标准制作链路（单集 4 步）

```
[1] 文生图（Z-image）            → 场景图/概念图        → sync 上传 MinIO
        ↓
[2] 图生图（KREA-2-EDIT）        → 角色三视图/定妆图     → sync 上传 MinIO
        ↓
[3] 图生视频                     → 分段成片             → sync 上传 MinIO
        ├─ RunningHub AnimateDiff  （6段式提示词，角色一致性）
        └─ Seedance 豆包/即梦       （文生/首尾帧/参考音频，电影级画质）
        ↓
[4] pipeline verify + render     → ASR 台词验收 + 拼接字幕混音成片
```

## 协作约定

1. **资源引用**：引用媒体资产统一使用 MinIO 链接（`minio_sync.py url <path>` 查询），不用本地路径或第三方 CDN
2. **RunningHub 注意**：
   - COS 云端链接 24h 失效，成片需及时下载并 `sync` 上传 MinIO
   - 有并发限制，关键任务串行处理（`batch` 命令已内置 421 等待与断点续接，taskId 落盘不重复扣费）
3. **提示词规范**：6 段式 Full-Reference，模板见 `projects/example/` 与 `docs/`
4. **文件命名约定**：三视图 `xxx_three_view.png`；音色 `<角色>_voice.flac`；成片 `<项目>_第N集_标题_vX.mp4`
5. **资源清单**：新增/删除媒体文件后执行 `scan + sync` 重新生成清单（生成物不入库）

## 安全约定

- 所有 API Key（RunningHub / 火山引擎 / MinIO / 飞书）一律走环境变量或 `*_config.json`（已 gitignore），**不入库**
- `projects/*/output/`、`resources/minio-manifest.json`、`.workbuddy/` 为生成物/敏感信息，均已 gitignore
- 全部媒体扩展名（mp4/png/flac/mp3/wav…）已在 .gitignore 排除，媒体永不入库

## 关联文档

- [workflow/README.md](workflow/README.md) — RunningHub API 调用流程与 JSON 案例
- [projects/README.md](projects/README.md) — 项目结构与九命令用法
- [docs/seedance_video_README.md](docs/seedance_video_README.md) / [docs/seedance_video_SKILL.md](docs/seedance_video_SKILL.md) — Seedance 使用说明
- [docs/runninghub技能.md](docs/runninghub技能.md) — RunningHub 调用技巧（上传缓存/中文路径编码）
- [docs/runninghub_video_curl模板.md](docs/runninghub_video_curl模板.md) — 图生视频 curl 模板
- [docs/runninghub_ai音乐与语音识别工作流.md](docs/runninghub_ai音乐与语音识别工作流.md) — AI 音乐三节点 + ASR 字幕
- [docs/工作流分析_高级视频生成.md](docs/工作流分析_高级视频生成.md) — 高级视频生成工作流分析

## License

[MIT](LICENSE)
