import re
import time
from urllib.parse import urljoin
from flask import Flask, render_template, jsonify, send_from_directory
import requests
from bs4 import BeautifulSoup

app = Flask(__name__)

SOURCE_URL  = "https://mobile-mix.jp/"
SOURCE_NAME = "モバイルミックス"

# Apple Store Japan 購入ページURL（シリーズ名 → URL）
APPLE_BUY_URLS: dict[str, str] = {
    "iPhone 17 Pro Max": "https://www.apple.com/jp/shop/buy-iphone/iphone-17-pro",
    "iPhone 17 Pro":     "https://www.apple.com/jp/shop/buy-iphone/iphone-17-pro",
    "iPhone Air":        "https://www.apple.com/jp/shop/buy-iphone/iphone-air",
    "iPhone 17":         "https://www.apple.com/jp/shop/buy-iphone/iphone-17",
    "iPhone 17e":        "https://www.apple.com/jp/shop/buy-iphone/iphone-17e",
}

# Apple Store Japan スクレイピング対象ページ
# (URL, ラベル) — "pro_page" は Pro Max / Pro 両方含むため href で判別
APPLE_PAGES = [
    ("https://www.apple.com/jp/shop/buy-iphone/iphone-17-pro", "pro_page"),
    ("https://www.apple.com/jp/shop/buy-iphone/iphone-air",    "iPhone Air"),
    ("https://www.apple.com/jp/shop/buy-iphone/iphone-17",     "iPhone 17"),
    ("https://www.apple.com/jp/shop/buy-iphone/iphone-17e",    "iPhone 17e"),
]

_apple_cache: dict = {"data": {}, "fetched_at": 0, "ttl": 3600}  # 1時間キャッシュ

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_cache = {"data": None, "fetched_at": 0, "ttl": 600}  # 10分キャッシュ


def scrape_apple_prices() -> dict[str, int]:
    """
    Apple Store Japan から各モデルの公式新品価格（税込）をスクレイピング。
    戻り値キー: "シリーズ名|容量"  例: "iPhone 17 Pro Max|256GB" → 194800

    各ページの div.equalize-capacity-button-height 内に
      <a href="...6.9インチ..."> (Pro Max) / <a href="...6.3インチ..."> (Pro)
      <span class="current_price">¥194,800</span>
    という構造が存在する（2025年以降の Apple Store JP 共通構造）。
    """
    now = time.time()
    if _apple_cache["data"] and (now - _apple_cache["fetched_at"]) < _apple_cache["ttl"]:
        return _apple_cache["data"]

    prices: dict[str, int] = {}

    for url, label in APPLE_PAGES:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding
            soup = BeautifulSoup(resp.text, "lxml")

            items = soup.find_all(
                "div",
                class_=lambda c: c and "equalize-capacity-button-height" in c
            )

            for item in items:
                # --- 容量 ---
                text = item.get_text(" ", strip=True)
                m_cap = re.search(r"(\d+\s*(?:GB|TB))", text, re.IGNORECASE)
                if not m_cap:
                    continue
                storage = m_cap.group(1).replace(" ", "").upper()

                # --- 価格 ---
                price_el = (
                    item.find("span", class_="current_price")
                    or item.find("span", class_=lambda c: c and "price" in c)
                )
                if not price_el:
                    continue
                price_str = re.sub(r"[^\d]", "", price_el.get_text(strip=True))
                if not price_str:
                    continue
                price = int(price_str)

                # --- シリーズ名 ---
                if label == "pro_page":
                    a_tag = item.find("a")
                    href  = a_tag.get("href", "") if a_tag else ""
                    # href に 6.9 (= 6.9インチ = Pro Max) か 6.3 (= Pro) が入る
                    if "6.9" in href:
                        series = "iPhone 17 Pro Max"
                    elif "6.3" in href:
                        series = "iPhone 17 Pro"
                    else:
                        # href が取れない場合は Pro Max / Pro を容量で推定
                        # 2TB は Pro Max のみ
                        series = "iPhone 17 Pro Max" if storage == "2TB" else "iPhone 17 Pro"
                else:
                    series = label

                key = f"{series}|{storage}"
                prices[key] = price

        except Exception:
            # ページ取得失敗時はそのモデルはスキップ（既存キャッシュがあれば使い続ける）
            pass

    if prices:
        _apple_cache["data"]       = prices
        _apple_cache["fetched_at"] = now

    return _apple_cache["data"] or prices


