#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
code-to-video · MinIO 资源同步工具
==================================

本仓库只保存代码与知识库；所有媒体资源（图片/音频/视频）统一存放在
MinIO 对象存储中，以 URL 链接形式引用。

资源总索引：resources/minio-manifest.json
（记录每个资源的相对路径、类型、大小、MinIO 对象键与访问链接）

用法
----
1) 扫描资源根目录，生成/刷新清单（不上传，无需第三方依赖）：
   python scripts/minio_sync.py scan <资源根目录>
   例：python scripts/minio_sync.py scan D:/h3-video-coding-main

2) 上传资源到 MinIO，并生成公开访问链接：
   python scripts/minio_sync.py sync <资源根目录> [--rescan]

3) 私有桶改用临时签名链接（默认 7 天有效）：
   python scripts/minio_sync.py presign [--expire-days 7]

4) 校验桶内对象与清单是否一致：
   python scripts/minio_sync.py check

5) 查询某个资源的访问链接：
   python scripts/minio_sync.py url images/songkou_characters/lin_xiaoxi_three_view.png

配置
----
优先级：环境变量 > scripts/minio_config.json > 默认值
（配置模板见 scripts/minio_config.example.json；真实配置已被 .gitignore 排除）

  MINIO_ENDPOINT     MinIO 地址（host:port，不含协议），如 minio.example.com:9000
  MINIO_ACCESS_KEY   访问密钥
  MINIO_SECRET_KEY   私密密钥
  MINIO_BUCKET       桶名，默认 code-to-video
  MINIO_SECURE       是否 HTTPS，默认 true
  MINIO_PUBLIC_URL   公网访问基址，如 https://minio.example.com:9000
  MINIO_PREFIX       对象键前缀，默认 code-to-video
  MINIO_SET_POLICY   sync 时是否将桶设为公开只读，默认 true

依赖：pip install -r scripts/requirements.txt
（仅 scan / url 子命令为标准库实现，无需安装任何依赖）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "scripts" / "minio_config.json"
MANIFEST_PATH = REPO_ROOT / "resources" / "minio-manifest.json"

IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "svg", "ico",
              "psd", "tif", "tiff", "heic", "avif"}
VIDEO_EXTS = {"mp4", "mov", "webm", "avi", "mkv", "wmv", "m4v",
              "mpg", "mpeg", "flv", "3gp", "ts"}
AUDIO_EXTS = {"flac", "mp3", "wav", "aac", "ogg", "m4a",
              "wma", "aiff", "opus", "mid", "midi"}

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".workbuddy", ".venv", "venv"}

DEFAULTS = {
    "endpoint": "",
    "access_key": "",
    "secret_key": "",
    "bucket": "code-to-video",
    "secure": True,
    "public_base_url": "",
    "prefix": "code-to-video",
    "set_public_policy": True,
}

ENV_MAP = {
    "endpoint": "MINIO_ENDPOINT",
    "access_key": "MINIO_ACCESS_KEY",
    "secret_key": "MINIO_SECRET_KEY",
    "bucket": "MINIO_BUCKET",
    "secure": "MINIO_SECURE",
    "public_base_url": "MINIO_PUBLIC_URL",
    "prefix": "MINIO_PREFIX",
    "set_public_policy": "MINIO_SET_POLICY",
}

PUBLIC_POLICY = """{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"AWS": ["*"]},
    "Action": ["s3:GetObject"],
    "Resource": ["arn:aws:s3:::%s/*"]
  }]
}"""


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8-sig") as f:
            user = json.load(f)
        cfg.update({k: v for k, v in user.items() if k in cfg})
    for key, env in ENV_MAP.items():
        raw = os.environ.get(env)
        if raw is None or raw == "":
            continue
        if key in ("secure", "set_public_policy"):
            cfg[key] = raw.strip().lower() in ("1", "true", "yes", "on")
        else:
            cfg[key] = raw
    return cfg


def normalize_path(p: str) -> Path:
    """兼容 Git Bash 传入的 /d/... 形式的路径。"""
    s = str(p)
    if len(s) >= 3 and s[0] == "/" and s[1].isalpha() and s[2] == "/":
        s = s[1].upper() + ":" + s[2:]
    return Path(s)


def media_type(name: str):
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    return None


def object_key(cfg: dict, rel_posix: str) -> str:
    prefix = cfg["prefix"].strip("/")
    return f"{prefix}/{rel_posix}" if prefix else rel_posix


