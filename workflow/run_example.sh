#!/bin/bash
# ============================================================
# RunningHub API 一键示例：提交 → 轮询 → 下载
# 用法：
#   export RUNNINGHUB_API_KEY="你的key"
#   bash workflow/run_example.sh [workflow/xxx.json]
# 默认演示 img2video_minimax_h3.json（约 5 分钟，消耗 58-60 RH 币）
# ============================================================
set -euo pipefail

BASE="https://www.runninghub.cn/openapi/v2"
KEY="${RUNNINGHUB_API_KEY:?请先 export RUNNINGHUB_API_KEY=你的key}"
WF="${1:-workflow/img2video_minimax_h3.json}"

# 案例 JSON → App ID 映射（替换为你自己账号中的 ai-app ID）
declare -A APP_IDS=(
  ["text2img_zimage.json"]="2088920592350277634"
  ["img2img_kera2edit.json"]="2088926295186034689"
  ["img2video_minimax_h3.json"]="2088844222551121921"
  ["text2music_minimax.json"]="2094807049065558018"
  ["imgaudio2video_multishot.json"]="2100129733211148290"
)

base=$(basename "$WF")
APP_ID="${APP_IDS[$base]:-}"
[ -n "$APP_ID" ] || { echo "未映射的案例文件：$base，请在脚本 APP_IDS 中登记 App ID"; exit 1; }

mkdir -p output

echo "== 1/3 提交任务：$WF → app $APP_ID =="
RESP=$(curl -s -X POST "$BASE/run/ai-app/$APP_ID" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $KEY" \
  -d @"$WF" --max-time 30)
echo "$RESP"
TASK_ID=$(echo "$RESP" | python3 -c "import json,sys; print(json.load(sys.stdin).get('taskId',''))")
[ -n "$TASK_ID" ] || { echo "提交失败"; exit 1; }
echo "taskId=$TASK_ID"

echo "== 2/3 轮询（每 30s，最长 15 分钟） =="
URL=""
for i in $(seq 1 30); do
  sleep 30
  DATA=$(curl -s -X POST "$BASE/query" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $KEY" \
    -d "{\"taskId\":\"$TASK_ID\"}" --max-time 30)
  STATUS=$(echo "$DATA" | python3 -c "import json,sys; print(json.load(sys.stdin).get('status',''))")
  echo "[$i] $STATUS"
  if [ "$STATUS" = "SUCCESS" ]; then
    URL=$(echo "$DATA" | python3 -c "import json,sys; print(json.load(sys.stdin)['results'][0]['url'])")
    break
  fi
  if [ "$STATUS" = "FAILED" ]; then
    echo "$DATA" | python3 -m json.tool
    exit 1
  fi
done
[ -n "$URL" ] || { echo "超时：taskId=$TASK_ID（可用查询接口续查，无需重复提交）"; exit 1; }

echo "== 3/3 下载产物 =="
EXT="${URL##*.}"; EXT="${EXT%%\?*}"
OUT="output/result_$(date +%s).${EXT:-bin}"
curl -sL -o "$OUT" "$URL" --max-time 180
echo "已保存：$OUT（结果 URL 24 小时内有效，请及时转存 MinIO）"
