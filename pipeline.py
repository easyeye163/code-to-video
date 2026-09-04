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

资产解析：角色图/场景图/音色在配置中只写仓库相对路径，由 resources/minio-manifest.json
自动解析为 MinIO URL。清单缺失时先运行：
  python scripts/minio_sync.py scan <资源根目录> && python scripts/minio_sync.py sync <资源根目录>
"""

from __future__ import annotations

import argparse
import json
import os
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
    scene = project.scene(seg.get("scene"), where)
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
        "scene_retention": seg.get("scene_retention", scene["retention"]),
        "voice_desc": voice["voice_desc"],
        "duration": seg.get("duration", defaults["duration"]),
        "style_qualifier": project.cfg["style_qualifier"],
        "style_visual": project.cfg["style"]["visual"],
        "style_retention": project.cfg["style"]["retention"],
        "summary": seg["summary"],
        "shots": format_shots(seg["shots"]),
        "soundscape": seg["soundscape"],
        "music": seg["music"],
    }

    p2 = None
    if "p2" in seg:
        p2 = project.char(seg["p2"], where)
        ctx["p2_gender"] = p2["gender"]
        ctx["p2_identity"] = p2["identity"]
        ctx["p2_retention"] = p2["retention"]
        ctx["voice_subject"] = "1" if voice_key == seg["p1"] else "2"
        mode = "dual"
    else:
        mode = "single"

    try:
        prompt = project.templates[mode].format(**ctx)
    except KeyError as e:
        die(f"{mode} 模板占位符缺少数据：{e}")
    return prompt, p1, p2, scene, voice


def build_payload(project: Project, seg: dict, ep: int):
    prompt, p1, p2, scene, voice = render_prompt(project, seg)
    defaults = project.cfg["engine"]["defaults"]
    p1_url = project.assets.url_of(p1["ref_image"])
    scene_url = project.assets.url_of(scene["ref_image"])
    voice_url = project.assets.url_of(voice["voice"])

    if p2 is not None:  # 双角色模式：P2=第二角色，P3=场景
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
        else:
            problems.append(f"[角色 {c['name']}] voice: 未配置（无专属音色文件，引用该角色的分镜无法生成）")
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


def cmd_submit(project_dir: Path, ep: int, seg: int, wait=False):
    import urllib.request

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

    def api(url, body):
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {key}",
                                              "User-Agent": "code-to-video-pipeline"})
        return json.loads(urllib.request.urlopen(req, timeout=90).read())

    resp = api(f"{RUNNINGHUB_BASE}/run/ai-app/{app_id}", payload)
    task_id = resp.get("taskId")
    if not task_id:
        die(f"提交失败：{json.dumps(resp, ensure_ascii=False)[:300]}")
    print(f"✓ 任务已提交 taskId={task_id}（App {app_id}，ep{ep} seg{seg}）")
    print(f"  手动查询：POST {RUNNINGHUB_BASE}/query {{\"taskId\": \"{task_id}\"}}")

    if wait:
        for i in range(1, 31):
            time.sleep(10)
            q = api(f"{RUNNINGHUB_BASE}/query", {"taskId": task_id})
            st = (q.get("taskStatus") or q.get("status") or "?").upper()
            print(f"  [{i * 10}s] {st}")
            if st == "SUCCESS":
                for r in q.get("results") or []:
                    print("  ✓ 成片：", r.get("url"))
                    print("  ⚠️  COS 链接 24 小时失效，请及时下载")
                return
            if st == "FAILED":
                die(f"任务失败：{json.dumps(q, ensure_ascii=False)[:300]}")


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

    args = ap.parse_args()
    project_dir = Path(args.project)
    if not project_dir.exists():
        die(f"项目目录不存在：{project_dir}")

    if args.cmd == "check":
        cmd_check(project_dir)
    elif args.cmd == "payload":
        cmd_payload(project_dir, args.ep, args.seg, args.stdout)
    elif args.cmd == "submit":
        cmd_submit(project_dir, args.ep, args.seg, args.wait)


if __name__ == "__main__":
    main()
