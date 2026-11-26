
import json
import re
import os
import hashlib
from datetime import datetime, timezone, timedelta
from urllib.parse import quote
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# =========================
# 設定
# =========================

MIN_PRICE = 50000
MAX_PRICE = 80000
TOP_N = 10

BASE_DIR = Path(__file__).parent
REPORT_DIR = BASE_DIR / "reports"
SEEN_FILE = BASE_DIR / "seen_cars.json"

# 台灣時間
TZ_TAIWAN = timezone(timedelta(hours=8))
NOW = datetime.now(TZ_TAIWAN)
DATE_STR = NOW.strftime("%Y-%m-%d")

# 搜尋關鍵字
SEARCH_QUERIES = [
    '中古車 掀背車 5萬 8萬',
    '8891 掀背車 50000 80000',
    '中古 Honda Fit 8萬',
    '中古 Toyota Yaris 8萬',
    '中古 Nissan Tiida 8萬',
    '中古 Ford Focus 5D 8萬',
    '中古 Suzuki Swift 8萬',
    '中古 Mazda 3 5D 8萬',
]

# =========================
# 車款維修便利性評分
# =========================

POPULAR_MODELS = {
    "toyota yaris": 20,
    "yaris": 20,
    "honda fit": 20,
    "fit": 20,
    "nissan tiida": 19,
    "tiida": 19,
    "ford focus": 17,
    "focus": 17,
    "suzuki swift": 18,
    "swift": 18,
    "mazda 3": 17,
    "mazda3": 17,
    "mazda": 16,
    "toyota": 19,
    "honda": 19,
    "nissan": 18,
    "ford": 17,
    "suzuki": 18,
}

# =========================
# 歷史紀錄
# =========================

def load_seen():
    if SEEN_FILE.exists():
        try:
            return json.loads(SEEN_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_seen(data):
    SEEN_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

# =========================
# 搜尋
# =========================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/131.0 Safari/537.36"
    )
}

def search_web(query):
    url = "https://html.duckduckgo.com/html/?q=" + quote(query)

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=20
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        results = []

        for item in soup.select(".result"):
            title_tag = item.select_one(".result__title")
            link_tag = item.select_one(".result__url")
            snippet_tag = item.select_one(".result__snippet")

            if not title_tag:
                continue

            a_tag = title_tag.select_one("a")
            if not a_tag:
                continue

            title = a_tag.get_text(" ", strip=True)
            link = a_tag.get("href", "")
            snippet = (
                snippet_tag.get_text(" ", strip=True)
                if snippet_tag else ""
            )

            if not link or not link.startswith("http"):
                continue

            results.append({
                "title": title,
                "url": link,
                "snippet": snippet,
            })

        return results

    except Exception as e:
        print(f"搜尋失敗: {query} / {e}")
        return []

# =========================
# 車輛判斷
# =========================

HATCHBACK_KEYWORDS = [
    "掀背", "hatchback", "5d", "5門",
    "五門", "fit", "yaris", "swift",
    "tiida", "mazda3", "focus"
]

EXCLUDE_KEYWORDS = [
    "休旅", "suv", "貨車", "商用",
    "機車", "零件", "拆車", "報廢"
]

def is_candidate(text):
    lower = text.lower()

    if any(word.lower() in lower for word in EXCLUDE_KEYWORDS):
        return False

    return any(word.lower() in lower for word in HATCHBACK_KEYWORDS)

# =========================
# 價格擷取
# =========================

def extract_price(text):
    text = text.replace(",", "").replace("，", "")

    # 8萬元、5萬、6.5萬等格式
    patterns = [
        r'(\d+(?:\.\d+)?)\s*萬',
        r'(\d{5,6})\s*元',
        r'NT\$?\s*(\d{5,6})',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            value = float(match.group(1))

            if "萬" in pattern:
                value *= 10000

            value = int(value)

            if MIN_PRICE <= value <= MAX_PRICE:
                return value

    return None

def extract_year(text):
    match = re.search(r'(?:19|20)\d{2}', text)
    if match:
        return int(match.group(0))
    return None

def extract_mileage(text):
    text = text.replace(",", "")

    patterns = [
        r'(\d{1,6})\s*公里',
        r'(\d{1,6})\s*km',
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1))

    return None

# =========================
# 評分
# =========================