def public_url(cfg: dict, key: str):
    base = cfg["public_base_url"].rstrip("/")
    if not base:
        return None
    return f"{base}/{cfg['bucket']}/{quote(key, safe='/')}"


def load_manifest():
    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH, encoding="utf-8") as f:
            return json.load(f)
    return None


def save_manifest(m: dict):
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)


def cmd_scan(root: Path, cfg: dict):
    """扫描资源根目录中的媒体文件，生成/刷新 resources/minio-manifest.json。"""
    old = {}
    prev = load_manifest()
    if prev:
        for e in prev.get("resources", []):
            old[(e["path"], e.get("size"))] = e.get("url")

    entries = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in sorted(filenames):
            mtype = media_type(fn)
            if not mtype:
                continue
            fp = Path(dirpath) / fn
            rel = fp.relative_to(root).as_posix()
            size = fp.stat().st_size
            url = old.get((rel, size)) or None
            entries.append({
                "path": rel,
                "type": mtype,
                "name": fn,
                "size": size,
                "object_key": object_key(cfg, rel),
                "url": url,
            })
    entries.sort(key=lambda e: e["path"])

    manifest = {
        "updated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "endpoint": cfg["endpoint"] or None,
        "bucket": cfg["bucket"],
        "prefix": cfg["prefix"],
        "public_base_url": cfg["public_base_url"] or None,
        "total": len(entries),
        "total_size": sum(e["size"] for e in entries),
        "resources": entries,
    }
    save_manifest(manifest)

    by_type = {}
    for e in entries:
        by_type[e["type"]] = by_type.get(e["type"], 0) + 1
    detail = "，".join(f"{k} {v} 个" for k, v in sorted(by_type.items()))
    print(f"扫描完成：共 {len(entries)} 个资源文件（{detail}），"
          f"合计 {manifest['total_size'] / 1024 / 1024:.1f} MB")
    print(f"清单已写入：{MANIFEST_PATH}")
    if not cfg["endpoint"]:
        print("提示：尚未配置 MinIO（endpoint 为空）。scan 仅生成清单，"
              "如需上传请先配置 scripts/minio_config.json 或环境变量。")


def get_client(cfg: dict):
    try:
        from minio import Minio
    except ImportError:
        sys.exit("缺少依赖：请先执行  pip install -r scripts/requirements.txt")
    if not (cfg["endpoint"] and cfg["access_key"] and cfg["secret_key"]):
        sys.exit("缺少 MinIO 配置：请填写 scripts/minio_config.json"
                 "（模板见 minio_config.example.json）或设置 MINIO_* 环境变量")
    return Minio(cfg["endpoint"], access_key=cfg["access_key"],
                 secret_key=cfg["secret_key"], secure=cfg["secure"])


def cmd_sync(root: Path, cfg: dict, rescan: bool):
    from minio import S3Error

    client = get_client(cfg)
    if rescan or not MANIFEST_PATH.exists():
        cmd_scan(root, cfg)
    manifest = load_manifest()
    if not manifest or not manifest.get("resources"):
        sys.exit("清单为空：请确认资源根目录下存在图片/音频/视频文件")

    if not client.bucket_exists(cfg["bucket"]):
        client.make_bucket(cfg["bucket"])
        print(f"已创建桶：{cfg['bucket']}")

    if cfg["set_public_policy"]:
        try:
            client.set_bucket_policy(cfg["bucket"], PUBLIC_POLICY % cfg["bucket"])
            print(f"已将桶 {cfg['bucket']} 设为公开只读（链接可直接访问）")
        except Exception as ex:  # noqa: BLE001
            print(f"警告：设置公开策略失败（{ex}），可改用 presign 生成签名链接")

    n = len(manifest["resources"])
    uploaded = skipped = 0
    for i, e in enumerate(manifest["resources"], 1):
        key = e["object_key"]
        local = root / e["path"]
        if not local.exists():
            print(f"[{i}/{n}] 跳过（本地不存在）{e['path']}")
            continue
        try:
            st = client.stat_object(cfg["bucket"], key)
            exists_same = st.size == e["size"]
        except S3Error:
            exists_same = False
        if not exists_same:
            client.fput_object(cfg["bucket"], key, str(local))
            uploaded += 1
            action = "已上传"
        else:
            skipped += 1
            action = "已存在跳过"
        e["url"] = public_url(cfg, key)
        print(f"[{i}/{n}] {action}  {key}")

    manifest.update({
        "updated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "endpoint": cfg["endpoint"],
        "bucket": cfg["bucket"],
        "prefix": cfg["prefix"],
        "public_base_url": cfg["public_base_url"] or None,
    })
    save_manifest(manifest)
    print(f"\n同步完成：新上传 {uploaded} 个，已存在跳过 {skipped} 个")

    # 清单本身也同步进桶（固定短键，供看板等外部程序读取最新索引）
    manifest_key = "resources/minio-manifest.json"
    client.fput_object(cfg["bucket"], manifest_key, str(MANIFEST_PATH))
    print(f"资源清单已同步到桶内：{cfg['bucket']}/{manifest_key}")
    if not cfg["public_base_url"]:
        print("提示：未配置 public_base_url，清单中 url 为空；"
              "请在配置中填写 MinIO 公网访问基址后重新 sync")