def parse_price(text: str) -> int | None:
    cleaned = re.sub(r"[^\d]", "", (text or "").strip())
    return int(cleaned) if cleaned else None


def parse_series(model_full: str) -> tuple[str, str]:
    """
    "iPhone 17 Pro Max 256GB" → ("iPhone 17 Pro Max", "256GB")
    容量パターン: 数字+GB/TB で分割。
    """
    m = re.search(r"(\d+\s*(?:GB|TB))\s*$", model_full, re.IGNORECASE)
    if m:
        storage = m.group(1).replace(" ", "")
        series  = model_full[:m.start()].strip()
        return series, storage
    return model_full.strip(), ""


def scrape_mobilemix() -> dict:
    """
    モバイルミックス (https://mobile-mix.jp/) のiPhone買取価格をスクレイピング。

    ページ構造（テーブル1本）:
        奇数行: <tr id="XXX">
                  <td class="product" name="model">機種名</td>
                  <td class="price" id="modelXXX">価格</td>
                </tr>
        偶数行: <tr>
                  <td class="open"><span>未開封/開封</span></td>
                  <td>カラー備考</td>
                  <td class="cart">...</td>
                </tr>
    """
    now = time.time()
    if _cache["data"] and (now - _cache["fetched_at"]) < _cache["ttl"]:
        return _cache["data"]

    resp = requests.get(SOURCE_URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding
    soup = BeautifulSoup(resp.text, "lxml")

    result = {
        "models":      [],
        "fetched_at":  int(now),
        "source_url":  SOURCE_URL,
        "source_name": SOURCE_NAME,
    }

    # 全 product行 を取得
    product_tds = soup.find_all("td", class_="product")
    if not product_tds:
        return result

    # series → rows のマップで集計
    series_map: dict[str, list] = {}
    series_order: list[str] = []

    for td in product_tds:
        row        = td.parent
        model_full = td.get_text(strip=True)
        price_td   = row.find("td", class_="price")
        price      = parse_price(price_td.get_text(strip=True)) if price_td else None
        if not price:
            continue

        # 続く偶数行（カラー備考・開封状態・カートリンク）
        color_note = ""
        cart_url   = ""
        next_row = row.find_next_sibling("tr")
        if next_row and not next_row.get("id"):
            cells = next_row.find_all("td")
            if len(cells) >= 2:
                color_note = cells[1].get_text(strip=True)
            # カートリンクを td.cart > a から取得
            cart_td = next_row.find("td", class_="cart")
            if cart_td:
                a = cart_td.find("a", href=True)
                if a:
                    href = a["href"].strip()
                    cart_url = href if href.startswith("http") else urljoin(SOURCE_URL, href)

        series, storage = parse_series(model_full)

        if series not in series_map:
            series_map[series] = []
            series_order.append(series)

        apple_prices  = scrape_apple_prices()
        apple_price   = apple_prices.get(f"{series}|{storage}")
        apple_buy_url = APPLE_BUY_URLS.get(series, "")

        series_map[series].append({
            "detail":         storage or model_full,
            "color_note":     color_note,
            "prices":         {"買取価格": price},
            "representative": price,
            "apple_price":    apple_price,
            "apple_buy_url":  apple_buy_url,
            "cart_url":       cart_url,
        })

    for series in series_order:
        result["models"].append({
            "name": series,
            "rows": series_map[series],
        })

    _cache["data"]       = result
    _cache["fetched_at"] = now
    return result


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/sw.js")
def service_worker():
    """Service Worker をルートスコープで配信"""
    resp = send_from_directory("static", "sw.js")
    resp.headers["Content-Type"]          = "application/javascript"
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"]          = "no-cache"
    return resp


@app.route("/api/prices")
def api_prices():
    try:
        return jsonify({"ok": True, "data": scrape_mobilemix()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    _cache["fetched_at"]       = 0
    _apple_cache["fetched_at"] = 0   # Apple価格も強制再取得
    try:
        return jsonify({"ok": True, "data": scrape_mobilemix()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
