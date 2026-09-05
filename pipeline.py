#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
code-to-video 制作流水线
========================

把「分镜数据 + 项目配置 + 提示词模板」自动组装成 RunningHub 任务 payload，
取代手工编写 scripts/ep*_seg*_payload.json 的流程。

项目抽象（projects/<项目名>/）：
  project.json           项目配置：引擎参数 / 角色库 / 场景库 / 风格
  prompt_template_*.txt  6段式提示词模板（single=单角色+场景，dual=双角色+场景）
  storyboards/epN.json   分集分镜数据（角色/场景/音色/镜头/台词）
  output/                生成的 payload（已 gitignore，不入库）

用法：
  python pipeline.py check   projects/songkou                  # 校验项目与分镜
  python pipeline.py payload projects/songkou --ep 7           # 生成整集 payload
  python pipeline.py payload projects/songkou --ep 7 --seg 1 --stdout
  python pipeline.py submit  projects/songkou --ep 7 --seg 1 [--wait]   # 提交（消耗币）
  python pipeline.py batch   projects/songkou --ep 7 [--continue-on-error]  # 串行批量（自动排队+下载）

单并发适配（batch）：
  - 同一时刻至多一个在途任务，421 占用自动等待重试
  - 提交成功立即落盘 taskId；中断重跑续接轮询，绝不重复提交烧币
  - 成片 SUCCESS 但本地缺失：按记录 URL 重下，URL 过期才重新生成
  - 轮询超时保留 taskId，重跑续接等待；网络抖动自动重试

资产解析：角色图/场景图/音色在配置中只写仓库相对路径，由 resources/minio-manifest.json
自动解析为 MinIO URL。清单缺失时先运行：
  python scripts/minio_sync.py scan <资源根目录> && python scripts/minio_sync.py sync <资源根目录>
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = ROOT / "resources" / "minio-manifest.json"
RUNNINGHUB_BASE = "https://www.runninghub.cn/openapi/v2"


def die(msg):
    print(f"✗ {msg}", file=sys.stderr)
    raise SystemExit(1)


def load_json(path: Path):
    try:
        return json.load(open(path, encoding="utf-8"))
    except FileNotFoundError:
        die(f"文件不存在：{path}")
    except json.JSONDecodeError as e:
        die(f"JSON 解析失败：{path}（{e}）")


class Assets:
    """资源清单解析器：仓库相对路径 → MinIO URL"""

    def __init__(self):
        if not MANIFEST_PATH.exists():
            die("缺少 resources/minio-manifest.json，请先运行 scripts/minio_sync.py scan")
        m = json.load(open(MANIFEST_PATH, encoding="utf-8"))
        self.urls = {e["path"]: e.get("url") for e in m.get("resources", [])}

    def url_of(self, path):
        if not path:
            raise ValueError("资产路径为空")
        url = self.urls.get(path)
        if not url:
            raise ValueError(f"资源未在清单中或尚未上传 MinIO：{path}")
        return url


class Project:
    def __init__(self, project_dir: Path):
        self.dir = project_dir
        self.cfg = load_json(project_dir / "project.json")
        self.characters = self.cfg.get("characters", {})
        self.scenes = self.cfg.get("scenes", {})
        self.templates = {}
        for mode, fname in self.cfg.get("prompt_templates", {}).items():
            tpath = project_dir / fname
            if not tpath.exists():
                die(f"提示词模板缺失：{tpath}")
            self.templates[mode] = tpath.read_text(encoding="utf-8")
        self.assets = Assets()

    def storyboard(self, ep: int):
        sb_path = self.dir / "storyboards" / f"ep{ep}.json"
        sb = load_json(sb_path)
        if sb.get("project") and sb["project"] != self.cfg.get("name"):
            die(f"分镜文件 {sb_path} 的 project 字段（{sb['project']}）与项目（{self.cfg.get('name')}）不符")
        return sb

    def char(self, key, where):
        if key not in self.characters:
            raise ValueError(f"{where}: 未知角色 “{key}”（可用：{', '.join(self.characters)}）")
        return self.characters[key]

    def scene(self, key, where):
        if key not in self.scenes:
            raise ValueError(f"{where}: 未知场景 “{key}”（可用：{', '.join(self.scenes)}）")
        return self.scenes[key]


def format_shots(shots):
    lines = []
    for i, s in enumerate(shots, 1):
        line = f"[Shot {i}]（{s['time']}）{s['desc']}"
        if s.get("dialogue"):
            line += f"<d>{s['dialogue']}</d>"
        lines.append(line)
    return "\n".join(lines)


def render_prompt(project: Project, seg: dict):
    """组装 6 段式提示词，返回 (prompt文本, p1角色, p2角色或None, 场景, 音色角色)"""
    where = f"ep? seg{seg.get('seg')}"
    p1 = project.char(seg.get("p1"), where)
    # 分段级覆盖：分镜可用 p1_identity / p2_identity / scene_desc 等前缀字段覆盖项目默认
    _P_KEYS = ("identity", "retention", "voice_desc", "role")
    p1 = {**p1, **{k[3:]: v for k, v in seg.items()
                   if k.startswith("p1_") and k[3:] in _P_KEYS}}
    scene = project.scene(seg.get("scene"), where)
    scene = {**scene, **{k[6:]: v for k, v in seg.items()
                         if k.startswith("scene_") and k[6:] in ("desc", "anchor", "extra", "retention")}}
    voice_key = seg.get("voice", seg.get("p1"))
    voice = project.char(voice_key, where)
    if not voice.get("voice"):
        raise ValueError(f"{where}: 角色 {voice['name']} 未配置音色文件")

    defaults = project.cfg["engine"]["defaults"]
    ctx = {
        "p1_gender": p1["gender"],
        "p1_identity": p1["identity"],
        "p1_name": p1["name"],
        "p1_retention": p1["retention"],
        "scene_desc": scene["desc"],
        "scene_anchor": scene["anchor"],
        "scene_extra": scene.get("extra", ""),
        "scene_retention": scene["retention"],
        "p1_role": p1.get("role", f"{p1['gender']}角色"),
        "drift_clause": seg.get("drift_clause", "全片不得漂移。"),
        "audio_line": "",
        "voice_desc": voice["voice_desc"],
        "duration": seg.get("duration", defaults["duration"]),
        "style_qualifier": project.cfg["style_qualifier"],
        "style_visual": project.cfg["style"]["visual"],
        "style_retention": project.cfg["style"]["retention"],
        "summary": seg["summary"],
        "shots": format_shots(seg["shots"]),
        "soundscape": seg["soundscape"],
        "music": seg["music"],
        "style_retention": seg.get("style_retention", project.cfg["style"]["retention"]),
    }

    p2 = None
    if "p2" in seg:
        p2 = project.char(seg["p2"], where)
        p2 = {**p2, **{k[3:]: v for k, v in seg.items()
                       if k.startswith("p2_") and k[3:] in _P_KEYS}}
        ctx["p2_gender"] = p2["gender"]
        ctx["p2_identity"] = p2["identity"]
        ctx["p2_retention"] = p2["retention"]
        ctx["p2_role"] = p2.get("role", f"{p2['gender']}角色")
        ctx["voice_subject"] = "1" if voice_key == seg["p1"] else "2"
        mode = "dual"
    else:
        mode = "single"

    if voice.get("voice") and seg.get(
            "voice_audio", project.cfg.get("voice_audio_default", True)):
        vs = ctx.get("voice_subject", "1")
        ctx["audio_line"] = f"<Audio 1> 为 <Subject {vs}>（S{vs}）的音色参考：{voice['voice_desc']}。"

    try:
        prompt = project.templates[mode].format(**ctx)
        prompt = re.sub(r"\n{3,}", "\n\n", prompt).rstrip("\n")  # 压缩空占位行、去尾部换行
    except KeyError as e:
        die(f"{mode} 模板占位符缺少数据：{e}")
    return prompt, p1, p2, scene, voice


