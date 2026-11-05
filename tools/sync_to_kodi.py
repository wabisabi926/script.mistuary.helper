#!/usr/bin/env python3
"""把仓库同步到 Kodi 的插件目录。

换机器、换用户名都不用改脚本：目标路径按 Kodi 的标准位置推导。

    Windows: %APPDATA%\\Kodi\\addons\\script.mistuary.helper
    Linux:   ~/.kodi/addons/script.mistuary.helper
    macOS:   ~/Library/Application Support/Kodi/addons/script.mistuary.helper

用法：
    python tools/sync_to_kodi.py              # 同步
    python tools/sync_to_kodi.py --dry-run    # 只看目标路径和文件数
    python tools/sync_to_kodi.py --path D:/Kodi/addons/script.mistuary.helper

为什么需要它：插件的 service 只在 Kodi 启动时拉起，改完代码不重启就一直跑旧逻辑；
手工复制又容易漏文件（2026-11-05 出现过「仓库 0.3.7、真机 0.3.6」的漂移）。
跑这个脚本会把整个运行时目录覆盖一遍，并在最后打印版本号，方便核对。

排除：.git / .github / tests / tools / docs / __pycache__（Kodi 用不到）
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADDON_ID = "script.mistuary.helper"
EXCLUDE_DIRS = {".git", ".github", "tests", "tools", "docs", "__pycache__"}
EXCLUDE_FILES = {".gitignore"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}


def default_target() -> Path:
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA")
        if not base:
            raise SystemExit("找不到 %APPDATA%，请用 --path 手动指定目标目录")
        return Path(base) / "Kodi" / "addons" / ADDON_ID
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Kodi" / "addons" / ADDON_ID
    return Path.home() / ".kodi" / "addons" / ADDON_ID


def iter_files(root: Path):
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        if path.is_dir():
            continue
        if rel.name in EXCLUDE_FILES or rel.suffix in EXCLUDE_SUFFIXES:
            continue
        yield path, rel


def read_version(root: Path) -> str:
    try:
        import xml.etree.ElementTree as ET

        return ET.parse(root / "addon.xml").getroot().get("version", "?")
    except Exception:  # noqa: BLE001
        return "?"


def main() -> int:
    ap = argparse.ArgumentParser(description="同步插件到 Kodi addons 目录")
    ap.add_argument("--path", help="目标目录（默认按平台推导）")
    ap.add_argument("--dry-run", action="store_true", help="只统计，不复制")
    args = ap.parse_args()

    target = Path(args.path) if args.path else default_target()
    files = list(iter_files(ROOT))
    version = read_version(ROOT)

    print(f"源:   {ROOT}  (版本 {version})")
    print(f"目标: {target}")
    print(f"文件: {len(files)} 个")

    if args.dry_run:
        print("（dry-run，未复制）")
        return 0

    if not target.exists():
        print(f"✗ 目标不存在，先装一次插件: {target}")
        return 1

    copied = 0
    for src, rel in files:
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied += 1

    print(f"✓ 已同步 {copied} 个文件（版本 {read_version(target)}）")
    print("  重启 Kodi 或禁用/启用一次插件，service 才会加载新代码")
    return 0


if __name__ == "__main__":
    sys.exit(main())
