# -*- coding: utf-8 -*-
"""
momo 限時搶購 - 商品資料抓取程式 v4

設計邏輯：
  OPEN  → 抓「下一個時段」的商品（準備開搶，顯示原始組數）
  CLOSE → 抓「當前時段」的商品（posTag1，顯示剩餘組數）

優點：
  - OPEN 的原始組數 100% 準確（開賣前的組數）
  - OPEN 和 CLOSE 抓不同時段，互不干擾，不會因 GitHub 延遲而衝突
  - 檔案以時段代碼命名，配對永遠正確

時段定義（台灣時間）：
  00:00~06:59 → 0000
  07:00~10:59 → 0700
  11:00~13:59 → 1100
  14:00~17:59 → 1400
  18:00~21:59 → 1800
  22:00~23:59 → 2200

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

MOMO_URL   = "https://www.momoshop.com.tw/edm/cmmedm.jsp?lpn=O1K5FBOqsvN&n=1"
OUTPUT_DIR = "snapshots"

# momo 六個時段定義（開始小時, 結束小時, 時段代碼）
SLOTS = [
    (0,  7,  "0000"),
    (7,  11, "0700"),
    (11, 14, "1100"),
    (14, 18, "1400"),
    (18, 22, "1800"),
    (22, 24, "2200"),
]

# 下一個時段的對應
NEXT_SLOT = {
    "0000": "0700",
    "0700": "1100",
    "1100": "1400",
    "1400": "1800",
    "1800": "2200",
    "2200": "0000",
}


def get_current_slot() -> str:
    """依台灣時間判斷當前時段"""
    now_hour = datetime.now(TW_TZ).hour
    for start, end, slot in SLOTS:
        if start <= now_hour < end:
            return slot
    return "2200"


def get_next_slot() -> str:
    """取得下一個時段代碼"""
    return NEXT_SLOT[get_current_slot()]


def scrape_open(page) -> tuple:
    """
    OPEN：抓下一時段（準備開搶）的商品
    頁面結構：#CustExclbuy 下的第二個 .MENTAL div
    """
    try:
        page.wait_for_selector("#CustExclbuy div.MENTAL", timeout=15000)
    except Exception:
        print("  ⚠️ 等待 .MENTAL 逾時，繼續嘗試...")

    page.wait_for_timeout(3000)

    # 取第二個 MENTAL div（下一時段）
    mentals = page.query_selector_all("#CustExclbuy div.MENTAL")
    if len(mentals) < 2:
        print(f"  ⚠️ 找不到下一時段區塊，只有 {len(mentals)} 個 MENTAL div")
        return [], {}

    next_div   = mentals[1]
    time_el    = next_div.query_selector(".time")
    time_text  = time_el.inner_text().strip() if time_el else ""
    items      = next_div.query_selector_all("li.box1")
    slot_code  = get_next_slot()

    print(f"  下一時段：{time_text}（{slot_code}），共 {len(items)} 個商品")
    return items, {"time_text": time_text, "slot_code": slot_code}


def scrape_close(page) -> tuple:
    """
    CLOSE：抓當前時段（posTag1）的商品
    """
    try:
        page.wait_for_selector("#posTag1 li.box1", timeout=15000)
    except Exception:
        print("  ⚠️ 等待 posTag1 逾時，繼續嘗試...")

    page.wait_for_timeout(3000)

    time_el   = page.query_selector("#posTag1 .time")
    time_text = time_el.inner_text().strip() if time_el else ""
    items     = page.query_selector_all("#posTag1 li.box1")
    slot_code = get_current_slot()

    print(f"  當前時段：{time_text}（{slot_code}），共 {len(items)} 個商品")
    return items, {"time_text": time_text, "slot_code": slot_code}


def parse_items(items, scraped_at: str) -> list:
    """解析商品清單"""
    products = []
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
            print(f"  ⚠️ 跳過商品：{e}")

    # 去重
    seen = {}
    for p in products:
        seen[p["icode"]] = p
    return list(seen.values())


def _clean_price(text: str):
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


def save_snapshot(products: list, snap_type: str, slot_info: dict):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    now       = datetime.now(TW_TZ)
    date_str  = now.strftime("%Y%m%d")
    slot_code = slot_info.get("slot_code", get_current_slot())

    filename = f"momo_{date_str}_{slot_code}_{snap_type}.csv"
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


def run(snap_type: str, headless: bool = True):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page    = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        print(f"  開啟頁面：{MOMO_URL}")
        page.goto(MOMO_URL, wait_until="domcontentloaded", timeout=30000)

        scraped_at = datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M:%S")

        if snap_type == "open":
            items, slot_info = scrape_open(page)
        else:
            items, slot_info = scrape_close(page)

        products = parse_items(items, scraped_at)
        browser.close()

    save_snapshot(products, snap_type, slot_info)


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("open", "close"):
        print("用法：python momo_scraper.py open|close")
        sys.exit(1)

    snap_type = sys.argv[1]
    print(f"\n🚀 開始抓取【{'開檔（下一時段）' if snap_type=='open' else '結束前（當前時段）'}】快照...")
    run(snap_type)
