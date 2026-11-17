"""
ETF 每日紀錄（先以元大 0050 實作）

來源：元大投信「申購買回清單」頁 https://www.yuantaetfs.com/tradeInfo/pcf/<代號>
      頁面內嵌的 pcfData 同時包含：基金概況、完整持股權重（股票／期貨）、實物申購買回清單
      元大約 16:15 上傳當日資料；網站只提供當日，因此每天記錄、逐日累積

儲存：data/etf/<代號>/YYYY-MM-DD.json（以資料的交易日命名）
網站：_site/data/etf/<代號>/index.json（日期清單）、_site/data/etf/<代號>/YYYY-MM-DD.json（含與前一筆紀錄的增減）
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import requests

import twdata

ETFS = ["0050"]
ROOT = Path(__file__).resolve().parent


def fetch(code: str) -> dict:
    r = requests.get(f"https://www.yuantaetfs.com/tradeInfo/pcf/{code}", timeout=60,
                     headers={"User-Agent": twdata.HEADERS["User-Agent"], "Accept-Language": "zh-TW,zh;q=0.9"})
    r.raise_for_status()
    out = subprocess.run(["node", str(ROOT / "etf_extract.js")], input=r.text, capture_output=True,
                         text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(f"{code} 解析失敗：{out.stderr.strip()[:200]}")
    pcf = json.loads(out.stdout)
    p, fw = pcf.get("PCF") or {}, pcf.get("FundWeights") or {}
    td = str(p.get("trandate") or "")
    if len(td) != 8:
        raise RuntimeError(f"{code} 無交易日")
    ben = p.get("Beneficiary") or {}
    return {
        "code": code, "date": f"{td[:4]}-{td[4:6]}-{td[6:]}", "name": p.get("fundname"), "fullname": p.get("fullname"),
        "updated": p.get("upddate"), "ann_date": p.get("anndate"),
        "summary": {
            "totalav": p.get("totalav"), "nav": p.get("nav"), "osunit": p.get("osunit"),
            "issuesdiff": p.get("issuesdiff"), "baseunit": p.get("baseunit"),
            "estcvalue": p.get("estcvalue"), "estdvalue": p.get("estdvalue"), "cashdiff": p.get("cashdiff"),
            "beneficiaries": ben.get("bf_cnt_a"), "ben_month": ben.get("doc_ym"),
            "stkvalues": (fw.get("Summary") or {}).get("stkvalues"), "futvalues": (fw.get("Summary") or {}).get("futvalues"),
        },
        "stocks": [{"c": s["code"], "n": s["name"], "q": s["qty"], "w": s["weights"]} for s in fw.get("StockWeights") or []],
        "futures": [{"c": s["code"], "n": s["name"], "ym": s.get("ym"), "q": s["qty"], "w": s["weights"]}
                    for s in fw.get("FutureWeights") or []],
        "inkind": [{"c": s["stkcd"], "n": s["name"], "q": s["qty"], "cash": s.get("cashinlieu"), "min": s.get("minimum")}
                   for s in (pcf.get("InKind") or {}).get("FundComposition") or []],
        "memo": pcf.get("Memo") or [],
    }


def update(data: Path, log=print):
    for code in ETFS:
        try:
            doc = fetch(code)
        except Exception as e:  # noqa: BLE001
            log(f"etf {code}: 失敗 {e}")
            continue
        folder = data / "etf" / code
        folder.mkdir(parents=True, exist_ok=True)
        p = folder / f"{doc['date']}.json"
        old = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
        if old and old.get("updated") == doc["updated"]:
            continue
        p.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        log(f"etf {code}: {doc['date']} 持股 {len(doc['stocks'])} 檔、申購籃 {len(doc['inkind'])} 檔"
            f"（上傳 {doc['updated']}）")


def write(data: Path, site: Path):
    for code in ETFS:
        files = sorted((data / "etf" / code).glob("20*.json"))
        if not files:
            continue
        out = site / "data" / "etf" / code
        out.mkdir(parents=True, exist_ok=True)
        prev = None
        dates = []
        for p in files:
            doc = json.loads(p.read_text(encoding="utf-8"))
            # 與前一筆紀錄比較：持股股數／權重增減、新增與剔除
            if prev:
                pq = {s["c"]: s for s in prev["stocks"]}
                for s in doc["stocks"]:
                    o = pq.get(s["c"])
                    s["dq"] = None if o is None else s["q"] - o["q"]
                    s["dw"] = None if o is None else round(s["w"] - o["w"], 2)
                    s["new"] = o is None
                cur = {s["c"] for s in doc["stocks"]}
                doc["removed"] = [{"c": s["c"], "n": s["n"], "q": s["q"], "w": s["w"]} for s in prev["stocks"] if s["c"] not in cur]
                doc["prev_date"] = prev["date"]
            prev = json.loads(p.read_text(encoding="utf-8"))
            (out / p.name).write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            dates.append(doc["date"])
        (out / "index.json").write_text(json.dumps({"code": code, "name": doc["name"], "dates": dates}, ensure_ascii=False),
                                        encoding="utf-8")
        print(f"etf {code}: {len(dates)} 天，最新 {dates[-1]}")
