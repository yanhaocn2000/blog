# Mayne 结构 + OTE 策略回测

本仓库在原始 Django 示例项目的基础上，加入了 **Mayne** 在外汇/加密市场常用的「结构（Market Structure）+ OTE（Optimal Trade Entry）」波段模型的回测实现。

## 策略简介

Mayne（Breakout 联合创始人）将 ICT 理论精简为一套可重复执行的流程：

1. **结构识别**：先确定行情的主要结构，记录关键 swing 高低点。
2. **流动性扫荡（Liquidity Sweep）**：等待价格假突破前高/前低，扫掉外部止损后重新回到区间内部。
3. **OTE 回调区入场**：利用斐波那契 0.618~0.79 的区间（OTE）寻找最佳回调入场点，常见的执行价是 0.705。
4. **风险收益比管理**：将止损放在扫单高/低点外，并追求固定盈亏比（例如 1:2）。

本回测程序通过简化的规则来模拟上述流程，帮助交易者理解策略节奏并验证参数组合的效果。

## 快速开始

1. 准备带有 `timestamp, open, high, low, close` 列的 K 线数据 CSV。仓库已提供 `data/sample_ohlc.csv` 演示数据。
2. 在本地安装依赖（需要 `pandas`）。

   ```bash
   pip install pandas
   ```

3. 运行命令行回测脚本：

   ```bash
   python -m backtests.run_mayne_ote_backtest --data data/sample_ohlc.csv \
       --initial-capital 10000 --risk-per-trade 0.01 --reward-risk 2.0
   ```

   输出包含收益指标、交易笔数与胜率等信息。如需保存成交明细，可增加 `--trades-output trades.csv` 参数。

## 结果分析

运行后可以得到 JSON 格式的统计信息，并可通过 `backtests.mayne_ote.MayneOTEBacktester.trades_to_frame` 方法导出 `pandas` DataFrame，进一步绘制权益曲线或评估分布。

## 注意事项

- 当前实现主要用于教学示范，与 Mayne 的实盘执行细节仍有差异。
- 回测假设单次只持有一笔仓位，止损优先于止盈成交。
- 若需要更精细的结构识别、挂单逻辑或多品种组合，可在 `backtests/mayne_ote.py` 的基础上拓展。
