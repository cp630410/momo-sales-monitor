# -*- coding: utf-8 -*-
"""
momo 限時搶購 - 商品資料抓取程式 v3

修正內容：
  - 檔案改用「時段」命名，不用實際執行時間
  - 避免同一時段多次執行造成配對錯亂

檔案命名規則：
  momo_YYYYMMDD_HHMM_open.csv   HHMM = 時段開始時間
  momo_YYYYMMDD_HHMM_close.csv

執行方式：
  python momo_scraper.py open
  python momo_scraper.py close
"""

import re
import sys
import csv
import os
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright

# 固定使用台灣時間（UTC+8），不管在哪裡執行都正確
TW_TZ = timezone(timedelta(hours=8))

MOMO_URL    = "https://www.momoshop.com.tw/edm/cmmedm.jsp?lpn=O1K5FBOqsvN&n=1"
OUTPUT_DIR  = "snapshots"

# momo 六個時段定義
SLOTS = [
    (0,  7,  "0000"),
    (7,  11, "0700"),
    (11, 14, "1100"),
    (14, 18, "1400"),
    (18, 22, "1800"),
    (22, 24, "2200"),
]


def get_current_slot() -> str:
    """依台灣當前時間判斷所在時段，回傳 HHMM 字串"""
    now_hour = datetime.now(TW_TZ).hour
    for start, end, slot in SLOTS:
        if start <= now_hour < end:
            return slot
    return "2200"


def scrape_current_slot(headless: bool = True):
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

        try:
            page.wait_for_selector("#posTag1 li.box1", timeout=15000)
        except Exception:
            print("  ⚠️ 等待 posTag1 逾時，繼續嘗試...")

        page.wait_for_timeout(3000)

        time_el = page.query_selector("#posTag1 .time")
        slot_info["time_text"] = time_el.inner_text().strip() if time_el else ""

        scraped_at = datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M:%S")
        items = page.query_selector_all("#posTag1 li.box1")
        print(f"  找到 {len(items)} 個商品（posTag1 當前時段）")

        for li in items:
            try:
                a_tag = li.query_selector("a[href]")
                href  = a_tag.get_attribute("href") if a_tag else ""
                m     = re.search(r"i_code=(\d+)", href or "")
                icode = m.group(1) if m else None
                if not icode:
                    continue

                brand_el     = li.query_selector(".brand")
                name_el      = li.query_selector(".brand2")
                discount_el  = li.query_selector(".discount")
                old_price_el = li.query_selector(".oldPrice")
                price_el     = li.query_selector(".price")
                last_el      = li.query_selector(".last")

                qty_text  = last_el.inner_text().strip() if last_el else ""
                qty_match = re.search(r"(\d+)", qty_text)
                qty       = int(qty_match.group(1)) if qty_match else None

                products.append({
                    "icode":      icode,
                    "brand":      brand_el.inner_text().strip()      if brand_el     else "",
                    "name":       name_el.inner_text().strip()       if name_el      else "",
                    "discount":   discount_el.inner_text().strip()    if discount_el  else "",
                    "old_price":  _clean_price(old_price_el.inner_text() if old_price_el else ""),
                    "price":      _clean_price(price_el.inner_text()     if price_el     else ""),
                    "qty":        qty,
                    "scraped_at": scraped_at,
                })
            except Exception as e:
                print(f"  ⚠️ 跳過：{e}")

        browser.close()

    # 去重
    seen = {}
    for prod in products:
        seen[prod["icode"]] = prod
    return list(seen.values()), slot_info


def _clean_price(text: str):
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def save_snapshot(products: list, snap_type: str, slot_info: dict):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    now      = datetime.now(TW_TZ)
    date_str = now.strftime("%Y%m%d")
    slot     = get_current_slot()

    # 用時段命名，不用實際執行時間
    filename = f"momo_{date_str}_{slot}_{snap_type}.csv"
    filepath = os.path.join(OUTPUT_DIR, filename)

    fieldnames = ["icode","brand","name","discount","old_price","price","qty","scraped_at"]
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(products)

    print(f"\n✅ 已儲存 → {filepath}")
    print(f"   時段：{slot_info.get('time_text','未知')}")
    print(f"   商品數：{len(products)} 個")
    print(f"   抓取時間：{now.strftime('%Y-%m-%d %H:%M:%S')}")
    return filepath


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("open","close"):
        print("用法：python momo_scraper.py open|close")
        sys.exit(1)

    snap_type = sys.argv[1]
    print(f"\n🚀 開始抓取【{'開檔' if snap_type=='open' else '結束前'}】快照...")

    products, slot_info = scrape_current_slot(headless=True)
    save_snapshot(products, snap_type, slot_info)
