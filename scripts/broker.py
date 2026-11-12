"""
櫃買熱門股：櫃買中心「熱門股證券商進出排行（等價整股）」
盤中 10:00、11:00、12:00 更新；由 .github/workflows/broker.yml 於整點後 10 分鐘抓取。
儲存 data/broker/latest.json（最新一次）、data/broker/YYYY-MM-DD.json（當日各時段）
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "broker"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


def fetch() -> dict:
    last = None
    for _ in range(3):
        try:
            r = requests.post("https://www.tpex.org.tw/www/zh-tw/mostActive/brokerVol",
                              data={"response": "json"}, headers={"User-Agent": UA}, timeout=30)
            j = r.json()
            t = (j.get("tables") or [{}])[0]
            if t.get("data"):
                return {"subtitle": t.get("subtitle", ""), "fields": t.get("fields", []), "data": t["data"]}
            last = RuntimeError(f"無資料: {str(j)[:200]}")
        except Exception as e:  # noqa: BLE001
            last = e
    raise last  # type: ignore[misc]


def main() -> int:
    j = fetch()
    m = re.search(r"(\d+)年(\d+)月(\d+)日.*?截至\s*([\d:]+)", j["subtitle"])
    if not m:
        print("無法解析日期：", j["subtitle"])
        return 1
    day = f"{int(m[1]) + 1911}-{int(m[2]):02d}-{int(m[3]):02d}"
    j.update(date=day, asof=m[4])
    DATA.mkdir(parents=True, exist_ok=True)
    latest = DATA / "latest.json"
    if latest.exists():
        old = json.loads(latest.read_text(encoding="utf-8"))
        if old.get("date") == day and old.get("asof") == m[4]:
            print(f"資料未更新（{day} 截至 {m[4]}）")
            return 0
    latest.write_text(json.dumps(j, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    dp = DATA / f"{day}.json"
    hist = json.loads(dp.read_text(encoding="utf-8")) if dp.exists() else {}
    hist[m[4]] = j
    dp.write_text(json.dumps(hist, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"櫃買熱門股 {day} 截至 {m[4]}：{len(j['data'])} 筆")
    return 0


if __name__ == "__main__":
    sys.exit(main())