def build_payload(project: Project, seg: dict, ep: int):
    prompt, p1, p2, scene, voice = render_prompt(project, seg)
    defaults = project.cfg["engine"]["defaults"]
    p1_url = project.assets.url_of(p1["ref_image"])
    scene_url = project.assets.url_of(scene["ref_image"])
    voice_url = project.assets.url_of(voice["voice"])

    if p2 is not None:  # 双角色模式：节点分配由 engine.dual_layout 决定
        if project.cfg["engine"].get("dual_layout") == "scene_at_166":
            # 镇妖录式：Picture 2=场景（node 166），Picture 3=第二角色（node 167）
            node166 = {"nodeId": "166", "fieldName": "image", "fieldValue": scene_url,
                       "description": f"picture2（{scene['name']}场景图）"}
            node167 = {"nodeId": "167", "fieldName": "image",
                       "fieldValue": project.assets.url_of(p2["ref_image"]),
                       "description": f"picture3（{p2['name']}角色图）"}
        else:
            # 嵩口式（默认）：Picture 2=第二角色（node 166），Picture 3=场景（node 167）
            node166 = {"nodeId": "166", "fieldName": "image",
                       "fieldValue": project.assets.url_of(p2["ref_image"]),
                       "description": f"picture2（{p2['name']}角色图）"}
            node167 = {"nodeId": "167", "fieldName": "image", "fieldValue": scene_url,
                       "description": f"picture3（{scene['name']}场景图）"}
    else:  # 单角色模式：P2=场景，P3=占位
        node166 = {"nodeId": "166", "fieldName": "image", "fieldValue": scene_url,
                   "description": f"picture2（{scene['name']}场景图）"}
        node167 = {"nodeId": "167", "fieldName": "image", "fieldValue": "example.png",
                   "description": "picture3（未使用）"}

    return {
        "nodeInfoList": [
            {"nodeId": "132", "fieldName": "value",
             "fieldValue": str(seg.get("duration", defaults["duration"])),
             "description": "时长（秒）"},
            {"nodeId": "115", "fieldName": "aspect_ratio",
             "fieldData": defaults["aspect_ratio_fielddata"],
             "fieldValue": defaults["aspect_ratio"], "description": "方向"},
            {"nodeId": "115", "fieldName": "megapixels",
             "fieldValue": defaults["megapixels"], "description": "分辨率"},
            {"nodeId": "137", "fieldName": "image", "fieldValue": p1_url,
             "description": f"picture1（{p1['name']}角色图）"},
            {"nodeId": "138", "fieldName": "value", "fieldValue": prompt,
             "description": "提示词（6段式 Full-Reference，pipeline.py 自动生成）"},
            node166,
            {"nodeId": "165", "fieldName": "audio", "fieldValue": voice_url,
             "description": f"audio1（{voice['name']}音色）"},
            node167,
            {"nodeId": "168", "fieldName": "image", "fieldValue": "example.png",
             "description": "picture4（占位，不要改）"},
            {"nodeId": "169", "fieldName": "audio", "fieldValue": voice_url,
             "description": "audio2（未使用，复用audio1）"},
        ],
        "instanceType": project.cfg["engine"]["instance_type"],
        "usePersonalQueue": defaults["use_personal_queue"],
    }


def cmd_check(project_dir: Path):
    project = Project(project_dir)
    problems = []

    for key, c in project.characters.items():
        try:
            project.assets.url_of(c.get("ref_image"))
        except ValueError as e:
            problems.append(f"[角色 {c['name']}] ref_image: {e}")
        if c.get("voice"):
            try:
                project.assets.url_of(c["voice"])
            except ValueError as e:
                problems.append(f"[角色 {c['name']}] voice: {e}")
        elif not c.get("voice_optional"):
            problems.append(f"[角色 {c['name']}] voice: 未配置（无专属音色文件，引用该角色的分镜无法生成；"
                            f"无对白角色可在 project.json 中设 \"voice_optional\": true 豁免）")
        for f in ("identity", "retention", "voice_desc", "gender"):
            if not c.get(f):
                problems.append(f"[角色 {c['name']}] {f}: 缺失")

    for key, s in project.scenes.items():
        try:
            project.assets.url_of(s.get("ref_image"))
        except ValueError as e:
            problems.append(f"[场景 {s['name']}] ref_image: {e}")

    sb_dir = project_dir / "storyboards"
    sbs = sorted(sb_dir.glob("ep*.json")) if sb_dir.exists() else []
    if not sbs:
        problems.append("无分镜文件（storyboards/ep*.json）")
    for sb_path in sbs:
        sb = load_json(sb_path)
        for seg in sb.get("segments", []):
            tag = f"[{sb_path.stem} seg{seg.get('seg')}]"
            try:
                project.char(seg.get("p1"), tag)
                if "p2" in seg:
                    project.char(seg["p2"], tag)
                project.scene(seg.get("scene"), tag)
                vkey = seg.get("voice", seg.get("p1"))
                v = project.char(vkey, tag)
                if not v.get("voice"):
                    problems.append(f"{tag} 角色 {v['name']} 无音色文件")
                render_prompt(project, seg)  # 完整渲染一遍，暴露模板/字段问题
            except ValueError as e:
                problems.append(f"{tag} {e}")

    if problems:
        print(f"发现 {len(problems)} 个问题：")
        for x in problems:
            print("  -", x)
        raise SystemExit(1)
    print(f"✓ 项目校验通过：角色 {len(project.characters)} / 场景 {len(project.scenes)} / "
          f"分镜 {len(sbs)} 集，全部资产可解析为 MinIO URL，模板渲染正常")


