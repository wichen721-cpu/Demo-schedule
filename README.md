# MLB 即時比分 CLI

使用 MLB 官方公開 API 追蹤當天賽事比分的終端機工具。

## 安裝

```bash
pip install -r requirements.txt
```

## 使用方式

列出當天所有賽事（單次查詢）：

```bash
python mlb_live.py
```

指定日期：

```bash
python mlb_live.py --date 2026-08-29
```

輪詢模式，每 15 秒自動更新一次畫面（Ctrl+C 結束）：

```bash
python mlb_live.py --watch
```

自訂更新間隔（秒）：

```bash
python mlb_live.py --watch --interval 30
```

## 顯示內容

- 對戰組合與比賽狀態（未開打 / 進行中 / 已結束）
- 進行中比賽的即時比分、局數（上半/下半）、出局數、好壞球數、壘包跑者狀態
- API 逾時或連線失敗時會顯示錯誤訊息，不會導致程式崩潰