def cmd_presign(cfg: dict, days: int):
    client = get_client(cfg)
    manifest = load_manifest()
    if not manifest or not manifest.get("resources"):
        sys.exit("清单不存在或为空：请先运行 scan")
    from datetime import timedelta
    for e in manifest["resources"]:
        e["url"] = client.presigned_get_object(
            cfg["bucket"], e["object_key"], expires=timedelta(days=days))
    manifest["updated"] = datetime.now().astimezone().isoformat(timespec="seconds")
    save_manifest(manifest)
    print(f"已生成 {len(manifest['resources'])} 条签名链接（有效期 {days} 天），"
          f"已写回 {MANIFEST_PATH}")


def cmd_check(cfg: dict):
    from minio import S3Error

    client = get_client(cfg)
    manifest = load_manifest()
    if not manifest or not manifest.get("resources"):
        sys.exit("清单不存在或为空：请先运行 scan")
    ok = 0
    missing, mismatch = [], []
    for e in manifest["resources"]:
        try:
            st = client.stat_object(cfg["bucket"], e["object_key"])
            if st.size == e["size"]:
                ok += 1
            else:
                mismatch.append(e["path"])
        except S3Error:
            missing.append(e["path"])
    print(f"校验结果：一致 {ok} / 缺失 {len(missing)} / 大小不符 {len(mismatch)}")
    for p in missing:
        print(f"  缺失：{p}")
    for p in mismatch:
        print(f"  大小不符：{p}")
    if missing or mismatch:
        sys.exit(1)


def cmd_url(path: str):
    manifest = load_manifest()
    if not manifest or not manifest.get("resources"):
        sys.exit("清单不存在或为空：请先运行 scan")
    target = path.replace("\\", "/")
    for e in manifest["resources"]:
        if e["path"] == target:
            if e.get("url"):
                print(e["url"])
            else:
                print(f"（尚未上传/未生成链接；对象键：{e['object_key']}）")
            return
    sys.exit(f"清单中未找到资源：{path}")


def main():
    ap = argparse.ArgumentParser(
        description="code-to-video MinIO 资源同步工具（详细用法见文件头部说明）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("scan", help="扫描资源根目录，生成/刷新资源清单")
    p.add_argument("root", help="资源根目录（即包含 audio/images/videos 的完整目录）")

    p = sub.add_parser("sync", help="上传资源到 MinIO 并生成访问链接")
    p.add_argument("root", help="资源根目录")
    p.add_argument("--rescan", action="store_true", help="上传前重新扫描目录")

    p = sub.add_parser("presign", help="为私有桶生成临时签名链接")
    p.add_argument("--expire-days", type=int, default=7, help="签名有效期（天），默认 7")

    sub.add_parser("check", help="校验桶内对象与清单是否一致")

    p = sub.add_parser("url", help="查询某个资源的访问链接")
    p.add_argument("path", help="资源相对路径，如 images/songkou_characters/xxx.png")

    args = ap.parse_args()
    cfg = load_config()

    if args.cmd == "scan":
        cmd_scan(normalize_path(args.root), cfg)
    elif args.cmd == "sync":
        cmd_sync(normalize_path(args.root), cfg, args.rescan)
    elif args.cmd == "presign":
        cmd_presign(cfg, args.expire_days)
    elif args.cmd == "check":
        cmd_check(cfg)
    elif args.cmd == "url":
        cmd_url(args.path)


if __name__ == "__main__":
    main()
