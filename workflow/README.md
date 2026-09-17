# workflow/ — RunningHub API 调用 JSON 案例

本目录专门存放 **RunningHub（云端 ComfyUI / ai-app）API 调用 JSON 案例**，覆盖图片、视频、音乐三类生成任务。每个 JSON 即一次 `提交任务` 接口的完整请求体，可直接作为 curl 的 `-d` 参数使用。

## ⚠️ 安全约定（必读）

- **API Key 一律不入库**：所有案例中不含密钥，调用前先设置环境变量：
  ```bash
  export RUNNINGHUB_API_KEY="你的RunningHub API Key"
  ```
- `APP_ID`（ai-app 编号）是各案例对应的工作流 ID，替换为你自己账号中已部署工作流的 App ID。
- 提交任务会消耗 RH 币，运行前确认工作流定价。

## 通用调用流程（四步）

### 1. 提交任务

```bash
curl -s -X POST "https://www.runninghub.cn/openapi/v2/run/ai-app/${APP_ID}" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${RUNNINGHUB_API_KEY}" \
  -d @workflow/img2video_minimax_h3.json --max-time 30
# 返回 {"code":200, "taskId":"xxxx"} → 记下 taskId
```

### 2. 轮询结果（每 30 秒一次）

```bash
curl -s -X POST "https://www.runninghub.cn/openapi/v2/query" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${RUNNINGHUB_API_KEY}" \
  -d '{"taskId":"<TASK_ID>"}' --max-time 30
# 状态机: QUEUED → RUNNING → SUCCESS / FAILED
```

### 3. 下载产物（SUCCESS 后，URL 24 小时有效）

```bash
curl -sL -o output/result.mp4 "<results[0].url>" --max-time 180
```

### 4.（可选）上传本地素材作为参考图

```bash
curl -s -X POST "https://www.runninghub.cn/openapi/v2/media/upload/binary" \
  -H "Authorization: Bearer ${RUNNINGHUB_API_KEY}" \
  -F "file=@./my_image.png" --max-time 60
# 返回 data.fileName（如 openapi/xxxx.png），填入对应 image 节点的 fieldValue
```

## 案例清单

| 文件 | 用途 | 关键节点 | 参考耗时 | 参考消耗 |
|------|------|----------|----------|----------|
| `text2img_zimage.json` | 文生图（Z-image） | node 17 `prompt` | 30-120s | 低 |
| `img2img_kera2edit.json` | 图生图：参考图+提示词改图（局部重绘/风格迁移） | node 160 `text`、node 104 `image` | 60-170s | 14-34 币 |
| `img2video_minimax_h3.json` | 图生视频（AnimateDiff + MiniMax H3，支持对话/口播） | node 138 `value`（提示词）、node 137 `image` | 约 5 分钟 | 58-60 币 |
| `text2music_minimax.json` | AI 音乐生成（三节点新格式：55 歌词 / 49 cfg / 56 曲风） | node 55/49/56 | 3-7 分钟 | 数十币 |

## 一键运行

```bash
# 提交 → 轮询 → 自动下载（默认演示图生视频案例）
bash workflow/run_example.sh workflow/img2video_minimax_h3.json
```

## 提示词规范

- 图生视频使用 **6 段式 Full-Reference** 提示词（subject_definitions / summary / retention_analysis / detailed_description / overall_soundscape / non_diegetic_music），完整规则与模板见 [docs/提示词模板_FullReference.md](../docs/提示词模板_FullReference.md)
- ⚠️ MiniMax H3 图生视频工作流的音频节点未连接，提示词中**不要出现 `<Audio 1>` 引用**，否则报错 `prompt media tag validation failed: <Audio 1> is not connected`；需要配音时后期用 edge-tts + ffmpeg 叠加
- `fieldValue` 中的换行在 JSON 里写作 `\n`

## 常见错误

| 错误 | 原因 | 处理 |
|------|------|------|
| `errorCode 421` | 并发任务超限 | 等待在途任务完成再提交（pipeline.py 的 batch 已自动处理） |
| `errorCode 805` | 工作流执行失败 | 查看 `failedReason.traceback` 定位节点 |
| `<Audio 1> is not connected` | 提示词引用了未连接的音频节点 | 删除提示词中的 `<Audio N>` 段落 |
| `Invalid image file` | 参考图标识格式不对 | 使用上传接口返回的完整 `openapi/xxxx.png`，或可直接访问的完整 URL |
| `503 no available server` | 无可用实例 | 稍后重试 |

更多知识文档见 [docs/](../docs/)（RunningHub 技能总结、上传资源 fileName 缓存策略、音乐/ASR 工作流等）。