def score_car(car):
    score = 0

    # 價格25分
    if car["price"]:
        price = car["price"]

        if 50000 <= price <= 65000:
            score += 25
        elif 65001 <= price <= 75000:
            score += 22
        elif 75001 <= price <= 80000:
            score += 19

    # 年份15分
    year = car.get("year")
    if year:
        age = NOW.year - year

        if age <= 10:
            score += 15
        elif age <= 15:
            score += 12
        elif age <= 20:
            score += 9
        else:
            score += 5

    # 里程15分
    mileage = car.get("mileage")

    if mileage is not None:
        if mileage <= 100000:
            score += 15
        elif mileage <= 150000:
            score += 12
        elif mileage <= 200000:
            score += 9
        else:
            score += 5

    # 維修便利性20分
    model_score = 10
    title_lower = car["title"].lower()

    for model, points in POPULAR_MODELS.items():
        if model in title_lower:
            model_score = points
            break

    score += model_score

    # 刊登資料完整度10分
    completeness = 0

    if car.get("year"):
        completeness += 3
    if car.get("mileage") is not None:
        completeness += 3
    if car.get("price"):
        completeness += 2
    if car.get("snippet"):
        completeness += 2

    score += completeness

    # 賣家及車況資訊10分
    description_score = 0
    text = car["title"] + " " + car.get("snippet", "")

    quality_keywords = [
        "自售", "保養", "車況", "無事故",
        "原廠", "維修紀錄", "可看車"
    ]

    for word in quality_keywords:
        if word in text:
            description_score += 2

    score += min(description_score, 10)

    # 事故及車況透明度5分
    transparency = 0
    transparency_keywords = [
        "事故", "車況", "保養紀錄",
        "檢查", "實車"
    ]

    for word in transparency_keywords:
        if word in text:
            transparency += 1

    score += min(transparency, 5)

    return min(score, 100)

# =========================
# 主程式
# =========================

def main():
    REPORT_DIR.mkdir(exist_ok=True)

    seen = load_seen()
    candidates = {}

    print("開始搜尋二手掀背車...")

    for query in SEARCH_QUERIES:
        results = search_web(query)

        for result in results:
            text = result["title"] + " " + result["snippet"]

            if not is_candidate(text):
                continue

            price = extract_price(text)

            # 僅納入明確取得價格的候選
            if price is None:
                continue

            car_id = hashlib.sha256(
                result["url"].encode("utf-8")
            ).hexdigest()[:16]

            car = {
                "id": car_id,
                "title": result["title"],
                "url": result["url"],
                "snippet": result["snippet"],
                "price": price,
                "year": extract_year(text),
                "mileage": extract_mileage(text),
                "first_seen": seen.get(car_id, {}).get(
                    "first_seen", DATE_STR
                ),
                "last_seen": DATE_STR,
            }

            car["score"] = score_car(car)
            car["new"] = car_id not in seen

            candidates[car_id] = car

    # 分數排序
    sorted_cars = sorted(
        candidates.values(),
        key=lambda c: (
            c["score"],
            -c["price"]
        ),
        reverse=True
    )

    top_cars = sorted_cars[:TOP_N]

    # 更新歷史資料
    for car in candidates.values():
        seen[car["id"]] = {
            "first_seen": car["first_seen"],
            "last_seen": DATE_STR,
            "title": car["title"],
            "url": car["url"],
            "price": car["price"],
        }

    save_seen(seen)

    # 產生報告
    report = [
        f"# 台灣二手掀背車雷達 - {DATE_STR}",
        "",
        f"預算：NT$ {MIN_PRICE:,} - {MAX_PRICE:,}",
        "",
        f"搜尋候選數：{len(candidates)}",
        "",
        f"本週前 {TOP_N} 名",
        "",
    ]

    for i, car in enumerate(top_cars, 1):
        report.extend([
            f"## {i}. {car['title']}",
            "",
            f"- 評分：{car['score']}/100",
            f"- 價格：NT$ {car['price']:,}",
            f"- 年份：{car['year'] or '未取得'}",
            f"- 里程：{car['mileage'] or '未取得'}",
            f"- 本週新發現：{'是' if car['new'] else '否'}",
            f"- 網址：{car['url']}",
            f"- 資訊：{car['snippet']}",
            "",
        ])

    if not top_cars:
        report.extend([
            "本次沒有取得足夠資料的符合候選車輛。",
            "",
            "搜尋引擎結果可能不包含價格，請勿將空結果",
            "視為市場上沒有車輛。",
            "",
        ])

    report.extend([
        "",
        "注意：搜尋結果不是車況鑑定。請確認刊登價格、",
        "年份、里程及車況，並安排第三方驗車。",
        "",
    ])

    report_path = REPORT_DIR / f"{DATE_STR}.md"
    report_path.write_text(
        "\n".join(report),
        encoding="utf-8"
    )

    # 保存 JSON 方便未來分析
    json_path = REPORT_DIR / f"{DATE_STR}.json"
    json_path.write_text(
        json.dumps(top_cars, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"搜尋完成：{len(candidates)} 輛候選")
    print(f"報告：{report_path}")

if __name__ == "__main__":
    main()