def cmd_payload(project_dir: Path, ep: int, seg=None, stdout=False):
    project = Project(project_dir)
    sb = project.storyboard(ep)
    segs = [s for s in sb["segments"] if seg is None or s["seg"] == seg]
    if not segs:
        die(f"未找到分镜：ep{ep}" + (f" seg{seg}" if seg else ""))
    out_dir = project_dir / "output"
    for s in segs:
        try:
            payload = build_payload(project, s, ep)
        except ValueError as e:
            die(f"ep{ep} seg{s['seg']}: {e}")
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        if stdout:
            print(f"===== ep{ep} seg{s['seg']} =====")
            print(text)
        else:
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / f"ep{ep}_seg{s['seg']}_payload.json"
            path.write_text(text + "\n", encoding="utf-8")
            print(f"✓ 生成 {path}")
    if not stdout:
        print(f"\n提交示例：python pipeline.py submit {project_dir} --ep {ep} --seg {segs[0]['seg']}")


def runninghub_api(url, body, key, timeout=90):
    import urllib.request

    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {key}",
                                          "User-Agent": "code-to-video-pipeline"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def is_concurrency_error(resp):
    """RunningHub 并发超限：errorCode 421，或错误信息含 并发/concurrency"""
    code = str(resp.get("errorCode", ""))
    msg = str(resp.get("errorMessage", "")).lower()
    return code == "421" or "并发" in msg or "concurren" in msg


def download_file(url, path: Path):
    """下载到 .part 临时文件，完整后原子改名，避免残留半截文件被误判为已下载。"""
    import urllib.request

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    with urllib.request.urlopen(url, timeout=300) as r, open(tmp, "wb") as f:
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
    tmp.replace(path)
    return path


def api_with_retry(url, body, key, attempts=3, base_delay=5):
    """网络抖动自动重试的 API 调用；轮询期间一次瞬时断网不应让整个批次崩溃丢任务。"""
    last = None
    for i in range(1, attempts + 1):
        try:
            return runninghub_api(url, body, key)
        except Exception as e:  # noqa: BLE001
            last = e
            if i < attempts:
                delay = base_delay * i
                print(f"    ⚠ 网络异常：{e}，{delay}s 后重试 {i}/{attempts - 1}")
                time.sleep(delay)
    raise last


def cmd_submit(project_dir: Path, ep: int, seg: int, wait=False, wait_timeout=900):
    key = os.environ.get("RUNNINGHUB_API_KEY")
    if not key:
        die("未设置环境变量 RUNNINGHUB_API_KEY")

    project = Project(project_dir)
    sb = project.storyboard(ep)
    seg_data = next((s for s in sb["segments"] if s["seg"] == seg), None)
    if not seg_data:
        die(f"未找到分镜：ep{ep} seg{seg}")
    try:
        payload = build_payload(project, seg_data, ep)
    except ValueError as e:
        die(f"ep{ep} seg{seg}: {e}")

    app_id = project.cfg["engine"]["app_id"]
    resp = runninghub_api(f"{RUNNINGHUB_BASE}/run/ai-app/{app_id}", payload, key)
    task_id = resp.get("taskId")
    if not task_id:
        die(f"提交失败：{json.dumps(resp, ensure_ascii=False)[:300]}")
    print(f"✓ 任务已提交 taskId={task_id}（App {app_id}，ep{ep} seg{seg}）")
    print(f"  手动查询：POST {RUNNINGHUB_BASE}/query {{\"taskId\": \"{task_id}\"}}")

    if wait:
        waited = 0
        while waited < wait_timeout:
            time.sleep(10)
            waited += 10
            q = api_with_retry(f"{RUNNINGHUB_BASE}/query", {"taskId": task_id}, key)
            st = (q.get("taskStatus") or q.get("status") or "?").upper()
            print(f"  [{waited}s] {st}")
            if st == "SUCCESS":
                for r in q.get("results") or []:
                    print("  ✓ 成片：", r.get("url"))
                    print("  ⚠️  COS 链接 24 小时失效，请及时下载")
                return
            if st == "FAILED":
                die(f"任务失败：{json.dumps(q, ensure_ascii=False)[:300]}")
        print(f"  ⚠ 等待超时（>{wait_timeout}s），taskId={task_id} 仍在运行，可稍后手动查询")


