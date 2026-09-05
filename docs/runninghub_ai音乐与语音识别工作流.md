# RunningHub AI 音乐与语音识别工作流

> 创建时间：2026-09-01
> 更新时间：2026-09-05（音乐生成升级为三节点格式 + plus 实例）
> 平台：RunningHub OpenAPI v2
> API Key 环境变量：`RUNNINGHUB_API_KEY`

---

## 一、AI 应用清单

| 应用 | App ID | 类型 | 用途 | 消耗 |
|------|--------|------|------|------|
| MiniMax H3 音乐生成 | `2094807049065558018` | ai-app | 文本生成带人声的完整歌曲 | - |
| 语音转字幕 (ASR) | `2094729697874763777` | ai-app | 音频转 SRT 字幕 | 约 7-8 coins/次 |
| H3 全能参考视频生成 | `2090774740146413570` | ai-app | 图生视频 | 约 75 coins/15秒 |

---

## 二、MiniMax H3 音乐生成 — 完整工作流

### 2.1 应用信息

- **App ID**: `2094807049065558018`
- **输入**: 完整歌词文本 + 曲风结构化描述（三节点分离，互不干扰）
- **输出**: mp3 音乐文件（含人声演唱）
- **节点配置（三节点新格式）**:
  - `nodeId: 55`, `fieldName: text` — 完整歌词（段落标签 + 括号编曲提示，**不放**曲风构想）
  - `nodeId: 49`, `fieldName: cfg` — 提示词强度（建议 1.5-2.0）
  - `nodeId: 56`, `fieldName: text` — 曲风结构化描述（Global Metadata / Vocal Details / Arrangement 三段式英文）
- **实例类型**: `instanceType: "plus"`（旧格式 default 已弃用，plus 出品质量更稳定）
- **输出节点**: `nodeId: 9`, `outputType: mp3`
- **时长**: 根据歌词长度自动生成（约 2-4 分钟）
- **实测消耗**: 约 110 coins/次（plus 实例，2026-09-05）

> ⚠️ 旧二节点格式（nodeId 55 混合风格+歌词 + instanceType default）仍可调用，但新项目一律使用三节点格式，风格与歌词解耦后改曲风无需重写歌词。

### 2.2 调用方式

```bash
export RUNNINGHUB_API_KEY="你的API Key"

curl --request POST 'https://www.runninghub.cn/openapi/v2/run/ai-app/2094807049065558018' \
--header "Content-Type: application/json" \
--header "Authorization: Bearer ${RUNNINGHUB_API_KEY}" \
--data-raw '{
  "nodeInfoList": [
    {
      "nodeId": "55",
      "fieldName": "text",
      "fieldValue": "(Intro 前奏)\n(深沉的 Kick 鼓点低频敲击，伴随水波声与采样极重延迟的古筝单音，营造慢摇迷幻感)\n\n(Verse 1 主歌一)\n夜泊秦淮 岸边的灯火渐次熄灭\n笙歌散尽 谁在船头 泼墨成雪\n\n(Chorus 副歌)\n画舫摇呀摇 摇晃着千年的寂寞\n你在故事的角落 哼着哪首江南的歌\n\n(Outro 尾声)\n(鼓点逐渐抽离，只剩 Bass 低鸣与古筝余音缓缓 Fade Out)\n秦淮夜… 慢摇过客…",
      "description": "歌词"
    },
    {
      "nodeId": "49",
      "fieldName": "cfg",
      "fieldValue": "1.7",
      "description": "提示词强度"
    },
    {
      "nodeId": "56",
      "fieldName": "text",
      "fieldValue": "[Global Metadata]\nGenre: Chinoiserie Downtempo, Chinese electronica ballad\nTempo: 92 BPM, 4/4 time signature\nMood: dreamy, nostalgic, night-drift atmosphere of an ancient water town\n\n[Vocal Details]\nLead vocal: soft ethereal female voice, Mandarin Chinese\nDelivery: intimate breathy verses, gently soaring chorus\n\n[Arrangement]\nIntro: deep 808 bass pulse, guzheng plucks drenched in delay\nVerse: sparse 808 groove, soft kick on quarter notes, erhu long notes\nChorus: full downtempo beat, guzheng and erhu counter-melody\nOutro: drums fade out, 808 low hum with guzheng residue",
      "description": "曲风描述"
    }
  ],
  "instanceType": "plus",
  "usePersonalQueue": "false"
}'
```

