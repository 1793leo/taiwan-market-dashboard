"""
可轉債（櫃買中心 轉(交)換債日統計報表）

  RSta0113：每日轉(交)換公司債買賣斷交易行情表 → 成交量排行
  RSdrs001：轉換公司債資訊看板（含最新轉換價格、標的股價）→ 突破轉換價

儲存：data/cb/quotes/YYYY-MM.csv（每日行情，等價成交）、data/cb/board.csv（最新資訊看板）
      data/cb/breakouts.csv（每日突破轉換價紀錄，2026 年起）、data/cb/breakout_dates.csv（已計算日期）
網站：_site/data/cb.json、_site/data/cb_hist.json

突破轉換價：前一交易日標的收盤價 < 轉換價，且當日價格 ≥ 轉換價。
標的股票 = 可轉債代號前 4 碼；若資訊看板的標的股價與該股收盤價不符（交換債等），不列入突破判斷。
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import time
from pathlib import Path

import pandas as pd
import requests

import twdata

TOP_N = 30
HIST_START = dt.date(2026, 1, 1)
HIST_COLS = ["date", "c", "n", "s", "sn", "m", "conv", "prev", "p", "cb"]
BASE = "https://www.tpex.org.tw/storage/bond_zone/tradeinfo/cb"


def _fetch_csv(kind: str, day: dt.date) -> list[dict]:
    url = f"{BASE}/{day:%Y}/{day:%Y%m}/{kind}.{day:%Y%m%d}-C.csv"
    r = requests.get(url, timeout=60, headers={"User-Agent": twdata.HEADERS["User-Agent"], "Accept": "*/*"})
    if r.status_code != 200 or b"HEADER" not in r.content[:5000]:
        raise twdata.NoData(f"{kind} {day} 尚未公布")
    text = r.content.decode("cp950", errors="replace")
    header, rows = None, []
    for rec in csv.reader(io.StringIO(text)):
        if not rec:
            continue
        tag, vals = rec[0], [v.strip() for v in rec[1:]]
        if tag == "HEADER":
            header = vals
        elif tag == "BODY" and header:
            rows.append(dict(zip(header, vals)))
    if not rows:
        raise twdata.NoData(f"{kind} {day} 無資料")
    return rows


def fetch_quotes(day: dt.date) -> list[dict]:
    out, last = [], None
    for r in _fetch_csv("RSta0113", day):
        code = r.get("代號", "")
        if code:
            last = {"code": code, "name": r.get("名稱", "")}
        if not last or r.get("交易") != "等價":
            continue
        out.append({**last, "close": twdata.num(r.get("收市")), "chg": twdata.num(r.get("漲跌", "").replace(" ", "")),
                    "units": twdata.num(r.get("單位")) or 0, "amount": twdata.num(r.get("金額")) or 0,
                    "ref": twdata.num(r.get("明日參價"))})
    return out


def fetch_board(day: dt.date) -> list[dict]:
    out = []
    for r in _fetch_csv("RSdrs001", day):
        out.append({"code": r.get("債券代碼", ""), "name": r.get("債券簡稱", ""),
                    "conv": twdata.num(r.get("轉換價格")), "next_date": r.get("下次轉換價格生效日期", ""),
                    "cb_ref": twdata.num(r.get("轉債參考價格")), "stock_px": twdata.num(r.get("轉換標的股票價格")),
                    "outstanding": twdata.num(r.get("上月底發行餘額")), "end_date": r.get("終止櫃檯買賣日", ""),
                    "halt_from": r.get("停止交易起日", ""), "halt_to": r.get("停止交易迄日", "")})
    return out


# ---------------------------------------------------------------- storage
def update(data: Path, trading_days: list[dt.date], log=print, deadline: float | None = None):
    folder = data / "cb"
    (folder / "quotes").mkdir(parents=True, exist_ok=True)
    have = set()
    for p in (folder / "quotes").glob("*.csv"):
        have |= set(pd.read_csv(p, usecols=["date"])["date"])
    # 行情：補最近 10 個交易日
    for d in trading_days[-10:]:
        if d.isoformat() in have:
            continue
        try:
            rows = fetch_quotes(d)
        except twdata.NoData as e:
            log(f"cb: {e}")
            continue
        except Exception as e:  # noqa: BLE001
            log(f"cb: 行情 {d} 失敗 {e}")
            continue
        p = folder / "quotes" / f"{d:%Y-%m}.csv"
        new = pd.DataFrame([{**r, "date": d.isoformat()} for r in rows])
        if p.exists():
            new = pd.concat([pd.read_csv(p, dtype={"code": str}), new]).drop_duplicates(["date", "code"], keep="last")
        new.sort_values(["date", "code"]).to_csv(p, index=False)
        log(f"cb: 行情 {d} {len(rows)} 檔")
        time.sleep(2)
    # 資訊看板：抓最新一個已公布的交易日
    bp = folder / "board.csv"
    cur = pd.read_csv(bp, dtype={"code": str})["date"].iloc[0] if bp.exists() else ""
    for d in reversed(trading_days[-5:]):
        if d.isoformat() <= cur:
            break
        try:
            rows = fetch_board(d)
        except twdata.NoData as e:
            log(f"cb: {e}")
            continue
        except Exception as e:  # noqa: BLE001
            log(f"cb: 資訊看板 {d} 失敗 {e}")
            continue
        pd.DataFrame([{**r, "date": d.isoformat()} for r in rows]).to_csv(bp, index=False)
        log(f"cb: 資訊看板 {d} {len(rows)} 檔")
        break
    update_history(data, trading_days, log, deadline)


def update_history(data: Path, trading_days: list[dt.date], log=print, deadline: float | None = None):
    """逐日以當日資訊看板（當日轉換價）＋股價計算突破轉換價，寫入紀錄；可中斷續算"""
    folder = data / "cb"
    hp, dp = folder / "breakouts.csv", folder / "breakout_dates.csv"
    done = set(pd.read_csv(dp)["date"]) if dp.exists() else set()
    st = _stocks(data, since=f"{HIST_START.year - 1}-12")
    sdates = sorted(st["date"].unique())
    todo = [d for d in trading_days if d >= HIST_START and d.isoformat() not in done and d.isoformat() in sdates]
    if todo:
        log(f"cb: 突破紀錄需計算 {len(todo)} 天")
    rows_all, marks = [], []
    for k, d in enumerate(todo):
        if deadline and time.time() > deadline:
            log(f"cb: 達時間上限，剩 {len(todo) - k} 天下次續算")
            break
        try:
            board = pd.DataFrame(fetch_board(d))
        except twdata.NoData:
            continue                       # 尚未公布，下次再算
        except Exception as e:  # noqa: BLE001
            log(f"cb: 資訊看板 {d} 失敗 {e}")
            continue
        br = compute_breakouts(board, d.isoformat(), st, sdates)
        rows_all += [{**b, "date": d.isoformat()} for b in br]
        marks.append({"date": d.isoformat(), "count": len(br)})
        if (k + 1) % 20 == 0:
            log(f"cb: 突破紀錄 {d} ({k + 1}/{len(todo)})")
        time.sleep(1.5)
    if marks:
        new = pd.DataFrame(rows_all, columns=HIST_COLS)
        if hp.exists():
            old = pd.read_csv(hp, dtype={"c": str, "s": str})
            new = pd.concat([old[~old["date"].isin([m["date"] for m in marks])], new])
        new.sort_values(["date", "c"]).to_csv(hp, index=False)
        idx = pd.concat([pd.read_csv(dp), pd.DataFrame(marks)]) if dp.exists() else pd.DataFrame(marks)
        idx.drop_duplicates("date", keep="last").sort_values("date").to_csv(dp, index=False)
        log(f"cb: 突破紀錄新增 {len(marks)} 天、{len(rows_all)} 筆")


# ---------------------------------------------------------------- site
def _stocks(data: Path, since: str | None = None) -> pd.DataFrame:
    frames = []
    for market, ex in (("twse", "tse"), ("tpex", "otc")):
        files = sorted((data / "stocks" / market).glob("*.csv"))
        for p in (files[-2:] if since is None else [f for f in files if f.stem >= since]):
            f = pd.read_csv(p, dtype={"code": str}, usecols=["date", "code", "name", "close"])
            f["m"] = ex
            frames.append(f)
    return pd.concat(frames).dropna(subset=["close"]).drop_duplicates(["date", "code"], keep="last")


def compute_breakouts(board: pd.DataFrame, d: str, st: pd.DataFrame, sdates: list[str]) -> list[dict]:
    """前一交易日標的收盤 < 當日轉換價 ≤ 當日收盤；標的需與資訊看板股價相符（排除交換債等）"""
    if d not in sdates or sdates.index(d) == 0:
        return []
    today = st[st["date"] == d].set_index("code")
    prev = st[st["date"] == sdates[sdates.index(d) - 1]].set_index("code")["close"]
    out = []
    for r in board.itertuples():
        conv = float(r.conv or 0)
        if conv <= 0 or str(r.end_date or "").strip() not in ("", "nan"):
            continue
        s = str(r.code)[:4]
        if s not in today.index or s not in prev.index or not r.stock_px:
            continue
        close = float(today.at[s, "close"])
        if abs(float(r.stock_px) / close - 1) >= 0.02:
            continue
        pv = float(prev[s])
        if pv < conv <= close:
            out.append({"c": str(r.code), "n": r.name, "s": s, "sn": today.at[s, "name"], "m": today.at[s, "m"],
                        "conv": conv, "prev": pv, "p": close, "cb": float(r.cb_ref) if r.cb_ref else None})
    return sorted(out, key=lambda x: x["c"])


def write_history(data: Path, site: Path):
    hp, dp = data / "cb" / "breakouts.csv", data / "cb" / "breakout_dates.csv"
    if not dp.exists():
        return
    dates = {r.date: int(r.count) for r in pd.read_csv(dp).itertuples()}
    rows = {}
    if hp.exists():
        h = pd.read_csv(hp, dtype={"c": str, "s": str})
        for d, g in h.groupby("date"):
            rows[d] = [[r.c, r.n, r.s, r.sn, r.m, r.conv, r.prev, r.p, None if pd.isna(r.cb) else r.cb] for r in g.itertuples()]
    (site / "data" / "cb_hist.json").write_text(json.dumps({"dates": dates, "rows": rows}, ensure_ascii=False,
                                                           separators=(",", ":")), encoding="utf-8")
    print(f"cb 突破紀錄：{len(dates)} 天、{sum(dates.values())} 筆")


def write(data: Path, site: Path):
    (site / "data").mkdir(parents=True, exist_ok=True)
    write_history(data, site)
    folder = data / "cb"
    bp = folder / "board.csv"
    qfiles = sorted((folder / "quotes").glob("*.csv"))
    if not bp.exists() or not qfiles:
        print("cb: 尚無資料")
        return
    board = pd.read_csv(bp, dtype={"code": str}).fillna("")
    bdate = board["date"].iloc[0]
    st = _stocks(data)
    sdates = sorted(st["date"].unique())

    def closes(d):
        return st[st["date"] == d].set_index("code")

    # 以資訊看板日期為基準日；需有該日與前一日的股價
    if bdate not in sdates:
        print(f"cb: 股價缺 {bdate}，略過")
        return
    i = sdates.index(bdate)
    today, prev = closes(bdate), closes(sdates[i - 1]) if i > 0 else None

    board = board[(board["conv"].astype(float) > 0) & (board["end_date"] == "")].copy()
    board["s"] = board["code"].str[:4]
    board["conv"] = board["conv"].astype(float)

    def matched(r):
        """標的 = 前 4 碼，且資訊看板的標的股價與該股收盤一致（排除交換債等）"""
        if r.s not in today.index or not r.stock_px:
            return False
        return abs(float(r.stock_px) / float(today.at[r.s, "close"]) - 1) < 0.02

    board["ok"] = [matched(r) for r in board.itertuples()]
    ok = board[board["ok"]].copy()
    ok["sname"] = ok["s"].map(today["name"])
    ok["m"] = ok["s"].map(today["m"])
    ok["close"] = ok["s"].map(today["close"]).astype(float)
    ok["prev"] = ok["s"].map(prev["close"]).astype(float) if prev is not None else float("nan")

    # 盤後：基準日突破（與歷史紀錄同一套算法）
    raw = pd.read_csv(bp, dtype={"code": str}).fillna("")
    breakout = compute_breakouts(raw, bdate, st, sdates)

    # 盤中監看名單：基準日收盤仍低於轉換價者（下一個交易日若突破即列出）
    w = ok[ok["close"] < ok["conv"]]
    watch = [[r.code, r.name, r.s, r.sname, r.m, r.conv, r.close, float(r.cb_ref) if r.cb_ref else None]
             for r in w.itertuples()]

    # 成交量前 30（行情最新一日）
    q = pd.concat([pd.read_csv(p, dtype={"code": str}) for p in qfiles[-2:]])
    qdate = q["date"].max()
    q = q[(q["date"] == qdate) & (q["units"] > 0)].sort_values(["units", "amount"], ascending=False).head(TOP_N)
    binfo = board.set_index("code")
    top = []
    for r in q.itertuples():
        b = binfo.loc[r.code] if r.code in binfo.index else None
        conv = float(b["conv"]) if b is not None else None
        spx = float(b["stock_px"]) if b is not None and b["stock_px"] != "" else None
        if b is not None and bool(b["ok"]) and b["s"] in today.index and qdate == bdate:
            spx = float(today.at[b["s"], "close"])
        parity = 100 * spx / conv if conv and spx else None
        top.append({"c": r.code, "n": r.name, "p": r.close, "chg": None if pd.isna(r.chg) else r.chg,
                    "v": int(r.units), "amt": int(r.amount), "s": r.code[:4],
                    "sp": spx, "conv": conv, "parity": round(parity, 2) if parity else None,
                    "prem": round((r.close / parity - 1) * 100, 2) if parity and r.close == r.close and r.close else None})

    out = {"date": bdate, "qdate": qdate, "breakout": breakout, "watch": watch, "top": top}
    (site / "data").mkdir(parents=True, exist_ok=True)
    (site / "data" / "cb.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":"), default=float),
                                           encoding="utf-8")
    print(f"cb {bdate}: 突破 {len(breakout)} / 監看 {len(watch)} / 成交量前{TOP_N}（{qdate}）")