def cmd_batch(project_dir: Path, ep: int, seg=None, continue_on_error=False,
              task_timeout=900, retry_wait=30, max_retries=20, save_dir=None):
    """串行批量生成（单并发适配）：同一时刻至多一个在途任务。

    - 并发占用（421）自动等待重试
    - 提交成功立即落盘 SUBMITTED 状态；中断重跑优先续接轮询，绝不重复提交烧币
    - 成片 SUCCESS 但本地文件缺失时，用状态里记录的 URL 重新下载，不重新生成
    - 网络抖动自动重试，轮询期间异常不丢任务
    - 轮询超时保留 taskId（POLLING），重跑续接该任务继续等，不重新提交

    状态文件 projects/<项目>/output/ep<N>_batch_state.json 记录每段进度。
    """
    key = os.environ.get("RUNNINGHUB_API_KEY")
    if not key:
        die("未设置环境变量 RUNNINGHUB_API_KEY")

    project = Project(project_dir)
    sb = project.storyboard(ep)
    segs = [s for s in sb["segments"] if seg is None or s["seg"] == seg]
    if not segs:
        die(f"未找到分镜：ep{ep}" + (f" seg{seg}" if seg else ""))

    out_dir = project_dir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    state_path = out_dir / f"ep{ep}_batch_state.json"
    state = load_json(state_path) if state_path.exists() else {}
    save_dir = Path(save_dir) if save_dir else out_dir

    def save_state():
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def files_ok(st):
        return bool(st.get("files")) and all(Path(f).exists() for f in st["files"])

    def finished(s):
        st = state.get(str(s["seg"]), {})
        return st.get("status") == "SUCCESS" and files_ok(st)

    todo = [s for s in segs if not finished(s)]
    print(f"批次 ep{ep}：共 {len(segs)} 段，待处理 {len(todo)}，已完成跳过 {len(segs) - len(todo)}")
    print(f"单并发串行策略：421 占用每 {retry_wait}s 重试（最多 {max_retries} 次），"
          f"轮询 10s/次，单任务超时 {task_timeout}s")

    app_id = project.cfg["engine"]["app_id"]
    submit_url = f"{RUNNINGHUB_BASE}/run/ai-app/{app_id}"
    query_url = f"{RUNNINGHUB_BASE}/query"
    ok = fail = 0

    for idx, s in enumerate(todo, 1):
        tag = f"ep{ep} seg{s['seg']}"
        st_key = str(s["seg"])
        st = state.get(st_key, {})

        # ---- 断点续跑 A：曾 SUCCESS 但本地成片缺失 → 按记录 URL 重下，不重新生成 ----
        if st.get("status") == "SUCCESS" and st.get("urls") and not files_ok(st):
            print(f"  [{tag}] 曾生成成功但本地成片缺失，按原 URL 重新下载（不重新提交）")
            files = []
            for i, url in enumerate(st["urls"], 1):
                if not url:
                    continue
                suffix = f"_{i}" if len(st["urls"]) > 1 else ""
                path = save_dir / f"ep{ep}_seg{s['seg']}{suffix}.mp4"
                try:
                    download_file(url, path)
                    files.append(str(path))
                    print(f"    ✓ 重新下载 {path.name}（{path.stat().st_size // 1024} KB）")
                except Exception as e:  # noqa: BLE001
                    print(f"    ⚠ 重下失败（URL 可能已过 24h）：{e}")
            if files and all(Path(f).exists() for f in files):
                st["files"] = files
                save_state()
                ok += 1
                continue
            print("    ✗ 重下失败，转为重新生成")
            st = state[st_key] = {"status": "PENDING"}

        # ---- 断点续跑 B：在途任务（SUBMITTED/POLLING）→ 续接轮询，不重复提交 ----
        task_id = st.get("taskId") if st.get("status") in ("SUBMITTED", "POLLING") else None
        if task_id:
            print(f"  [{tag}]（{idx}/{len(todo)}）检测到在途任务 taskId={task_id}，续接轮询")

        if task_id is None:
            # ---- 组装 payload ----
            try:
                payload = build_payload(project, s, ep)
            except ValueError as e:
                fail += 1
                state[st_key] = {"status": "BUILD_FAILED", "error": str(e)}
                save_state()
                print(f"✗ [{tag}] payload 生成失败：{e}")
                if not continue_on_error:
                    die(f"{tag} 中止（--continue-on-error 可跳过继续）")
                continue

            # ---- 提交（421 等待重试；网络异常自动重试）----
            task_id = None
            err = ""
            for attempt in range(1, max_retries + 1):
                try:
                    resp = api_with_retry(submit_url, payload, key)
                except Exception as e:  # noqa: BLE001
                    err = f"网络异常：{e}"
                    print(f"  [{tag}] {err}，{retry_wait}s 后重试 {attempt}/{max_retries}")
                    time.sleep(retry_wait)
                    continue
                task_id = resp.get("taskId")
                if task_id:
                    break
                err = f"{resp.get('errorCode', '')} {resp.get('errorMessage', '')}".strip()
                if not is_concurrency_error(resp):
                    break
                print(f"  [{tag}] 并发占用（{err}），{retry_wait}s 后重试 {attempt}/{max_retries}")
                time.sleep(retry_wait)
            if not task_id:
                fail += 1
                state[st_key] = {"status": "SUBMIT_FAILED", "error": err}
                save_state()
                print(f"✗ [{tag}] 提交失败：{err}")
                if not continue_on_error:
                    die(f"{tag} 提交未成功，批次中止（--continue-on-error 可跳过继续）")
                continue
            print(f"  [{tag}]（{idx}/{len(todo)}）已提交 taskId={task_id}")
            state[st_key] = {"status": "SUBMITTED", "taskId": task_id}
            save_state()  # 立即落盘：此后任何中断，重跑都只会续接轮询，不会重复提交

        # ---- 轮询（网络异常不丢任务；超时保留 taskId 供重跑续接）----
        final = None
        start = time.time()
        while time.time() - start < task_timeout:
            time.sleep(10)
            try:
                q = api_with_retry(query_url, {"taskId": task_id}, key)
            except Exception as e:  # noqa: BLE001
                print(f"    ⚠ 查询异常：{e}（taskId={task_id} 已落盘，中断重跑可续接）")
                continue
            stt = (q.get("taskStatus") or q.get("status") or "?").upper()
            print(f"    [{int(time.time() - start)}s] {stt}")
            if stt in ("SUCCESS", "FAILED"):
                final = q
                break
            state[st_key] = {"status": "POLLING", "taskId": task_id}
            save_state()

        if final is None:
            fail += 1
            state[st_key] = {"status": "POLLING", "taskId": task_id}
            save_state()
            print(f"✗ [{tag}] 轮询超时（>{task_timeout}s），taskId={task_id} 仍在运行；"
                  f"重跑将续接该任务（不重复提交）")
            if not continue_on_error:
                die(f"{tag} 超时中止（--continue-on-error 可跳过继续）")
            time.sleep(10)
            continue

        # ---- 成功：下载成片（COS 链接 24h 失效，必须及时落地）----
        if (final.get("taskStatus") or final.get("status")).upper() == "SUCCESS":
            results = final.get("results") or []
            urls = [r.get("url") for r in results]
            files = []
            for i, r in enumerate(results, 1):
                url = r.get("url")
                if not url:
                    continue
                ext = (r.get("outputType") or "mp4").lstrip(".")
                suffix = f"_{i}" if len(results) > 1 else ""
                path = save_dir / f"ep{ep}_seg{s['seg']}{suffix}.{ext}"
                try:
                    download_file(url, path)
                    files.append(str(path))
                    print(f"    ✓ 已下载 {path.name}（{path.stat().st_size // 1024} KB）")
                except Exception as e:  # noqa: BLE001
                    print(f"    ⚠ 下载失败：{e}（URL 已存入状态，重跑自动续下，不重新生成）")
            coins = ((final.get("usage") or {}).get("consumeCoins")) or 0
            state[st_key] = {"status": "SUCCESS", "taskId": task_id, "files": files, "urls": urls,
                             "coins": float(coins)}
            save_state()
            if files_ok(state[st_key]):
                ok += 1
            else:
                fail += 1  # 任务成功但文件没落地：计为失败，重跑走 URL 重下分支
            time.sleep(10)  # 单并发：确认前一段彻底结束再提交下一段
            continue

        # ---- 失败 ----
        fail += 1
        err = f"{final.get('errorCode', '')} {final.get('errorMessage', '')}".strip()
        state[st_key] = {"status": "FAILED", "taskId": task_id, "error": err}
        save_state()
        print(f"✗ [{tag}] 任务失败：{err}")
        time.sleep(10)  # 单并发：留出间隔再提交下一段
        if not continue_on_error:
            die(f"{tag} 失败中止（--continue-on-error 可跳过继续）")

    print(f"\n批次结束：成功 {ok}，失败 {fail}；状态：{state_path}")
    total_coins = sum(float(v.get("coins") or 0) for v in state.values() if isinstance(v, dict))
    done = sum(1 for v in state.values() if isinstance(v, dict) and v.get("status") == "SUCCESS")
    print(f"💰 成本账单：本批累计消耗 {total_coins:g} 币"
          + (f"（均值 {total_coins / done:.1f} 币/段）" if done else "")
          + "；充值比例以 RunningHub 平台为准")
    if save_dir.resolve() != out_dir.resolve():
        print(f"成片目录 {save_dir}：建议运行 scripts/minio_sync.py scan+sync 将成片纳入资源清单")
    if fail:
        raise SystemExit(1)



