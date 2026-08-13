# -*- coding: utf-8 -*-
"""
momo 限時搶購 - 商品資料抓取程式 v9

v9 新增內容：
  - 抓取失敗自動記錄：當頁面載入逾時（重試後仍失敗）、找不到
    .MENTAL 區塊、或發生其他預期外錯誤時，會將失敗事件記錄到
    snapshots/scrape_failures.csv，方便之後離線檢視追蹤穩定性，
    不需要每次都去 log 檔案裡翻找。
  - 記錄欄位：timestamp（記錄時間）、date（時段日期）、
    slot（時段代碼）、checkpoint（open/mid/close）、reason（原因）

沿用 v8 修正內容：
  - page.goto 加上重試機制（逾時45秒，最多重試2次）
  - date_str 在 run() 一開始就固定，避免跨午夜日期錯位

沿用先前版本邏輯：
  - 每次執行只抓「當前時段」一筆資料，checkpoint 參數決定
    這次是 open（開檔）/ mid（時段中點）/ close（結束前5分）
  - CLOSE 抓取邏輯：直接用 .MENTAL 區塊第1個（mentals[0]）
    作為當前時段，不依賴已失效的 #posTag1

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
FAILURE_LOG = os.path.join(OUTPUT_DIR, "scrape_failures.csv")

VALID_CHECKPOINTS = ("open", "mid", "close")

GOTO_TIMEOUT_MS = 45000   # 頁面載入逾時時間
MAX_RETRIES     = 2       # 最多重試 2 次（總共嘗試 3 次）
RETRY_WAIT_MS   = 5000    # 每次重試前等待 5 秒

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


def log_failure(date_str: str, slot_code: str, checkpoint: str, reason: str):
    """把抓取失敗事件記錄到 snapshots/scrape_failures.csv，方便之後離線查看"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    file_exists = os.path.exists(FAILURE_LOG)
    now = datetime.now(TW_TZ)
    with open(FAILURE_LOG, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp", "date", "slot", "checkpoint", "reason"])
        writer.writerow([now.strftime("%Y-%m-%d %H:%M:%S"), date_str, slot_code, checkpoint, reason])
    print(f"  📝 已記錄失敗事件 → {FAILURE_LOG}（原因：{reason}）")


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


def save_csv(products: list, date_str: str, slot_code: str, checkpoint: str, time_text: str):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    filename = f"momo_{date_str}_{slot_code}_{checkpoint}.csv"
    filepath = os.path.join(OUTPUT_DIR, filename)

    fieldnames = ["icode","brand","name","discount","old_price","price","qty","scraped_at"]
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(products)

    print(f"  ✅ {checkpoint.upper()} → {filename}（{len(products)} 個商品）{time_text}")
    return filepath


def goto_with_retry(page, url: str):
    """帶重試機制的頁面載入，應對開檔瞬間流量尖峰造成的逾時"""
    last_error = None
    for attempt in range(1, MAX_RETRIES + 2):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=GOTO_TIMEOUT_MS)
            return True, None
        except Exception as e:
            last_error = type(e).__name__
            if attempt <= MAX_RETRIES:
                print(f"  ⚠️ 第{attempt}次頁面載入失敗，{RETRY_WAIT_MS//1000}秒後重試...（{last_error}）")
                page.wait_for_timeout(RETRY_WAIT_MS)
            else:
                print(f"  ❌ 頁面載入失敗，已重試{MAX_RETRIES}次仍無法載入，放棄本次抓取（{last_error}）")
    return False, last_error


def run(checkpoint: str):
    now        = datetime.now(TW_TZ)
    scraped_at = now.strftime("%Y-%m-%d %H:%M:%S")
    date_str   = now.strftime("%Y%m%d")   # 一開始就固定，全流程共用，避免跨午夜錯位
    cur_slot   = get_current_slot()

    print(f"\n🚀 開始抓取（台灣時間 {now.strftime('%H:%M')}，checkpoint={checkpoint}）")
    print(f"   當前時段：{cur_slot}")

    products  = []
    time_text = ""

    try:
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
            ok, err_reason = goto_with_retry(page, MOMO_URL)

            if not ok:
                log_failure(date_str, cur_slot, checkpoint, f"page_goto_failed:{err_reason}")
            else:
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
                    if len(products) == 0:
                        log_failure(date_str, cur_slot, checkpoint, "mentals_found_but_zero_products")
                else:
                    print("  ⚠️ 找不到當前時段區塊")
                    log_failure(date_str, cur_slot, checkpoint, "no_mentals_found")

            browser.close()

    except Exception as e:
        print(f"  ❌ 發生預期外錯誤：{type(e).__name__}: {e}")
        log_failure(date_str, cur_slot, checkpoint, f"unexpected_error:{type(e).__name__}")

    print()
    save_csv(products, date_str, cur_slot, checkpoint, f"  ← {time_text}")

    return cur_slot


if __name__ == "__main__":
    checkpoint = sys.argv[1] if len(sys.argv) > 1 else "close"
    if checkpoint not in VALID_CHECKPOINTS:
        print(f"❌ 無效的 checkpoint 參數：{checkpoint}（必須是 open / mid / close）")
        sys.exit(1)
    run(checkpoint)
