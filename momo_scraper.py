# -*- coding: utf-8 -*-
"""
momo 限時搶購 - 商品資料抓取程式 v2
修正內容（依測試結果）：
  1. 只抓 posTag1（當前進行中時段），不抓全頁所有時段
  2. 抓完立刻存成 CSV，不依賴瀏覽器記憶體

執行方式：
  # 開檔快照（時段開始後 1 分鐘執行）
  python momo_scraper.py open

  # 結束前快照（時段結束前 10 分鐘執行）
  python momo_scraper.py close

URL 固定為 momo 限時搶購首頁，程式自動讀取當前時段。

需要的套件：
  pip install playwright
  playwright install chromium
"""

import re
import sys
import csv
import os
from datetime import datetime
from playwright.sync_api import sync_playwright

MOMO_URL = "https://www.momoshop.com.tw/edm/cmmedm.jsp?lpn=O1K5FBOqsvN&n=1"
OUTPUT_DIR = "snapshots"


def scrape_current_slot(headless: bool = True):
    """
    打開 momo 限時搶購頁面，只抓 posTag1（當前進行中時段）的商品。
    抓完立刻回傳，不留在記憶體。
    """
    products = []
    slot_info = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )

        print(f"  開啟頁面：{MOMO_URL}")
        page.goto(MOMO_URL, wait_until="domcontentloaded", timeout=30000)

        # 等待 posTag1 區塊出現
        try:
            page.wait_for_selector("#posTag1 li.box1", timeout=15000)
        except Exception:
            print("  ⚠️ 等待 posTag1 逾時，頁面可能載入較慢，繼續嘗試...")

        page.wait_for_timeout(3000)  # 額外等待確保完全載入

        # 抓時段資訊
        time_el = page.query_selector("#posTag1 .time")
        slot_info["time_text"] = time_el.inner_text().strip() if time_el else ""

        # 抓活動時間區間（例如「07/01 11:00~07/01 13:59」）
        act_time_el = page.query_selector("#posTag1 .activityTime, #posTag1 [class*='actTime']")
        slot_info["activity_time"] = act_time_el.inner_text().strip() if act_time_el else ""

        scraped_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 只抓 posTag1 裡面的 li.box1
        items = page.query_selector_all("#posTag1 li.box1")
        print(f"  找到 {len(items)} 個商品（posTag1 當前時段）")

        for li in items:
            try:
                a_tag = li.query_selector("a[href]")
                href = a_tag.get_attribute("href") if a_tag else ""
                m = re.search(r"i_code=(\d+)", href or "")
                icode = m.group(1) if m else None
                if not icode:
                    continue

                brand_el    = li.query_selector(".brand")
                name_el     = li.query_selector(".brand2")
                discount_el = li.query_selector(".discount")
                old_price_el= li.query_selector(".oldPrice")
                price_el    = li.query_selector(".price")
                last_el     = li.query_selector(".last")

                qty_text  = last_el.inner_text().strip() if last_el else ""
                qty_match = re.search(r"(\d+)", qty_text)
                qty       = int(qty_match.group(1)) if qty_match else None

                products.append({
                    "icode":       icode,
                    "brand":       brand_el.inner_text().strip()     if brand_el     else "",
                    "name":        name_el.inner_text().strip()      if name_el      else "",
                    "discount":    discount_el.inner_text().strip()   if discount_el  else "",
                    "old_price":   _clean_price(old_price_el.inner_text() if old_price_el else ""),
                    "price":       _clean_price(price_el.inner_text()     if price_el     else ""),
                    "qty":         qty,
                    "scraped_at":  scraped_at,
                })
            except Exception as e:
                print(f"  ⚠️ 單一商品解析失敗，跳過：{e}")

        browser.close()

    # 去重（同一商品在頁面可能出現兩次）
    seen = {}
    for p in products:
        seen[p["icode"]] = p
    return list(seen.values()), slot_info


def _clean_price(text: str):
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def save_snapshot(products: list, snap_type: str, slot_info: dict):
    """
    存成 CSV，檔名格式：momo_YYYYMMDD_HHMM_open.csv 或 _close.csv
    同時在控制台印出時段資訊確認。
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M")
    filename  = f"momo_{timestamp}_{snap_type}.csv"
    filepath  = os.path.join(OUTPUT_DIR, filename)

    fieldnames = ["icode", "brand", "name", "discount", "old_price", "price", "qty", "scraped_at"]
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(products)

    print(f"\n✅ 已儲存 → {filepath}")
    print(f"   時段：{slot_info.get('time_text', '未知')}")
    print(f"   商品數：{len(products)} 個")
    print(f"   抓取時間：{now.strftime('%Y-%m-%d %H:%M:%S')}")
    return filepath


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("open", "close"):
        print("用法：")
        print("  python momo_scraper.py open    ← 開檔快照（時段開始後 1 分鐘執行）")
        print("  python momo_scraper.py close   ← 結束前快照（時段結束前 10 分鐘執行）")
        sys.exit(1)

    snap_type = sys.argv[1]
    print(f"\n🚀 開始抓取【{'開檔' if snap_type=='open' else '結束前'}】快照...")

    products, slot_info = scrape_current_slot(headless=True)
    save_snapshot(products, snap_type, slot_info)
