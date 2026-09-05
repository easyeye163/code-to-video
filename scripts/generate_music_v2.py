# -*- coding: utf-8 -*-
"""
《古镇之灵》Chinoiserie Downtempo 版 — 三节点新格式
节点 55: 纯歌词（段落标签 + 括号编曲提示）
节点 49: cfg 提示词强度
节点 56: 曲风结构化描述（Global Metadata / Vocal Details / Arrangement 三段式英文）
instanceType: plus
"""
import requests
import json
import time
import os
import sys

# ===== 配置 =====
API_KEY = os.environ.get("RUNNINGHUB_API_KEY", "8fb0b806946040448ef2e8ef1ea891de")
APP_ID = "2094807049065558018"  # MiniMax H3 音乐生成
BASE_URL = "https://www.runninghub.cn/openapi/v2"
SAVE_PATH = "/home/z/my-project/download/songkou_guzhenzhiling_downtempo.mp3"
STATE_FILE = "/home/z/my-project/scripts/.music_task_state.json"  # 断点续跑状态

# ===== 节点 56: 曲风结构化描述（三段式英文） =====
style_prompt = """[Global Metadata]
Genre: Chinoiserie Downtempo, Chinese electronica ballad
Tempo: 92 BPM, 4/4 time signature
Key: D minor with pentatonic-leaning melody
Mood: dreamy, nostalgic, serene; night-drift atmosphere of an ancient water town
Dynamics: restrained and hypnotic, subtle builds, smooth long transitions

[Vocal Details]
Lead vocal: soft ethereal female voice, Mandarin Chinese
Delivery: intimate breathy verses, gently soaring chorus, light stacked harmonies in chorus
Ad-libs: minimal humming echoes at section transitions

[Arrangement]
Intro: deep 808 bass pulse, guzheng plucks drenched in delay, faint water-stream ambience
Verse: sparse 808 groove, soft kick on quarter notes, guzheng arpeggios, erhu long sustained notes
Pre-Chorus: pipa tremolo builds, warm pads widen, subtle riser
Chorus: full downtempo beat, 808 sub-bass, guzheng and erhu counter-melody, layered backing vocals
Bridge: beat thins to half-time, guzheng and lead vocal duet, erhu answering phrases
Outro: drums fade out, 808 low hum with guzheng residue slowly fade to silence"""

# ===== 节点 55: 歌词（保留原词，编曲提示改电子版） =====
lyrics = """(Intro 前奏)
(深沉的808 Bass低频渐入，古筝单音在延迟回声中浮现，溪水采样若隐若现)

(Verse 1 主歌一)
大樟溪的水 静静地流过千年
白墙黛瓦间 谁的梦还未做完
古榕树下 一盏灯笼摇曳着暖
风吹鹤形路 石板上落花片片

(Verse 2 主歌二)
德星楼的檐角 挂着一弯新月
古码头的碑文 刻着谁的离别
用坦厝的天井 漏下一束光
照见阿公沏茶 说起从前的模样

(Pre-Chorus 导歌)
(琵琶轮指渐密，合成器铺底缓缓抬升)

(Chorus 副歌)
古镇的灵 是溪水里的月光
是夯土墙上 岁月留下的霜
你听那风 穿过一百八十三间房
每一扇门后 都藏着一段悠长

古镇的灵 是鹤影掠过的窗
是青石板上 脚步声的回响
你走多远 回头她还在原处望
等着你归来 再尝一碗蛋燕汤

(Instrumental 间奏)
(二胡独奏如泣如诉，808鼓点收紧，古筝琶音在电音延迟中交织)

(Verse 3 主歌三)
万安堡的墙 说过多少故事
宁远庄的月 照过几番别离
九重粿蒸起 甜甜糯糯的香气
谁家的姑娘 唱着不知名的曲

(Chorus 副歌)
古镇的灵 是溪水里的月光
是夯土墙上 岁月留下的霜
你听那风 穿过一百八十三间房
每一扇门后 都藏着一段悠长

(Bridge 桥段)
(鼓点半抽离，只剩古筝与人声清唱，二胡远远应答)
松一松肩 倦了就回来看看
这座古镇 从不催促谁的步慢
门前的溪水 会替她记着你的归期
等到那天 推门就是家

(Final Chorus 终极副歌)
古镇的灵 是溪水里的月光
是夯土墙上 岁月留下的霜
你听那风 穿过一百八十三间房
每一扇门后 都藏着一段悠长

(Outro 尾声)
(鼓点逐渐抽离，只剩808低鸣与古筝余音缓缓淡出)
古镇的灵… 一直在你身旁…"""

