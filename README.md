# 台股儀表板

追蹤台股市場寬度，每日盤後由 GitHub Actions 自動更新並發佈到 GitHub Pages。

## 分頁一：市場寬度
- 加權指數日 K 線 + 成交金額
- 收盤價 **低於 5 日均價** 的普通股家數 / 比例
- 收盤價 **低於 20 日均價** 的普通股家數 / 比例
- 兩圖時間軸與十字線同步；可切換「家數 / 比例 %」與 3M / 6M / 1Y / 全部

## 資料範圍
| 資料 | 來源 | 欄位 |
|---|---|---|
| 上市普通股 | 證交所 `MI_INDEX`（ALLBUT0999） | 開、高、低、收、成交股數 |
| 上櫃普通股 | 櫃買中心 `afterTrading/otc`（EW） | 開、高、低、收、成交股數 |
| 加權指數 | 證交所 `MI_5MINS_HIST` + `FMTQIK` | 開、高、低、收、成交股數、成交金額 |

普通股篩選：代號為 4 位數字且首碼非 0。排除 ETF / 主動式 ETF（00xx、00xxxA）、特別股（如 2881A）、TDR（91xxxx）、權證（6 碼）、可轉債（5 碼）。

```
data/
  taiex.csv                 加權指數 OHLCV
  stocks/twse/YYYY-MM.csv   上市普通股日 K（每月一檔）
  stocks/tpex/YYYY-MM.csv   上櫃普通股日 K
  breadth.csv               每日 低於5日/20日均價 家數與分母
web/                        前端原始碼
scripts/                    抓取與計算程式
```

## 部署步驟
1. 在 GitHub 建立新 repo，把本資料夾全部推上去：
   ```bash
   git init && git add . && git commit -m "init"
   git branch -M main
   git remote add origin https://github.com/<你的帳號>/tw-market-dashboard.git
   git push -u origin main
   ```
2. Repo → **Settings → Pages → Build and deployment → Source** 選 **GitHub Actions**。
3. Repo → **Settings → Actions → General → Workflow permissions** 選 **Read and write permissions**。
4. **Actions → 盤後更新 & 部署 → Run workflow**，第一次會回補 3 年資料（約 1～1.5 小時，因證交所有限流）。若中途被限流或超過時間，再按一次 Run workflow 會從缺口續抓。
5. 完成後網址為 `https://<你的帳號>.github.io/tw-market-dashboard/`。

之後每個交易日台北時間 15:40 自動更新，17:40 再補抓一次（以防資料晚公布）。

## 本機執行
```bash
pip install -r requirements.txt
python scripts/update.py --years 3      # 抓資料 + 產生 _site/
python -m http.server -d _site 8000     # 開 http://localhost:8000
```

## 計算口徑與限制
- 均價為個股近 N 個「有成交」交易日的收盤均價；分母為當日有收盤價且已累積 N 日資料的家數。
- 股價 **未還原除權息**，除權息當日可能讓個股被誤判為跌破均價。
- 回補起始的前 20 個交易日為均線暖機期，不輸出寬度值。
- GitHub runner 位於海外，證交所偶爾會限流或擋連線；程式有重試與續抓，失敗的日期會在下次排程自動補上。
- 證交所 / 櫃買若改版 API，請檢查 `scripts/twdata.py`（欄位以名稱比對，有一定容錯）。
