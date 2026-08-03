# -*- coding: utf-8 -*-
"""
momo 限時搶購 - 成效計算程式 v2
修正內容：
  1. 自動配對同一時段的 open/close 檔案，不需手動指定
  2. 售完下架（close 沒有的商品）正確標記並計算
  3. 輸出檔名與 open/close 對應

執行方式：
  # 自動找最新一組 open/close 配對來計算
  python compare_snapshots.py

  # 或指定特定的開檔和結束前檔案
  python compare_snapshots.py snapshots/momo_20260701_1101_open.csv snapshots/momo_20260701_1350_close.csv
"""

import csv
import os
import sys
import re
from datetime import datetime
from glob import glob


def load_snapshot(filepath: str) -> dict:
    data = {}
    with open(filepath, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            data[row["icode"]] = row
    return data


def compare(open_file: str, close_file: str):
    snap_open  = load_snapshot(open_file)
    snap_close = load_snapshot(close_file)

    results = []

    # 開檔有的商品 → 主要分析對象
    for icode, s in snap_open.items():
        qty_start = int(s["qty"]) if s["qty"] else None

        if icode in snap_close:
            qty_raw  = snap_close[icode]["qty"]
            qty_end  = int(qty_raw) if qty_raw and qty_raw.strip() else 0
            # 售完判斷：消失 OR 組數歸零
            sold_out = (qty_end == 0)
        else:
            # 結束前消失 → 售完下架
            qty_end  = 0
            sold_out = True

        sold = max(qty_start - qty_end, 0) if qty_start is not None else None
        rate = round(sold / qty_start * 100, 1) if (sold is not None and qty_start) else None

        results.append({
            "icode":      icode,
            "brand":      s.get("brand", ""),
            "name":       s.get("name", ""),
            "price":      s.get("price", ""),
            "old_price":  s.get("old_price", ""),
            "discount":   s.get("discount", ""),
            "qty_open":   qty_start,
            "qty_close":  qty_end,
            "sold":       sold,
            "sold_out":   "是" if sold_out else "否",
            "sell_rate":  f"{rate}%" if rate is not None else "N/A",
        })

    # close 有但 open 沒有 → 中途新增商品，標記備注
    for icode, s in snap_close.items():
        if icode not in snap_open:
            results.append({
                "icode":     icode,
                "brand":     s.get("brand", ""),
                "name":      s.get("name", "") + "【中途加入】",
                "price":     s.get("price", ""),
                "old_price": s.get("old_price", ""),
                "discount":  s.get("discount", ""),
                "qty_open":  None,
                "qty_close": int(s["qty"]) if s["qty"] else None,
                "sold":      None,
                "sold_out":  "否",
                "sell_rate": "N/A",
            })

    # 依售出數排序（多→少）
    results.sort(key=lambda r: (r["sold"] is None, -(r["sold"] or 0)))
    return results


def save_result(results: list, open_file: str):
    # 輸出檔名根據 open 檔名命名
    base = os.path.basename(open_file).replace("_open.csv", "_result.csv")
    outdir = os.path.dirname(open_file)
    outpath = os.path.join(outdir, base)

    fieldnames = ["icode","brand","name","price","old_price","discount",
                  "qty_open","qty_close","sold","sold_out","sell_rate"]
    with open(outpath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    print(f"\n✅ 成效報告 → {outpath}")
    return outpath


def find_latest_pair():
    """自動找 snapshots/ 裡最新的一組 open/close 配對"""
    opens  = sorted(glob("snapshots/*_open.csv"))
    closes = sorted(glob("snapshots/*_close.csv"))
    if not opens or not closes:
        return None, None

    # 取最新的 open，找同一時間前綴的 close
    latest_open = opens[-1]
    prefix = latest_open.replace("_open.csv", "")
    matching_close = prefix + "_close.csv"
    if os.path.exists(matching_close):
        return latest_open, matching_close

    # 找不到同前綴，就用最新的 close
    return latest_open, closes[-1]


if __name__ == "__main__":
    if len(sys.argv) == 3:
        open_file  = sys.argv[1]
        close_file = sys.argv[2]
    else:
        open_file, close_file = find_latest_pair()
        if not open_file:
            print("❌ 找不到 snapshots/ 資料夾裡的快照檔案，請先執行 momo_scraper.py")
            sys.exit(1)
        print(f"自動配對：\n  開檔：{open_file}\n  結束前：{close_file}")

    results = compare(open_file, close_file)
    outpath = save_result(results, open_file)

    # 印出摘要
    sold_any   = [r for r in results if r["sold"] and r["sold"] > 0]
    sold_out   = [r for r in results if r["sold_out"] == "是"]
    no_sales   = [r for r in results if r["sold"] == 0]

    print(f"\n{'商品名稱':<28} {'折扣':>5} {'開檔':>6} {'結束':>6} {'售出':>6} {'售出率':>7} {'售完':>5}")
    print("─" * 68)
    for r in results:
        print(f"{r['name'][:26]:<28} {r['discount']:>5} "
              f"{str(r['qty_open'] or '-'):>6} {str(r['qty_close'] or '-'):>6} "
              f"{str(r['sold'] or '-'):>6} {r['sell_rate']:>7} {r['sold_out']:>5}")

    print(f"\n📊 摘要")
    print(f"   總商品數：{len(results)} 個")
    print(f"   有銷售：{len(sold_any)} 個")
    print(f"   售完下架：{len(sold_out)} 個")
    print(f"   零銷售：{len(no_sales)} 個")