### 2.3 歌词提示词撰写规范（节点 55）

**要点**：歌词节点只写歌词本身 + 括号编曲提示，曲风全部移到节点 56，不要在歌词里写【曲风构想】段。

**标准结构：**
```
(Intro 前奏)
（配器/氛围描述，无人声）

(Verse 1 主歌一)
第一句歌词
第二句歌词
...

(Pre-Chorus 副歌前预热)
（配器/情绪描述）

(Chorus 副歌)
副歌第一句
副歌第二句
...

(Bridge 过渡段)
（配器/情绪描述）

(Final Chorus 终极副歌)
副歌重复/变奏

(Outro 尾声)
（配器/收尾描述）
```

### 2.4 曲风结构化描述撰写规范（节点 56）

**三段式英文结构**，段标签固定为 `[Global Metadata]` / `[Vocal Details]` / `[Arrangement]`：

```
[Global Metadata]
Genre: 曲风名（如 Chinoiserie Downtempo, Chinese electronica ballad）
Tempo: BPM 数值 + 拍号
Key: 调式（可写 pentatonic-leaning 引导五声音阶）
Mood: 情绪关键词 + 一句意境描述
Dynamics: 动态特征（restrained / subtle builds 等）

[Vocal Details]
Lead vocal: 声线类型 + 演唱语言
Delivery: 主歌/副歌演唱方式（breathy verses, soaring chorus 等）
Ad-libs: 和声/哼鸣等点缀

[Arrangement]
Intro: 前奏配器 + 氛围
Verse: 主歌配器骨架
Chorus: 副歌全奏编制
Bridge/Outro: 过渡段与收尾处理
```

**常用配器英文对照**：古筝 guzheng、二胡 erhu、琵琶 pipa、竹笛 bamboo flute、洞箫 xiao flute、808 Bass（直接写）、Delay/延迟回声、tremolo 轮指。

### 2.5 查询结果

```bash
curl --request POST 'https://www.runninghub.cn/openapi/v2/query' \
--header "Content-Type: application/json" \
--header "Authorization: Bearer ${RUNNINGHUB_API_KEY}" \
--data-raw '{
  "taskId": "你的任务ID"
}'
```

**成功响应示例：**
```json
{
  "taskId": "xxx",
  "status": "SUCCESS",
  "results": [
    {
      "url": "https://rh-images-xxx.cos.ap-beijing.myqcloud.com/.../music_xxx.mp3",
      "nodeId": "9",
      "outputType": "mp3"
    }
  ],
  "usage": {
    "consumeCoins": "xx",
    "taskCostTime": "xxx"
  }
}
```

### 2.6 常用曲风参考（写入节点 56）

| 曲风 | 适用场景 | 曲风描述关键词（英文） |
|------|----------|--------|
| 中国风慢摇电子 | 古镇/夜游/国风 MV | Chinoiserie Downtempo, 808 bass, guzheng, erhu, delay |
| 仙侠古风 | 修仙/战斗/情感 | Epic Chinese orchestral, pipa, strings, choir |
| 江南民谣 | 日常/温情/美食 | Chinese folk ballad, acoustic guitar, bamboo flute, gentle |
| 电子国风 | 现代+古风融合 | Chinese synth-pop, guzheng samples, trap hats, neon vibe |

> 实测记录：《古镇之灵》民谣版（二节点+default）377s/76 coins；《古镇之灵》慢摇电子版（三节点+plus）191s/110 coins，新格式一次提交成功。


---

## 三、语音转字幕 (ASR) — 完整工作流