# ==================== render：成片合成 ====================

def _fmt_srt(t):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _probe(path, ffprobe="ffprobe"):
    """返回 (宽, 高, 有无音轨, 时长秒)"""
    import subprocess

    def run(args):
        r = subprocess.run(args, capture_output=True, text=True)
        return r.stdout.strip()
    wh = run([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
              "stream=width,height", "-of", "csv=p=0", str(path)]).split(",")
    w, h = (int(wh[0]), int(wh[1])) if len(wh) == 2 and wh[0].isdigit() else (1920, 1080)
    has_audio = bool(run([ffprobe, "-v", "error", "-select_streams", "a",
                          "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(path)]))
    dur = run([ffprobe, "-v", "error", "-show_entries", "format=duration",
               "-of", "csv=p=0", str(path)])
    try:
        dur = float(dur)
    except ValueError:
        dur = None
    return w, h, has_audio, dur


def find_clip(project: Project, ep: int, seg: int, clips_dir=None):
    """段视频查找顺序：--clips-dir（batch 命名）→ output/ → source_root 手工命名（EP{ep}段{seg}_*.mp4）"""
    candidates = []
    if clips_dir:
        candidates.append(Path(clips_dir) / f"ep{ep}_seg{seg}.mp4")
    candidates.append(project.dir / "output" / f"ep{ep}_seg{seg}.mp4")
    src_root = project.cfg.get("source_root")
    if src_root:
        for base in ("videos/songkou_drama", "videos"):
            candidates.extend(sorted((Path(src_root) / base).glob(f"EP{ep}段{seg}_*.mp4")))
    for c in candidates:
        if c.exists():
            return c
    return None


def gen_srt(project: Project, segs, durations, out_path: Path, initial_offset=0.0):
    """由分镜台词生成集级 SRT；durations 为各段实际时长（秒），字幕偏移按实际时长累计。"""
    idx, lines, offset = 0, [], initial_offset
    for seg, dur in zip(segs, durations):
        for shot in seg.get("shots", []):
            m = re.match(r"(\d+)s-(\d+)s", str(shot.get("time", "")))
            dlg = shot.get("dialogue")
            if not m or not dlg:
                continue
            a, b = float(m.group(1)), float(m.group(2))
            b = min(b, dur)
            idx += 1
            lines.append(f"{idx}\n{_fmt_srt(offset + a)} --> {_fmt_srt(offset + b)}\n{dlg}\n")
        offset += dur
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return idx


def _ensure_audio_track(src: Path, dst: Path, ffmpeg="ffmpeg"):
    """无音轨段补静音轨（concat 音频要求每段都有音轨）。"""
    import subprocess

    subprocess.run([ffmpeg, "-y", "-i", str(src), "-f", "lavfi",
                    "-i", "anullsrc=r=44100:cl=stereo", "-shortest",
                    "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac",
                    str(dst)], check=True, capture_output=True)


def _make_title_clip(text, w, h, seconds, dst: Path, ffmpeg="ffmpeg"):
    """黑底白字片头（微软雅黑，淡入淡出，含静音轨）。"""
    import subprocess

    font = "C\\:/Windows/Fonts/msyh.ttc"
    fontsize = max(28, h // 12)
    vf = (f"drawtext=fontfile='{font}':text='{text}':fontcolor=white:fontsize={fontsize}:"
          f"x=(w-text_w)/2:y=(h-text_h)/2,fade=t=in:st=0:d=0.5,fade=t=out:st={seconds - 0.5}:d=0.5")
    subprocess.run([ffmpeg, "-y", "-f", "lavfi",
                    "-i", f"color=c=black:s={w}x{h}:d={seconds}:r=24",
                    "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                    "-t", str(seconds), "-vf", vf, "-c:v", "libx264", "-crf", "20",
                    "-c:a", "aac", "-shortest", str(dst)], check=True, capture_output=True)


def cmd_render(project_dir: Path, ep: int, clips_dir=None, bgm=None, title=None,
               out=None, keep_srt=False):
    """分镜 + 段视频 → 成片：拼接 + 台词字幕烧录 + BGM 混音 + 可选片头。"""
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        import glob
        hits = (glob.glob("F:/Downloads/ffmpeg*/bin/ffmpeg.exe")
                + glob.glob("C:/ffmpeg/bin/ffmpeg.exe"))
        if not hits:
            die("未找到 ffmpeg：请安装或将其 bin 目录加入 PATH（https://ffmpeg.org）")
        ffmpeg = hits[0]
    project = Project(project_dir)
    sb = project.storyboard(ep)
    segs = sorted(sb["segments"], key=lambda s: s["seg"])

    clips = []
    for s in segs:
        c = find_clip(project, ep, s["seg"], clips_dir)
        if not c:
            die(f"ep{ep} seg{s['seg']} 段视频缺失（先运行 batch，或用 --clips-dir 指定目录；"
                f"手工成片命名 EP{ep}段{s['seg']}_*.mp4 会被自动识别）")
        clips.append(c)

    out_dir = project_dir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("探测段视频…")
    ffprobe = str(Path(ffmpeg).with_name(Path(ffmpeg).name.replace("ffmpeg", "ffprobe")))
    probe = [_probe(c, ffprobe) for c in clips]
    w = max(p[0] for p in probe)
    h = max(p[1] for p in probe)
    w, h = w - w % 2, h - h % 2
    fixed = []
    for c, (_, _, has_a, _) in zip(clips, probe):
        if has_a:
            fixed.append(c)
        else:
            dst = out_dir / f"_fix_{c.stem}.mp4"
            _ensure_audio_track(c, dst, ffmpeg)
            fixed.append(dst)
            print(f"  段 {c.name} 无音轨 → 已补静音")
    durations = [p[3] or float(s.get("duration", 15)) for p, s in zip(probe, segs)]
    total = sum(durations)

    srt_path = out_dir / f"ep{ep}.srt"
    n = gen_srt(project, segs, durations, srt_path, initial_offset=2.5 if title else 0.0)
    print(f"字幕：{n} 条台词 → {srt_path.name}（总时长 {total:.1f}s）")

    inputs = []
    if title:
        tpath = out_dir / "_title_clip.mp4"
        _make_title_clip(title, w, h, 2.5, tpath, ffmpeg)
        inputs.append(tpath)
        durations = [2.5] + durations
        total += 2.5
        print(f"片头：{title}（2.5s）")
    inputs += fixed
    inputs = [Path(c).resolve() for c in inputs]  # 主命令 cwd=out_dir，输入必须绝对路径

    parts, vlabels, alabels = [], [], []
    for i in range(len(inputs)):
        parts.append(f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                     f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24[v{i}]")
        parts.append(f"[{i}:a]aformat=sample_rates=44100:channel_layouts=stereo[a{i}]")
        vlabels.append(f"[v{i}]")
        alabels.append(f"[a{i}]")
    parts.append("".join(vlabels) + f"concat=n={len(inputs)}:v=1:a=0[cv]")
    srt_arg = srt_path.name  # cwd=out_dir，规避 Windows 盘符转义
    style = ("FontName=Microsoft YaHei,FontSize=11,PrimaryColour=&H00FFFFFF,"
             "OutlineColour=&H00000000,BorderStyle=1,Outline=1,Shadow=1,MarginV=22")
    parts.append(f"[cv]subtitles={srt_arg}:force_style='{style}'[fv]")
    parts.append("".join(alabels) + f"concat=n={len(inputs)}:v=0:a=1[ca]")
    cmd = ["ffmpeg", "-y"]
    for c in inputs:
        cmd += ["-i", str(c)]
    if bgm:
        cmd += ["-stream_loop", "-1", "-i", str(bgm)]
        bi = len(inputs)
        parts.append(f"[{bi}:a]volume=0.22,atrim=0:{total:.2f}[bga]")
        parts.append("[ca][bga]amix=inputs=2:duration=first:normalize=0[fa]")
        print(f"BGM：{Path(bgm).name}（音量 22%，混音至 {total:.1f}s）")
    else:
        parts.append("[ca]anull[fa]")
    fc = ";".join(parts)

    out_path = Path(out).resolve() if out else (out_dir / f"ep{ep}_final.mp4").resolve()
    cmd += ["-filter_complex", fc, "-map", "[fv]", "-map", "[fa]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
            "-t", f"{total:.2f}", str(out_path)]
    print(f"合成中（{len(inputs)} 段 → {out_path.name}）…")
    r = subprocess.run(cmd, cwd=str(out_dir), capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-1500:])
        die("ffmpeg 合成失败")
    size = out_path.stat().st_size / 1024 / 1024
    print(f"✓ 成片完成：{out_path}（{size:.1f} MB，{total:.1f}s，{w}x{h}）")
    print(f"  字幕文件：{srt_path}（如需外挂字幕可用）")


# ==================== init-project：新剧脚手架 ====================

_INIT_PROJECT_JSON = {
    "name": "TEMPLATE_NAME",
    "title": "TEMPLATE_TITLE",
    "style_qualifier": "（一句话风格定位，如：XX古镇文化宣传）",
    "engine": {
        "provider": "runninghub",
        "app_id": "2090774740146413570",
        "instance_type": "TEMPLATE_INSTANCE",
        "defaults": {
            "duration": 15,
            "aspect_ratio": "16:9 (Widescreen)",
            "megapixels": "0.7000000000000001",
            "use_personal_queue": "false",
            "aspect_ratio_fielddata": None,
        },
    },
    "style": {
        "visual": "（detailed_description 开头的画面风格段落）",
        "retention": "（风格不变量：retention_analysis 的风格行，末尾不带句号）",
    },
    "voice_audio_default": True,
    "prompt_templates": {"single": "prompt_template_single.txt",
                         "dual": "prompt_template_dual.txt"},
    "characters": {},
    "scenes": {},
}

_INIT_STORYBOARD_README = """# 分镜目录

每集一个文件：`ep1.json`、`ep2.json`…（`--ep N` 寻址）。

```json
{
  "project": "TEMPLATE_NAME",
  "episode": 1,
  "title": "本集标题",
  "segments": [
    {
      "seg": 1,
      "p1": "角色key（必填）",
      "p2": "第二角色key（可选，双角色对话段）",
      "scene": "场景key（必填）",
      "voice": "音色角色key（缺省用 p1）",
      "duration": 15,
      "summary": "本段一句话概括",
      "shots": [
        { "time": "0s-7s", "desc": "镜头描述", "dialogue": "台词（可选）" },
        { "time": "7s-15s", "desc": "镜头描述" }
      ],
      "soundscape": "环境声",
      "music": "配乐"
    }
  ]
}
```

> **台词量经验**：15 秒段建议台词 ≥2 句（约 30~40 字）铺满时段，台词过少模型会为填满音轨而重复念白。

分段级覆盖字段（覆盖 project.json 默认）：`p1_identity` `p2_identity` `p1_retention` `p2_retention`
`scene_desc` `scene_anchor` `scene_extra` `scene_retention` `style_retention` `drift_clause` `voice_audio`
"""

_INIT_CHECKLIST = """## 新剧开工清单

按顺序准备资产，每完成一项运行 `python pipeline.py check projects/{name}` 查看缺口：

### 1. 项目配置（project.json）
- [ ] name / title / style_qualifier（一句话风格定位）
- [ ] style.visual（画面风格段落）/ style.retention（风格不变量）
- [ ] engine.instance_type（plus=更快更好 / default）
- [ ] engine.dual_layout（可选：scene_at_166=双角色时 P2 场景/P3 第二角色；缺省 P2 第二角色/P3 场景）
- [ ] voice_audio_default（提示词是否写音色参考行）
- [ ] source_root（可选：本地资源根目录，render 会自动找手工成片 EP{N}段{M}_*.mp4）

### 2. 角色库 characters（每个角色）
- [ ] name / gender / role（提示词中的角色称谓，如"女性角色"）
- [ ] identity（外形设定：年龄/发型/服装/气质/道具）
- [ ] ref_image（三视图/立绘 —— 可用 `pipeline.py asset --character <key>` 自动生成）
- [ ] voice（音色文件 —— RunningHub 声音设计工作流生成；无对白角色设 "voice_optional": true）
- [ ] retention（人物不变量）/ voice_desc（音色描述）

### 3. 场景库 scenes（每个场景）
- [ ] name / desc（空间描述）/ anchor（机位参照要点）/ retention（场景不变量）
- [ ] extra（风格化元素，如仙侠化特效；写实项目留空）
- [ ] ref_image（场景参照图 —— 可用 `pipeline.py asset --scene <key>` 自动生成）

### 4. 分镜 storyboards/
- [ ] 每集一个 epN.json（schema 见 storyboards/README.md）
- [ ] `python pipeline.py check projects/{name}` 全绿

### 5. 生成与成片
- [ ] `python pipeline.py payload projects/{name} --ep 1` 生成 payload 检查
- [ ] `python pipeline.py batch projects/{name} --ep 1` 串行出段视频（自动账单）
- [ ] `python pipeline.py render projects/{name} --ep 1 --title "第1集"` 合成成片
"""


def cmd_init_project(project_dir: Path, title=None, layout=None, instance="plus",
                     voice_audio=True, source_root=None):
    """创建新剧项目骨架：project.json + 通用模板 + 分镜说明 + 开工清单。"""
    if project_dir.exists() and any(project_dir.iterdir()):
        die(f"目录已存在且非空：{project_dir}")
    name = project_dir.name
    cfg = json.loads(json.dumps(_INIT_PROJECT_JSON))
    cfg["name"] = name
    cfg["title"] = title or name
    cfg["engine"]["instance_type"] = instance
    cfg["engine"]["defaults"]["aspect_ratio_fielddata"] = json.load(open(
        ROOT / "projects" / "songkou" / "project.json", encoding="utf-8")
    )["engine"]["defaults"]["aspect_ratio_fielddata"]
    if layout:
        cfg["engine"]["dual_layout"] = layout
    if not voice_audio:
        cfg["voice_audio_default"] = False
    if source_root:
        cfg["source_root"] = source_root

    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "project.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for t in ("prompt_template_single.txt", "prompt_template_dual.txt"):
        shutil.copy2(ROOT / "projects" / "songkou" / t, project_dir / t)
    sb_dir = project_dir / "storyboards"
    sb_dir.mkdir(exist_ok=True)
    (sb_dir / "README.md").write_text(
        _INIT_STORYBOARD_README.replace("TEMPLATE_NAME", name), encoding="utf-8")
    (project_dir / "README.md").write_text(
        f"# {cfg['title']}（{name}）\n\n" + _INIT_CHECKLIST.replace("{name}", name),
        encoding="utf-8")
    print(f"✓ 项目骨架已创建：{project_dir}")
    print("  - project.json（引擎默认已配好，风格/角色/场景待填）")
    print("  - prompt_template_single.txt / prompt_template_dual.txt（通用 6 段式模板）")
    print("  - storyboards/README.md（分镜 schema）")
    print("  - README.md（开工清单，照着做即可）")
    print(f"\n下一步：编辑 project.json 填风格与角色库 → pipeline.py check projects/{name} 查缺口")


# ==================== asset：素材自动生成入库 ====================

def _minio_client_for_upload(cfg):
    """优先本机回环（MinIO 在本机时绕开 NAT 回环，速度快）。"""
    from minio import Minio
    endpoint = cfg["endpoint"]
    try:
        import urllib.request as _u
        with _u.urlopen("http://127.0.0.1:9000/minio/health/live", timeout=3):
            _, _, port = endpoint.partition(":")
            endpoint = f"127.0.0.1:{port or '9000'}"
    except Exception:
        pass
    return Minio(endpoint, access_key=cfg["access_key"], secret_key=cfg["secret_key"],
                 secure=cfg.get("secure", False))


def _register_asset(rel_path: str, local: Path, content_type="image/png"):
    """入库：FS 直拷（MinIO 数据目录在本机）或 SDK 上传 → 更新资源清单 → 返回公开 URL。"""
    import shutil as _sh
    from urllib.parse import quote
    from datetime import datetime

    cfg = json.load(open(ROOT / "scripts" / "minio_config.json", encoding="utf-8"))
    mpath = ROOT / "resources" / "minio-manifest.json"
    m = json.load(open(mpath, encoding="utf-8"))
    key = f"{cfg['prefix']}/{rel_path}"
    bucket_dir = Path(cfg.get("fs_root", "F:/buket")) / cfg["bucket"]
    dst = bucket_dir / key
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        _sh.copy2(local, dst)
    except OSError:
        c = _minio_client_for_upload(cfg)
        c.fput_object(cfg["bucket"], key, str(local), content_type=content_type)
    entry = {"path": rel_path, "type": "image", "name": local.name,
             "size": local.stat().st_size, "object_key": key,
             "url": f"{cfg['public_base_url']}/{cfg['bucket']}/{quote(key, safe='/')}"}
    m["resources"] = [e for e in m["resources"] if e["path"] != rel_path] + [entry]
    m["resources"].sort(key=lambda e: e["path"])
    m["total"] = len(m["resources"])
    m["total_size"] = sum(e["size"] for e in m["resources"])
    m["updated"] = datetime.now().astimezone().isoformat(timespec="seconds")
    json.dump(m, open(mpath, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    bdir = bucket_dir / "resources"
    bdir.mkdir(parents=True, exist_ok=True)
    _sh.copy2(mpath, bdir / "minio-manifest.json")
    return entry["url"]


def _generate_image(prompt, app_id, out_path: Path, node="17", field_name="prompt",
                    extra_nodes=None, instance="default", timeout_s=600):
    """RunningHub 图生成（Z-image node17/prompt / KREA node160/text + 104/image）。"""
    key = os.environ.get("RUNNINGHUB_API_KEY")
    if not key:
        die("未设置环境变量 RUNNINGHUB_API_KEY")
    nodes = [{"nodeId": node, "fieldName": field_name, "fieldValue": prompt}] + (extra_nodes or [])
    resp = runninghub_api(f"{RUNNINGHUB_BASE}/run/ai-app/{app_id}",
                          {"nodeInfoList": nodes, "instanceType": instance}, key)
    task_id = resp.get("taskId")
    if not task_id:
        die(f"图生成提交失败：{json.dumps(resp, ensure_ascii=False)[:300]}")
    print(f"  已提交 taskId={task_id}")
    start = time.time()
    while time.time() - start < timeout_s:
        time.sleep(10)
        q = runninghub_api(f"{RUNNINGHUB_BASE}/query", {"taskId": task_id}, key)
        st = (q.get("taskStatus") or q.get("status") or "?").upper()
        print(f"    [{int(time.time() - start)}s] {st}")
        if st == "SUCCESS":
            results = q.get("results") or []
            if not results or not results[0].get("url"):
                die(f"任务成功但无结果：{json.dumps(q, ensure_ascii=False)[:200]}")
            coins = (q.get("usage") or {}).get("consumeCoins") or 0
            print(f"    消耗 {coins} 币")
            download_file(results[0]["url"], out_path)
            return out_path
        if st == "FAILED":
            die(f"图生成失败：{json.dumps(q, ensure_ascii=False)[:300]}")
    die(f"图生成轮询超时（taskId={task_id}）")


def cmd_asset(project_dir: Path, character=None, scene=None, three_view=False,
              ref_url=None, dry_run=False):
    """自动生成角色立绘/三视图或场景图 → 入 MinIO + 清单 → 回写 project.json。"""
    project = Project(project_dir)
    out_dir = project_dir / "output" / "assets"
    ZIMAGE, KREA = "2088920592350277634", "2088926295186034689"

    if character:
        c = project.char(character, "asset")
        rel = f"images/generated/{project.cfg['name']}/{character}.png"
        if three_view:
            if not ref_url:
                die("三视图基于已生成立绘做图生图：请传 --ref-url <立绘URL>（先不带 --three-view 跑一次）")
            prompt = (f"生成{c['name']}的标准角色三视图 turnaround sheet：同一角色同一服装的正面、侧面、"
                      f"背面三个全身视角并排，纯白背景，全身完整可见，比例一致，高清细节。"
                      f"角色设定：{c['identity']}")
            app, node, extra = KREA, "160", [
                {"nodeId": "104", "fieldName": "image", "fieldValue": ref_url}]
        else:
            xianxia = project.cfg["name"] == "yaolu"
            prompt = (f"{c['identity']}，全身角色立绘，正面站姿，纯白简洁背景，"
                      f"{'3D CG渲染，国漫角色设定集风格' if xianxia else '超写实照片级质感'}，高清细节，8K")
            app, node, extra = ZIMAGE, "17", None
    elif scene:
        s = project.scene(scene, "asset")
        rel = f"images/generated/{project.cfg['name']}/scene_{scene}.png"
        prompt = f"{s['desc']}，{s.get('extra', '')}电影感构图，空间纵深感，高清细节，8K"
        app, node, extra = ZIMAGE, "17", None
    else:
        die("请指定 --character <key> 或 --scene <key>（--three-view 需配合 --ref-url）")

    print(f"目标：{rel}")
    print(f"提示词：{prompt[:120]}{'…' if len(prompt) > 120 else ''}")
    if dry_run:
        print("(dry-run，未提交)")
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    local = out_dir / Path(rel).name
    _generate_image(prompt, app, local, node=node,
                    field_name="text" if app == KREA else "prompt",
                    extra_nodes=extra,
                    instance=project.cfg["engine"].get("instance_type", "default")
                    if app == KREA else "default")
    url = _register_asset(rel, local)

    cfgp = project_dir / "project.json"
    cfg = json.load(open(cfgp, encoding="utf-8"))
    if character:
        cfg["characters"][character]["ref_image"] = rel
    else:
        cfg["scenes"][scene]["ref_image"] = rel
    json.dump(cfg, open(cfgp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"✓ 已入库：{url}")
    print(f"✓ project.json 已回写 ref_image → {rel}")
    if character and not three_view:
        print(f"  下一步：--three-view --ref-url {url} 生成三视图")



def main():
    ap = argparse.ArgumentParser(
        description="code-to-video 制作流水线：分镜 + 项目配置 + 提示词模板 → RunningHub payload")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("check", help="校验项目配置与分镜")
    p.add_argument("project", help="项目目录，如 projects/songkou")

    p = sub.add_parser("payload", help="生成 payload（不提交、不消耗币）")
    p.add_argument("project", help="项目目录")
    p.add_argument("--ep", type=int, required=True, help="集数")
    p.add_argument("--seg", type=int, help="段号（缺省生成整集）")
    p.add_argument("--stdout", action="store_true", help="打印到终端而非写文件")

    p = sub.add_parser("submit", help="生成并提交 RunningHub 任务（消耗币）")
    p.add_argument("project", help="项目目录")
    p.add_argument("--ep", type=int, required=True, help="集数")
    p.add_argument("--seg", type=int, required=True, help="段号")
    p.add_argument("--wait", action="store_true", help="轮询直到任务完成")
    p.add_argument("--wait-timeout", type=int, default=900, help="--wait 轮询超时秒数，默认 900")

    p = sub.add_parser("batch", help="串行批量生成（单并发适配）：421等待+断点续接不重复提交+URL重下")
    p.add_argument("project", help="项目目录")
    p.add_argument("--ep", type=int, required=True, help="集数")
    p.add_argument("--seg", type=int, help="只跑指定段（缺省整集）")
    p.add_argument("--continue-on-error", action="store_true", help="失败/超时后继续下一段")
    p.add_argument("--task-timeout", type=int, default=900, help="单任务轮询超时秒数，默认 900")
    p.add_argument("--retry-wait", type=int, default=30, help="并发占用重试间隔秒数，默认 30")
    p.add_argument("--max-retries", type=int, default=20, help="并发占用最大重试次数，默认 20")
    p.add_argument("--save-dir", help="成片下载目录（缺省 projects/<项目>/output/）")

    p = sub.add_parser("render", help="段视频 → 成片：拼接+台词字幕+BGM混音+片头")
    p.add_argument("project", help="项目目录")
    p.add_argument("--ep", type=int, required=True, help="集数")
    p.add_argument("--clips-dir", help="段视频目录（缺省依次找 output/ 与 source_root 手工成片）")
    p.add_argument("--bgm", help="BGM 音频文件路径（可选）")
    p.add_argument("--title", help="片头标题文字（可选，2.5s 黑底片头）")
    p.add_argument("--out", help="输出路径（缺省 projects/<项目>/output/epN_final.mp4）")
    p.add_argument("--keep-srt", action="store_true", help="保留生成的 SRT 字幕文件")

    p = sub.add_parser("init-project", help="创建新剧项目骨架（配置+模板+分镜说明+开工清单）")
    p.add_argument("project", help="新项目目录，如 projects/ancient_town_x")
    p.add_argument("--title", help="剧名（缺省用目录名）")
    p.add_argument("--layout", choices=["scene_at_166"], help="双角色节点布局（缺省嵩口式）")
    p.add_argument("--instance", default="plus", help="RunningHub 实例类型，默认 plus")
    p.add_argument("--no-voice-audio", dest="voice_audio", action="store_false",
                   help="提示词默认不写音色参考行（如镇妖录式）")
    p.add_argument("--source-root", help="本地资源根目录（render 自动找手工成片 EP{N}段{M}_*.mp4）")

    p = sub.add_parser("asset", help="角色/场景图自动生成 → MinIO 入库 → 回写配置")
    p.add_argument("project", help="项目目录")
    p.add_argument("--character", help="角色 key（生成角色立绘）")
    p.add_argument("--scene", help="场景 key（生成场景图）")
    p.add_argument("--three-view", action="store_true",
                   help="基于 --ref-url 立绘生成三视图（KREA 图生图）")
    p.add_argument("--ref-url", help="立绘图片 URL（--three-view 必需）")
    p.add_argument("--dry-run", action="store_true", help="只打印提示词，不提交")

    args = ap.parse_args()
    project_dir = Path(args.project)
    if args.cmd != "init-project" and not project_dir.exists():
        die(f"项目目录不存在：{project_dir}")

    if args.cmd == "check":
        cmd_check(project_dir)
    elif args.cmd == "payload":
        cmd_payload(project_dir, args.ep, args.seg, args.stdout)
    elif args.cmd == "submit":
        cmd_submit(project_dir, args.ep, args.seg, args.wait, args.wait_timeout)
    elif args.cmd == "batch":
        cmd_batch(project_dir, args.ep, args.seg, args.continue_on_error,
                  args.task_timeout, args.retry_wait, args.max_retries, args.save_dir)
    elif args.cmd == "render":
        cmd_render(project_dir, args.ep, args.clips_dir, args.bgm, args.title,
                   args.out, args.keep_srt)
    elif args.cmd == "init-project":
        cmd_init_project(project_dir, args.title, args.layout, args.instance,
                         args.voice_audio, args.source_root)
    elif args.cmd == "asset":
        cmd_asset(project_dir, args.character, args.scene, args.three_view,
                  args.ref_url, args.dry_run)


if __name__ == "__main__":
    main()
