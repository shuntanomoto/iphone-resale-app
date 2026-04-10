import re
import time
from flask import Flask, render_template, jsonify
import requests
from bs4 import BeautifulSoup

app = Flask(__name__)

SOURCE_URL  = "https://mobile-mix.jp/"
SOURCE_NAME = "モバイルミックス"

# Apple Store Japan 公式新品価格（円・税込・SIMフリー）
# キー: "シリーズ名|容量"
APPLE_PRICES: dict[str, int] = {
    "iPhone 17 Pro Max|256GB": 194800,
    "iPhone 17 Pro Max|512GB": 229800,
    "iPhone 17 Pro Max|1TB":   264800,
    "iPhone 17 Pro Max|2TB":   329800,
    "iPhone 17 Pro|256GB":     179800,
    "iPhone 17 Pro|512GB":     214800,
    "iPhone 17 Pro|1TB":       249800,
    "iPhone Air|256GB":        159800,
    "iPhone Air|512GB":        194800,
    "iPhone Air|1TB":          229800,
    "iPhone 17|256GB":         129800,
    "iPhone 17|512GB":         164800,
    "iPhone 17e|256GB":         99800,
    "iPhone 17e|512GB":        134800,
}

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

        # 続く偶数行（カラー備考・開封状態）
        color_note = ""
        next_row = row.find_next_sibling("tr")
        if next_row and not next_row.get("id"):
            cells = next_row.find_all("td")
            if len(cells) >= 2:
                color_note = cells[1].get_text(strip=True)

        series, storage = parse_series(model_full)

        if series not in series_map:
            series_map[series] = []
            series_order.append(series)

        apple_price = APPLE_PRICES.get(f"{series}|{storage}")

        series_map[series].append({
            "detail":         storage or model_full,
            "color_note":     color_note,
            "prices":         {"買取価格": price},
            "representative": price,
            "apple_price":    apple_price,
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


@app.route("/api/prices")
def api_prices():
    try:
        return jsonify({"ok": True, "data": scrape_mobilemix()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    _cache["fetched_at"] = 0
    try:
        return jsonify({"ok": True, "data": scrape_mobilemix()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
