# -*- coding: utf-8 -*-
"""
momo 限時搶購 - 商品資料抓取程式 v6

設計邏輯：
  一次開啟頁面，同時抓取兩筆資料：
  1. 第1個 .MENTAL div（當前時段）→ CLOSE 快照
  2. 第2個 .MENTAL div（下一時段）→ OPEN 快照

v6 修正說明（2026-08-06）：
  - 原本 CLOSE 依賴 #posTag1 這個 id 抓取，但 momo 網頁已改版，
    該 id 已不存在，導致 CLOSE 持續抓到 0 個商品。
  - 診斷確認：.MENTAL 區塊本身已依時段順序排列，
    第1個 = 當前時段，第2個 = 下一時段，
    因此改為直接用 mentals[0] / mentals[1]，不再依賴 posTag1。

優點：
  - 一次網頁載入，兩筆資料
  - 順序 100% 保證（先 close 後 open，同一次執行）
  - 減少 GitHub Actions 執行次數
  - 不再依賴可能失效的 id，只依賴穩定的 class 結構

執行方式：
  python momo_scraper.py
"""

import re
import sys
import csv
import os
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright

TW_TZ      = timezone(timedelta(hours=8))
MOMO_URL   = "https://www.momoshop.com.tw/edm/cmmedm.jsp?lpn=O1K5FBOqsvN&n=1"
OUTPUT_DIR = "snapshots"

SLOTS = [
    (0,  7,  "0000"),
    (7,  11, "0700"),
    (11, 14, "1100"),
    (14, 18, "1400"),
    (18, 22, "1800"),
    (22, 24, "2200"),
]

NEXT_SLOT = {
    "0000": "0700",
    "0700": "1100",
    "1100": "1400",
    "1400": "1800",
    "1800": "2200",
    "2200": "0000",
}


def get_current_slot() -> str:
    now_hour = datetime.now(TW_TZ).hour
    for start, end, slot in SLOTS:
        if start <= now_hour < end:
            return slot
    return "2200"


def parse_items(items, scraped_at: str) -> list:
    products = []
    for li in items:
        try:
            a_tag = li.query_selector("a[href]")
            href  = a_tag.get_attribute("href") if a_tag else ""
            m     = re.search(r"i_code=(\d+)", href or "")
            icode = m.group(1) if m else None
            if not icode:
                continue

            def get_txt(sel):
                el = li.query_selector(sel)
                return el.inner_text().strip() if el else ""

            qty_match = re.search(r"(\d+)", get_txt(".last"))
            qty       = int(qty_match.group(1)) if qty_match else None

            old_price = get_txt(".oldPrice")
            price     = get_txt(".price")

            products.append({
                "icode":      icode,
                "brand":      get_txt(".brand"),
                "name":       get_txt(".brand2"),
                "discount":   get_txt(".discount"),
                "old_price":  re.sub(r"[^\d]", "", old_price) or None,
                "price":      re.sub(r"[^\d]", "", price)     or None,
                "qty":        qty,
                "scraped_at": scraped_at,
            })
        except Exception as e:
            print(f"  ⚠️ 跳過商品：{e}")

    seen = {}
    for p in products:
        seen[p["icode"]] = p
    return list(seen.values())


def save_csv(products: list, slot_code: str, snap_type: str, time_text: str):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    now      = datetime.now(TW_TZ)
    date_str = now.strftime("%Y%m%d")

    # 如果是 open 且時段是 0000，日期用隔天
    if snap_type == "open" and slot_code == "0000":
        from datetime import timedelta as td
        date_str = (now + td(days=1)).strftime("%Y%m%d")

    filename = f"momo_{date_str}_{slot_code}_{snap_type}.csv"
    filepath = os.path.join(OUTPUT_DIR, filename)

    fieldnames = ["icode","brand","name","discount","old_price","price","qty","scraped_at"]
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(products)

    print(f"  ✅ {snap_type.upper()} → {filename}（{len(products)} 個商品）{time_text}")
    return filepath


def run():
    now          = datetime.now(TW_TZ)
    scraped_at   = now.strftime("%Y-%m-%d %H:%M:%S")
    cur_slot     = get_current_slot()
    next_slot    = NEXT_SLOT[cur_slot]

    print(f"\n🚀 開始抓取（台灣時間 {now.strftime('%H:%M')}）")
    print(f"   當前時段：{cur_slot} → CLOSE")
    print(f"   下一時段：{next_slot} → OPEN")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page    = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )

        print(f"  開啟頁面：{MOMO_URL}")
        page.goto(MOMO_URL, wait_until="domcontentloaded", timeout=30000)

        # 等待頁面載入
        try:
            page.wait_for_selector("#CustExclbuy div.MENTAL", timeout=15000)
        except Exception:
            print("  ⚠️ 等待頁面逾時，繼續嘗試...")
        page.wait_for_timeout(3000)

        # 一次抓取所有 .MENTAL 區塊（依時段順序排列：第1個=當前，第2個=下一）
        mentals = page.query_selector_all("#CustExclbuy div.MENTAL")

        # ── CLOSE：抓當前時段（第1個 .MENTAL）──
        if len(mentals) >= 1:
            cur_div       = mentals[0]
            time_el_cur   = cur_div.query_selector(".time")
            time_text_cur = time_el_cur.inner_text().strip() if time_el_cur else ""
            items_close   = cur_div.query_selector_all("li.box1")
            products_close = parse_items(items_close, scraped_at)
        else:
            print("  ⚠️ 找不到當前時段區塊")
            products_close = []
            time_text_cur  = ""

        # ── OPEN：抓下一時段（第2個 .MENTAL）──
        if len(mentals) >= 2:
            next_div       = mentals[1]
            time_el_next   = next_div.query_selector(".time")
            time_text_next = time_el_next.inner_text().strip() if time_el_next else ""
            items_open     = next_div.query_selector_all("li.box1")
            products_open  = parse_items(items_open, scraped_at)
        else:
            print("  ⚠️ 找不到下一時段區塊")
            products_open  = []
            time_text_next = ""

        browser.close()

    # 儲存兩個快照
    print()
    save_csv(products_close, cur_slot,  "close", f"  ← {time_text_cur}")
    save_csv(products_open,  next_slot, "open",  f"  ← {time_text_next}")

    return cur_slot


if __name__ == "__main__":
    run()
