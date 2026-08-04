# -*- coding: utf-8 -*-
"""
momo 限時搶購 - 每月自動清理程式
================================
每月第二週週日 02:00 執行
清理上個月的 open/close 原始快照
永久保留 all_results.csv

執行方式：
  python cleanup.py           # 自動清理上個月
  python cleanup.py --month 2026-07  # 指定清理特定月份
"""

import os
import sys
import re
from datetime import datetime
from glob import glob


def get_last_month(ref: datetime = None) -> str:
    """回傳上個月的 YYYYMM 字串，例如 202607"""
    if ref is None:
        ref = datetime.now()
    if ref.month == 1:
        return f"{ref.year - 1}12"
    return f"{ref.year}{ref.month - 1:02d}"


def cleanup(target_month: str = None, dry_run: bool = False):
    """
    target_month: YYYYMM 格式，例如 '202607'
                  不指定則自動用上個月
    """
    if target_month is None:
        target_month = get_last_month()

    snapshot_dir = "snapshots"
    display_month = f"{target_month[:4]}/{target_month[4:]}"

    print(f"清理目標月份：{display_month}")
    print(f"保留檔案：all_results.csv（永遠不刪）")
    print("-" * 45)

    # 找所有 open/close 原始快照
    all_files = (
        glob(os.path.join(snapshot_dir, "momo_*_open.csv")) +
        glob(os.path.join(snapshot_dir, "momo_*_close.csv"))
    )

    deleted = []
    kept = []
    skipped = []

    for f in sorted(all_files):
        basename = os.path.basename(f)
        m = re.match(r"momo_(\d{8})_", basename)
        if not m:
            skipped.append(f)
            continue

        file_ym = m.group(1)[:6]  # 取 YYYYMM

        if file_ym == target_month:
            deleted.append(f)
            if not dry_run:
                os.remove(f)
        else:
            kept.append(f)

    print(f"刪除 {display_month} 的快照：{len(deleted)} 個檔案")
    print(f"保留其他月份快照：{len(kept)} 個檔案")

    if deleted:
        print("\n已刪除：")
        for f in deleted[:10]:
            print(f"  ✗ {os.path.basename(f)}")
        if len(deleted) > 10:
            print(f"  ... 共 {len(deleted)} 個")
    else:
        print(f"沒有找到 {display_month} 的快照檔案")

    return len(deleted)


if __name__ == "__main__":
    target = None
    for arg in sys.argv[1:]:
        if arg.startswith("--month="):
            # 支援 2026-07 或 202607 格式
            val = arg.split("=")[1].replace("-", "")
            target = val

    cleanup(target_month=target)
