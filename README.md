# 台股儀表板

追蹤台股市場均線風向，每日盤後由 GitHub Actions 自動更新並發佈到 GitHub Pages。

## 分頁一：市場均線風向
- 加權指數日 K 線 + 成交金額
- 收盤價 **高於 5 日均價** 的普通股家數 / 比例
- 收盤價 **高於 20 日均價** 的普通股家數 / 比例
- 兩圖時間軸與十字線同步；可切換「家數 / 比例 %」與 3M / 6M / 1Y / 全部
- 盤中（9:00–13:30）每 10 分鐘以全市場即時報價（經 Worker）計算今日家數並更新今日 K 棒；收盤後由排程換成官方資料

## 分頁二：貢獻點數
- 上市市值前 100 大普通股，對加權指數的正 / 負貢獻點數，各顯示前 20 名，其餘可展開
- 貢獻點數 = 漲跌 × 發行股數 ÷ 除數；除數 = 上市總市值 ÷ 加權指數（與證交所編算邏輯一致，實測全體加總與大盤漲跌誤差約 0.1%）
- 盤後：每日排程以官方收盤資料計算（`data/shares_twse.csv` 為每日更新的發行股數）
- 盤中（9:00–13:30）：網頁每 15 秒透過 Cloudflare Worker 中繼抓證交所即時行情計算

### 設定盤中即時報價（Cloudflare Worker，免費）
1. 註冊 / 登入 https://dash.cloudflare.com
2. 左側 **Workers & Pages → Create → Create Worker**，名稱例如 `tw-quote`，按 Deploy
3. 按 **Edit code**，把 `worker/quote-proxy.js` 的內容整段貼上覆蓋，按 **Deploy**
4. 複製 Worker 網址（例如 `https://tw-quote.<帳號>.workers.dev`），填入 `web/config.json` 的 `quoteProxy`
5. Commit 後自動部署；開盤時間打開「貢獻點數」分頁即會顯示「● 盤中即時」

## 分頁三：成交重心股
- 上市櫃普通股當日成交值前 30 名，含成交價、漲跌幅、成交值、成交量
- 盤中：每 15 秒透過 Worker 抓即時行情，成交值以「累積成交量 × (最高 + 最低 + 成交價) ÷ 3」估算；追蹤近 5 日成交值前 200 大的候選池
- 盤後：每日排程以官方成交金額排名
- 需要 v2 版 Worker（支援上櫃 `otc=` 參數），更新方式同下方「設定盤中即時報價」第 3 步

## 分頁四：鉅額交易
- 上市（證交所 BFIAUU 單一證券）＋上櫃（櫃買中心 鉅額交易個股最新行情）合併顯示，含股票、ETF 等所有證券
- 每個交易日台北時間約 21:00 自動抓取；日曆可回看 2026 年以來每一天，格子數字為當日鉅額成交金額（億）
- 資料存於 `data/block/YYYY-MM.csv`，`data/block/dates.csv` 記錄已抓取日期

## 分頁五：可轉債
- **突破轉換價**：前一交易日標的股收盤 < 轉換價、今日股價 ≥ 轉換價；盤中每 10 分鐘以即時報價更新，盤後顯示當日結果
- **成交量前 30 名**：櫃買中心每日可轉債行情（等價成交）依成交張數排序，附轉換價值與溢價率
- 來源：櫃買中心 轉(交)換債日統計報表 `RSta0113`（行情）、`RSdrs001`（轉換公司債資訊看板，含最新轉換價）

## 分頁六：櫃買熱門股
- 櫃買中心「熱門股證券商進出排行」30 檔，每檔前 10 大券商買賣量，以小卡片呈現
- 卡片標示前 10 大券商中外資券商的合計買超／賣超
- 櫃買中心 10:00、11:00、12:00 更新，GitHub 排程於 10:10、11:10、12:10 抓取並部署（櫃買中心會阻擋 Cloudflare Worker，故不經 Worker）

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
  breadth.csv               每日 高於5日/20日均價 家數與分母
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
