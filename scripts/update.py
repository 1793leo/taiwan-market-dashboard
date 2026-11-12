"""
增量更新：
  1. 更新加權指數 (data/taiex.csv)
  2. 以指數交易日為基準，補齊上市/上櫃普通股日 K (data/stocks/{twse,tpex}/YYYY-MM.csv)
  3. 計算市場均線風向、貢獻點數、成交重心股並輸出網站資料 (build.py)

第一次執行會自動回補 --years 年的資料；中途因時間上限中斷，下次執行會從缺口續抓。
用法: python scripts/update.py --years 3 --budget 300
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import threading
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import twdata  # noqa: E402
import build  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TAIEX_CSV = DATA / "taiex.csv"
STOCK_COLS = ["date", "code", "name", "open", "high", "low", "close", "volume", "change", "turnover"]
SHARES_CSV = DATA / "shares_twse.csv"
TPE = dt.timezone(dt.timedelta(hours=8))

FETCHERS = {
    "twse": (twdata.fetch_twse_stocks, 3.5),  # 證交所限流較嚴：約每 5 秒 3 次以內
    "tpex": (twdata.fetch_tpex_stocks, 2.5),
}


def log(*a):
    print(f"[{dt.datetime.now(TPE):%H:%M:%S}]", *a, flush=True)


def today_tpe() -> dt.date:
    return dt.datetime.now(TPE).date()


def month_iter(start: dt.date, end: dt.date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


# ---------------------------------------------------------------- TAIEX
def update_taiex(start: dt.date, end: dt.date) -> pd.DataFrame:
    df = pd.read_csv(TAIEX_CSV, parse_dates=["date"]) if TAIEX_CSV.exists() else pd.DataFrame()
    have_months = set()
    last = None
    if len(df):
        df["date"] = df["date"].dt.date
        have_months = {(d.year, d.month) for d in df["date"]}
        last = max(df["date"])
    rows = []
    for y, m in month_iter(start, end):
        # 缺的月份要抓；最後一個月份（可能不完整）及之後都重抓
        if (y, m) in have_months and last and (y, m) < (last.year, last.month):
            continue
        try:
            got = twdata.fetch_taiex_month(y, m)
            rows += got
            log(f"TAIEX {y}-{m:02d}: {len(got)} 天")
        except twdata.NoData:
            log(f"TAIEX {y}-{m:02d}: 無資料")
        except Exception as e:  # noqa: BLE001
            log(f"TAIEX {y}-{m:02d} 失敗: {e}")
        time.sleep(3.5)
    if rows:
        new = pd.DataFrame(rows)
        df = pd.concat([df, new]) if len(df) else new
        df = df.drop_duplicates("date", keep="last").sort_values("date")
        DATA.mkdir(parents=True, exist_ok=True)
        df.to_csv(TAIEX_CSV, index=False)
    return df


# ---------------------------------------------------------------- stocks
def month_file(market: str, y: int, m: int) -> Path:
    return DATA / "stocks" / market / f"{y}-{m:02d}.csv"


def have_dates(market: str) -> set[dt.date]:
    out = set()
    for p in (DATA / "stocks" / market).glob("*.csv"):
        s = pd.read_csv(p, usecols=["date"])["date"].unique()
        out |= {dt.date.fromisoformat(x) for x in s}
    return out


def save_rows(market: str, rows: list[dict]):
    if not rows:
        return
    new = pd.DataFrame(rows, columns=STOCK_COLS)
    new["date"] = new["date"].astype(str)
    for ym, part in new.groupby(new["date"].str[:7]):
        y, m = map(int, ym.split("-"))
        p = month_file(market, y, m)
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists():
            part = pd.concat([pd.read_csv(p, dtype={"code": str}), part])
        part = part.drop_duplicates(["date", "code"], keep="last").sort_values(["date", "code"])
        part.to_csv(p, index=False)


def backfill_market(market: str, days: list[dt.date], deadline: float, report: dict):
    fetch, pause = FETCHERS[market]
    missing = sorted(set(days) - have_dates(market))
    log(f"{market}: 需抓取 {len(missing)} 天")
    buf, done, fail = [], 0, 0
    for i, d in enumerate(missing):
        if time.time() > deadline:
            log(f"{market}: 達到時間上限，剩 {len(missing) - i} 天下次續抓")
            break
        try:
            rows = fetch(d)
            buf += [{**r, "date": d.isoformat()} for r in rows]
            done += 1
            if done % 10 == 0 or i == len(missing) - 1:
                log(f"{market}: {d} ({i + 1}/{len(missing)}) {len(rows)} 檔")
        except twdata.NoData:
            log(f"{market}: {d} 尚無資料")
        except Exception as e:  # noqa: BLE001
            fail += 1
            log(f"{market}: {d} 失敗 {e}")
            time.sleep(30)
        if len(buf) > 20000:
            save_rows(market, buf)
            buf = []
        time.sleep(pause)
    save_rows(market, buf)
    report[market] = {"fetched": done, "failed": fail, "remaining": len(missing) - done}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=float, default=3)
    ap.add_argument("--budget", type=float, default=300, help="抓取時間上限(分鐘)")
    ap.add_argument("--skip-fetch", action="store_true", help="只重算寬度/網站")
    ap.add_argument("--site", default=str(ROOT / "_site"))
    args = ap.parse_args()

    end = today_tpe()
    start = end - dt.timedelta(days=int(365.25 * args.years))
    if not args.skip_fetch:
        deadline = time.time() + args.budget * 60
        tx = update_taiex(start, end)
        if not len(tx):
            sys.exit("無法取得加權指數資料（證交所連線失敗？）")
        days = sorted(d for d in tx["date"] if d >= start)
        log(f"交易日 {len(days)} 天：{days[0]} ~ {days[-1]}")
        report: dict = {}
        threads = [threading.Thread(target=backfill_market, args=(m, days, deadline, report)) for m in FETCHERS]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        log("抓取結果:", report)
        ensure_latest_change(days[-1])
        update_shares()
    build.build(DATA, Path(args.site), start)


def ensure_latest_change(day: dt.date):
    """貢獻點數需要最新交易日的『漲跌價差』；舊資料沒有此欄位時補抓一次"""
    p = month_file("twse", day.year, day.month)
    if not p.exists():
        return
    df = pd.read_csv(p, dtype={"code": str})
    cur = df[df["date"] == day.isoformat()]
    if len(cur) and "change" in df.columns and cur["change"].notna().sum() > len(cur) * 0.5:
        return
    try:
        rows = twdata.fetch_twse_stocks(day)
        save_rows("twse", [{**r, "date": day.isoformat()} for r in rows])
        log(f"twse: {day} 補上漲跌價差")
    except Exception as e:  # noqa: BLE001
        log(f"twse: {day} 補漲跌價差失敗 {e}")


def update_shares():
    try:
        shares = twdata.fetch_twse_shares()
    except Exception as e:  # noqa: BLE001
        log(f"股本資料更新失敗，沿用舊資料: {e}")
        return
    pd.DataFrame(sorted(shares.items()), columns=["code", "shares"]).to_csv(SHARES_CSV, index=False)
    log(f"股本資料 {len(shares)} 檔")


if __name__ == "__main__":
    main()
