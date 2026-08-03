# -*- coding: utf-8 -*-
"""
momo 限時搶購 - 成效計算程式 v3
修正內容：
  - 改為累積模式：結果追加到 all_results.csv，不產生獨立檔案
  - 修正售完判斷：組數歸零也算售完

執行方式：
  python compare_snapshots.py
  python compare_snapshots.py <open.csv> <close.csv>
"""

import csv
import os
import sys
from datetime import datetime
from glob import glob

OUTPUT_DIR   = "snapshots"
ALL_RESULTS  = os.path.join(OUTPUT_DIR, "all_results.csv")
FIELDNAMES   = ["date","slot","icode","brand","name","discount","price",
                "qty_open","qty_close","sold","sold_out","sell_rate"]


def load_snapshot(filepath: str) -> dict:
    data = {}
    with open(filepath, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            data[row["icode"]] = row
    return data


def parse_slot_from_filename(filepath: str) -> str:
    """從檔名抓時段，例如 momo_20260803_0700_result → 07:00"""
    base = os.path.basename(filepath)
    parts = base.split("_")
    if len(parts) >= 3:
        t = parts[2]
        return f"{t[:2]}:{t[2:]}"
    return "??"


def compare(open_file: str, close_file: str) -> list:
    snap_open  = load_snapshot(open_file)
    snap_close = load_snapshot(close_file)
    results = []

    for icode, s in snap_open.items():
        qty_start = int(s["qty"]) if s.get("qty") else None

        if icode in snap_close:
            qty_raw  = snap_close[icode].get("qty", "")
            qty_end  = int(qty_raw) if qty_raw and qty_raw.strip() else 0
            sold_out = (qty_end == 0)
        else:
            qty_end  = 0
            sold_out = True

        sold = max(qty_start - qty_end, 0) if qty_start is not None else None
        rate = round(sold / qty_start * 100, 1) if (sold is not None and qty_start) else 0.0

        results.append({
            "icode":    icode,
            "brand":    s.get("brand", ""),
            "name":     s.get("name", ""),
            "discount": s.get("discount", ""),
            "price":    s.get("price", ""),
            "qty_open": qty_start,
            "qty_close":qty_end,
            "sold":     sold,
            "sold_out": "是" if sold_out else "否",
            "sell_rate":rate,
        })

    results.sort(key=lambda r: -(r["sold"] or 0))
    return results


def append_to_all_results(results: list, date_str: str, slot_str: str):
    """把結果追加到 all_results.csv（不存在則建立）"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    file_exists = os.path.exists(ALL_RESULTS)

    with open(ALL_RESULTS, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if not file_exists:
            writer.writeheader()
        for r in results:
            writer.writerow({
                "date":      date_str,
                "slot":      slot_str,
                "icode":     r["icode"],
                "brand":     r["brand"],
                "name":      r["name"],
                "discount":  r["discount"],
                "price":     r["price"],
                "qty_open":  r["qty_open"],
                "qty_close": r["qty_close"],
                "sold":      r["sold"],
                "sold_out":  r["sold_out"],
                "sell_rate": r["sell_rate"],
            })
    print(f"✅ 已追加 {len(results)} 筆 → {ALL_RESULTS}")


def find_latest_pair():
    opens  = sorted(glob(os.path.join(OUTPUT_DIR, "*_open.csv")))
    closes = sorted(glob(os.path.join(OUTPUT_DIR, "*_close.csv")))
    if not opens or not closes:
        return None, None
    latest_open = opens[-1]
    matching_close = latest_open.replace("_open.csv", "_close.csv")
    if os.path.exists(matching_close):
        return latest_open, matching_close
    return latest_open, closes[-1]


if __name__ == "__main__":
    if len(sys.argv) == 3:
        open_file, close_file = sys.argv[1], sys.argv[2]
    else:
        open_file, close_file = find_latest_pair()
        if not open_file:
            print("❌ 找不到快照檔案")
            sys.exit(1)
        print(f"自動配對：\n  開檔：{open_file}\n  結束前：{close_file}")

    results = compare(open_file, close_file)

    # 從檔名取得日期和時段
    base     = os.path.basename(open_file)
    parts    = base.split("_")
    date_str = f"{parts[1][:4]}/{parts[1][4:6]}/{parts[1][6:]}" if len(parts) > 1 else datetime.now().strftime("%Y/%m/%d")
    slot_str = parse_slot_from_filename(open_file)

    append_to_all_results(results, date_str, slot_str)

    # 印出摘要
    sold_any  = [r for r in results if r["sold"] and r["sold"] > 0]
    sold_out  = [r for r in results if r["sold_out"] == "是"]
    print(f"\n{'商品名稱':<24} {'折扣':>5} {'開檔':>6} {'結束':>6} {'售出':>6} {'售出率':>7} {'售完':>5}")
    print("─" * 65)
    for r in results:
        print(f"{r['name'][:22]:<24} {r['discount']:>5} "
              f"{str(r['qty_open']):>6} {str(r['qty_close']):>6} "
              f"{str(r['sold'] or '-'):>6} {str(r['sell_rate'])+'%':>7} {r['sold_out']:>5}")
    print(f"\n總商品：{len(results)} ｜ 有銷售：{len(sold_any)} ｜ 售完：{len(sold_out)}")
