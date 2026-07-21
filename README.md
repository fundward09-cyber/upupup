# SK 海力士每日股价看板

跟踪三只标的的每日行情：
- `7709.HK` — 南方东英 SK 海力士每日 2x 杠杆产品（港股 / HKD）
- `000660.KS` — SK hynix 韩国正股（KOSPI / KRW）
- `SKHY` — SK hynix 美股直通上市（USD）

数据源：yfinance (Yahoo Finance) 免费接口。

## 看板内容
- 最新价 + 日内 OHLC 摘要卡
- 近 90 日收盘折线（各标的独立 y 轴）
- 归一化对比（各标的首日 = 100）
- 2x ETF 实际表现 vs 理论 2 倍海力士正股还原

## 本地开发
```powershell
uv sync
uv run python app.py            # FastAPI 实时版: http://127.0.0.1:8787
```

## 静态构建（GitHub Pages 部署用）
```powershell
uv run python generate_static.py
uv run python -m http.server -d dist 8788
```

## GitHub Pages 部署
1. 推送到 public 仓库。
2. Actions workflow `.github/workflows/refresh.yml` 每 2 小时自动拉数据、构建静态站、推到 `gh-pages` 分支。
3. 仓库 Settings → Pages → Source: `gh-pages / root`。
4. 访问 `https://<user>.github.io/<repo>/`。

可在 Actions tab 手动 Run workflow 触发首次部署。

## 局限性
详见看板内"⚠️ 数据与计算局限性提醒"面板。本看板仅为数据可视化工具，不构成投资建议。