### 3.1 应用信息

- **App ID**: `2094729697874763777`
- **输入**: 音频文件（mp3 / flac / wav 等）
- **输出**: SRT 格式字幕文件 (.txt)
- **节点**: `nodeId: 25`, `fieldName: audio`
- **耗时**: 约 30-60 秒（2 分钟音频约 40 秒）
- **消耗**: 约 7-8 coins

### 3.2 调用方式

**前置条件**：音频文件需先上传到可公开访问的 URL（推荐 GitHub raw 链接）。

```bash
export RUNNINGHUB_API_KEY="你的API Key"

# 提交任务
curl --request POST 'https://www.runninghub.cn/openapi/v2/run/ai-app/2094729697874763777' \
--header "Content-Type: application/json" \
--header "Authorization: Bearer ${RUNNINGHUB_API_KEY}" \
--data-raw '{
  "nodeInfoList": [
    {
      "nodeId": "25",
      "fieldName": "audio",
      "fieldValue": "https://raw.githubusercontent.com/your-repo/path/to/audio.mp3",
      "description": "audio"
    }
  ],
  "instanceType": "default",
  "usePersonalQueue": "false"
}'
```

### 3.3 查询结果

```bash
curl --request POST 'https://www.runninghub.cn/openapi/v2/query' \
--header "Content-Type: application/json" \
--header "Authorization: Bearer ${RUNNINGHUB_API_KEY}" \
--data-raw '{
  "taskId": "你的任务ID"
}'
```

**成功响应示例：**
```json
{
  "taskId": "2094811181486395393",
  "status": "SUCCESS",
  "results": [
    {
      "url": "https://rh-images-xxx.cos.ap-beijing.myqcloud.com/.../subtitle_xxx.txt",
      "nodeId": "7",
      "outputType": "txt"
    }
  ],
  "usage": {
    "consumeCoins": "8",
    "taskCostTime": "39"
  }
}
```

### 3.4 输出格式 (SRT)

```
1
00:00:00,000 --> 00:00:05,000
第一句歌词

2
00:00:05,000 --> 00:00:10,000
第二句歌词
```

### 3.5 使用场景

| 场景 | 说明 |
|------|------|
| 歌曲歌词识别 | AI 生成音乐后，自动提取歌词文本和时间轴 |
| 对话字幕生成 | 角色配音音频自动打时间轴字幕 |
| 视频字幕对齐 | 为成片自动生成 SRT 字幕文件 |

### 3.6 注意事项

1. **前奏/间奏部分**：无人声时可能识别出乱码或时间轴为 0，属于正常现象
2. **长音频**：目前测试 2 分 40 秒无压力，更长音频需自行测试
3. **COS 链接时效**：输出文件是临时 COS 链接，生成后需及时下载保存
4. **音频格式**：mp3 / flac / wav 均可，建议使用 GitHub raw 链接直接调用，无需上传

---

## 四、标准制作链路：AI 音乐 → 字幕 → 视频

```
编写音乐描述 + 完整歌词（曲风/Verse/Chorus结构）
    ↓
调用 MiniMax H3 音乐生成（App 2094807049065558018）
    ↓
获取 mp3 文件 → 上传到 GitHub audio/music/ 目录
    ↓
调用 ASR 字幕应用识别歌词（App 2094729697874763777）
    ↓
获取 SRT 字幕 → 校对润色歌词和时间轴
    ↓
选 15 秒片段 → 截音 + 对应歌词 → 调用 H3 视频生成
    ↓
生成音画同步视频 → 下载到 videos/songkou_xianxia/
```

---

## 五、相关文件

| 文件 | 说明 |
|------|------|
| `audio/music/` | AI 生成音乐存放目录 |
| `docs/runninghub_video_curl模板.md` | H3 视频生成调用模板 |
| `docs/长期记忆_工作流节点配置.md` | 所有工作流节点总览 |
| `scripts/seedance_video.py` | 豆包 Seedance 视频生成脚本 |
