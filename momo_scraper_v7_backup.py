# -*- coding: utf-8 -*-
"""
momo 限時搶購 - 商品資料抓取程式 v7

設計邏輯（v7 全新架構）：
  改為單次抓取模式，每次執行只抓「當前時段」一筆資料，
  由外部（crontab）在同一時段內呼叫三次，分別帶入不同的
  checkpoint 參數，代表抓取的時間點：
    open  → 時段開檔（時段開始時）
    mid   → 時段中點（時段開始後 1/2 時間）
    close → 時段結束前 5 分鐘

  這樣可以在同一時段內觀察開檔→中段→結束的庫存變化趨勢，
  也能看出是否有中途加碼（結束庫存 > 中段或開檔庫存）的狀況。

v7 修正/簡化說明：
  - 移除舊版「一次抓當前+下一時段」的複合邏輯，因為現在
    每個時段會在自己開始時被獨立呼叫 open checkpoint，
    不需要再靠「上一時段結束前」順便偷抓下一時段。
  - CLOSE 抓取邏輯延續 v6 修正：直接用 .MENTAL 區塊的
    第1個（mentals[0]）作為當前時段，不依賴已失效的 #posTag1。

執行方式：
  python momo_scraper.py open
  python momo_scraper.py mid
  python momo_scraper.py close
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

VALID_CHECKPOINTS = ("open", "mid", "close")

SLOTS = [
    (0,  7,  "0000"),
    (7,  11, "0700"),
    (11, 14, "1100"),
    (14, 18, "1400"),
    (18, 22, "1800"),
    (22, 24, "2200"),
]


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


def save_csv(products: list, slot_code: str, checkpoint: str, time_text: str):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    now      = datetime.now(TW_TZ)
    date_str = now.strftime("%Y%m%d")

    filename = f"momo_{date_str}_{slot_code}_{checkpoint}.csv"
    filepath = os.path.join(OUTPUT_DIR, filename)

    fieldnames = ["icode","brand","name","discount","old_price","price","qty","scraped_at"]
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(products)

    print(f"  ✅ {checkpoint.upper()} → {filename}（{len(products)} 個商品）{time_text}")
    return filepath


def run(checkpoint: str):
    now        = datetime.now(TW_TZ)
    scraped_at = now.strftime("%Y-%m-%d %H:%M:%S")
    cur_slot   = get_current_slot()

    print(f"\n🚀 開始抓取（台灣時間 {now.strftime('%H:%M')}，checkpoint={checkpoint}）")
    print(f"   當前時段：{cur_slot}")

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

        try:
            page.wait_for_selector("#CustExclbuy div.MENTAL", timeout=15000)
        except Exception:
            print("  ⚠️ 等待頁面逾時，繼續嘗試...")
        page.wait_for_timeout(3000)

        # 抓取所有 .MENTAL 區塊，第1個（mentals[0]）即為當前時段
        mentals = page.query_selector_all("#CustExclbuy div.MENTAL")

        if len(mentals) >= 1:
            cur_div     = mentals[0]
            time_el_cur = cur_div.query_selector(".time")
            time_text   = time_el_cur.inner_text().strip() if time_el_cur else ""
            items       = cur_div.query_selector_all("li.box1")
            products    = parse_items(items, scraped_at)
        else:
            print("  ⚠️ 找不到當前時段區塊")
            products  = []
            time_text = ""

        browser.close()

    print()
    save_csv(products, cur_slot, checkpoint, f"  ← {time_text}")

    return cur_slot


if __name__ == "__main__":
    checkpoint = sys.argv[1] if len(sys.argv) > 1 else "close"
    if checkpoint not in VALID_CHECKPOINTS:
        print(f"❌ 無效的 checkpoint 參數：{checkpoint}（必須是 open / mid / close）")
        sys.exit(1)
    run(checkpoint)


