# -*- coding: utf-8 -*-
"""
momo 限時搶購 - 自動排程主程式
================================
只需執行一次，程式會在背景持續運作，
自動在每天六個時段的開檔和結束前分別抓取資料，並計算成效。

執行方式：
  python scheduler.py

停止方式：
  按 Ctrl + C

注意事項：
  - 執行期間電腦不能關機、不能睡眠
  - 建議插著電源執行
  - 所有資料存在 snapshots/ 資料夾

momo 每日六個時段：
  00:00 ~ 06:59
  07:00 ~ 10:59
  11:00 ~ 13:59
  14:00 ~ 17:59
  18:00 ~ 21:59
  22:00 ~ 23:59
"""

import time
import subprocess
import sys
import os
from datetime import datetime, timedelta


# ── 設定區 ──────────────────────────────────────────
# 每個時段「開始幾分鐘後」抓開檔快照
OPEN_DELAY_MIN = 1

# 每個時段「結束幾分鐘前」抓結束前快照
CLOSE_BEFORE_MIN = 10

# momo 六個時段的開始時間（小時, 分鐘）
SLOTS = [
    (0,  0),   # 00:00
    (7,  0),   # 07:00
    (11, 0),   # 11:00
    (14, 0),   # 14:00
    (18, 0),   # 18:00
    (22, 0),   # 22:00
]

# 每個時段的結束時間（對應上面的順序）
SLOT_ENDS = [
    (6,  59),  # 00:00 檔結束
    (10, 59),  # 07:00 檔結束
    (13, 59),  # 11:00 檔結束
    (17, 59),  # 14:00 檔結束
    (21, 59),  # 18:00 檔結束
    (23, 59),  # 22:00 檔結束
]

# 程式所在資料夾（自動偵測）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# ────────────────────────────────────────────────────


def log(msg: str):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}", flush=True)


def run_scraper(snap_type: str):
    """執行抓取程式（open 或 close）"""
    scraper = os.path.join(BASE_DIR, "momo_scraper.py")
    log(f"▶ 執行抓取：{snap_type.upper()}")
    result = subprocess.run(
        [sys.executable, scraper, snap_type],
        capture_output=True, text=True,
        encoding=sys.stdout.encoding or "utf-8",
        errors="replace"
    )
    if result.stdout:
        for line in result.stdout.strip().split("\n"):
            log(f"   {line}")
    if result.returncode != 0 and result.stderr:
        log(f"   ⚠️ 錯誤：{result.stderr.strip()[:200]}")


def run_compare():
    """執行成效計算程式"""
    compare = os.path.join(BASE_DIR, "compare_snapshots.py")
    log("▶ 計算成效報告...")
    result = subprocess.run(
        [sys.executable, compare],
        capture_output=True, text=True,
        encoding=sys.stdout.encoding or "utf-8",
        errors="replace"
    )
    if result.stdout:
        for line in result.stdout.strip().split("\n"):
            log(f"   {line}")
    if result.returncode != 0 and result.stderr:
        log(f"   ⚠️ 錯誤：{result.stderr.strip()[:200]}")


def get_today_schedule():
    """
    計算今天所有需要執行的時間點，回傳 list of (datetime, action)
    action 可以是 'open'、'close'、'compare'
    """
    today = datetime.now().date()
    schedule = []

    for i, (sh, sm) in enumerate(SLOTS):
        eh, em = SLOT_ENDS[i]

        # 開檔快照時間 = 時段開始 + OPEN_DELAY_MIN 分鐘
        open_time = datetime(today.year, today.month, today.day, sh, sm) \
                    + timedelta(minutes=OPEN_DELAY_MIN)

        # 結束前快照時間 = 時段結束 - CLOSE_BEFORE_MIN 分鐘
        close_time = datetime(today.year, today.month, today.day, eh, em) \
                     - timedelta(minutes=CLOSE_BEFORE_MIN)

        # 計算成效時間 = 結束前快照後 2 分鐘（等抓取完成）
        compare_time = close_time + timedelta(minutes=2)

        schedule.append((open_time,   "open",    f"{sh:02d}:{sm:02d} 檔"))
        schedule.append((close_time,  "close",   f"{sh:02d}:{sm:02d} 檔"))
        schedule.append((compare_time,"compare", f"{sh:02d}:{sm:02d} 檔"))

    # 依時間排序
    schedule.sort(key=lambda x: x[0])
    return schedule


def seconds_until(target: datetime) -> float:
    now = datetime.now()
    diff = (target - now).total_seconds()
    return diff


def main():
    log("=" * 55)
    log("  momo 限時搶購自動排程啟動")
    log("  按 Ctrl+C 可停止程式")
    log("=" * 55)

    while True:
        schedule = get_today_schedule()
        now = datetime.now()

        # 找出今天還沒執行的任務
        pending = [(t, action, label) for t, action, label in schedule if t > now]

        if not pending:
            # 今天的任務都跑完了，等到明天 00:01 重新計算
            tomorrow = datetime(now.year, now.month, now.day) + timedelta(days=1, minutes=1)
            wait_sec = seconds_until(tomorrow)
            log(f"今日所有任務完成，等待明天 00:01 繼續... ({wait_sec/3600:.1f} 小時後)")
            time.sleep(wait_sec)
            continue

        # 取下一個任務
        next_time, action, label = pending[0]
        wait_sec = seconds_until(next_time)

        if wait_sec > 0:
            log(f"下一個任務：【{label} {action.upper()}】於 {next_time.strftime('%H:%M')} 執行（{wait_sec/60:.0f} 分鐘後）")

            # 每 60 秒檢查一次（避免電腦時間偏移）
            while seconds_until(next_time) > 5:
                time.sleep(30)

            # 最後幾秒精準等待
            remaining = seconds_until(next_time)
            if remaining > 0:
                time.sleep(remaining)

        # 執行任務
        log(f"⏰ 執行 [{label} {action.upper()}]")
        if action == "open":
            run_scraper("open")
        elif action == "close":
            run_scraper("close")
        elif action == "compare":
            run_compare()

        # 短暫等待，避免重複觸發
        time.sleep(10)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("\n程式已停止（Ctrl+C）")