# ===== 1. 提交音乐生成任务（三节点格式） =====
def generate_music(cfg=1.7):
    """调用 MiniMax H3 生成音乐 — 三节点新格式 + instanceType plus"""
    url = f"{BASE_URL}/run/ai-app/{APP_ID}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}"
    }
    payload = {
        "nodeInfoList": [
            {
                "nodeId": "55",
                "fieldName": "text",
                "fieldValue": lyrics,
                "description": "歌词"
            },
            {
                "nodeId": "49",
                "fieldName": "cfg",
                "fieldValue": str(cfg),
                "description": "提示词强度"
            },
            {
                "nodeId": "56",
                "fieldName": "text",
                "fieldValue": style_prompt,
                "description": "曲风描述"
            }
        ],
        "instanceType": "plus",
        "usePersonalQueue": "false"
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    data = resp.json()
    print(f"提交响应: {json.dumps(data, ensure_ascii=False, indent=2)}")

    if "taskId" not in data:
        print(f"提交失败: {data.get('msg') or data}")
        return None

    task_id = data.get("taskId")
    # 状态落盘：中断后凭 taskId 续查，不重复提交烧币
    with open(STATE_FILE, "w") as f:
        json.dump({"taskId": task_id, "save_path": SAVE_PATH, "submitted_at": time.time()}, f)
    print(f"音乐生成任务已提交: {task_id}（状态已落盘 {STATE_FILE}）")
    return task_id

# ===== 2. 轮询任务状态 =====
def query_task(task_id, interval=30, max_wait=900):
    """查询任务状态，直到完成或超时"""
    url = f"{BASE_URL}/query"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}"
    }

    for i in range(max_wait // interval):
        try:
            resp = requests.post(url, headers=headers, json={"taskId": task_id}, timeout=30)
            data = resp.json()
        except requests.RequestException as e:
            print(f"网络异常（{e}），{interval}s 后重试...")
            time.sleep(interval)
            continue

        status = data.get("status")

        if status == "SUCCESS":
            result_url = data["results"][0]["url"]
            output_type = data["results"][0].get("outputType", "unknown")
            coins = data.get("usage", {}).get("consumeCoins", "?")
            cost_time = data.get("usage", {}).get("taskCostTime", "?")
            print(f"任务完成！耗时 {cost_time}s，消耗 {coins} coins，类型: {output_type}")
            return result_url
        elif status == "FAILED":
            print(f"任务失败: {data.get('errorMessage') or data.get('msg')}")
            return None

        print(f"第 {i+1} 次轮询，状态: {status}，等待 {interval}s...")
        time.sleep(interval)

    print("任务超时（taskId 已落盘，可直接续查）")
    return None

# ===== 3. 下载音乐文件（.part 原子落盘） =====
def download_file(url, save_path):
    """下载文件到本地"""
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    part_path = save_path + ".part"
    resp = requests.get(url, timeout=180)
    with open(part_path, "wb") as f:
        f.write(resp.content)
    os.replace(part_path, save_path)
    print(f"已保存到: {save_path} ({os.path.getsize(save_path)/1024/1024:.1f} MB)")

# ===== 主流程 =====
if __name__ == "__main__":
    print("===== 古镇之灵 Chinoiserie Downtempo 版 - AI音乐生成 =====")
    print("曲风: 国风慢摇电子 (Chinoiserie Downtempo)")
    print("配器: 808 Bass + 古筝 + 二胡 + 琵琶, 92 BPM")
    print("格式: 三节点 (55歌词 / 49cfg / 56曲风) + instanceType plus")

    # 断点续跑：已有 taskId 则直接续查，不重复提交
    if os.path.exists(STATE_FILE) and "--resume" in sys.argv:
        with open(STATE_FILE) as f:
            state = json.load(f)
        task_id = state["taskId"]
        print(f"\n[--resume] 沿用已提交任务: {task_id}")
    else:
        task_id = generate_music(cfg=1.7)

    if task_id:
        print(f"\n开始轮询任务状态...\n")
        music_url = query_task(task_id, interval=30, max_wait=900)

        if music_url:
            download_file(music_url, SAVE_PATH)
            os.remove(STATE_FILE)  # 清理状态
            print("\n===== 音乐生成完成！ =====")
        else:
            print("\n音乐生成失败或超时（可用 --resume 续查，无需重新提交）")
            sys.exit(1)
