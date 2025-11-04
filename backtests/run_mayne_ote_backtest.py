"""命令行脚本：运行 Mayne OTE 策略回测。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .mayne_ote import MayneOTEBacktester, load_ohlc_csv


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mayne 结构 + OTE 策略回测")
    parser.add_argument("--data", required=True, help="包含 timestamp/open/high/low/close 的 CSV 数据路径")
    parser.add_argument("--initial-capital", type=float, default=10_000.0, help="初始资金")
    parser.add_argument("--risk-per-trade", type=float, default=0.01, help="单笔风险占比")
    parser.add_argument("--reward-risk", type=float, default=2.0, help="盈亏比")
    parser.add_argument("--swing-lookback", type=int, default=20, help="结构 swing 的回看周期")
    parser.add_argument("--ote-low", type=float, default=0.618, help="OTE 区间下边界")
    parser.add_argument("--ote-high", type=float, default=0.79, help="OTE 区间上边界")
    parser.add_argument("--entry-fib", type=float, default=0.705, help="OTE 入场比例")
    parser.add_argument("--max-setup-bars", type=int, default=20, help="setup 最多等待的 K 线数量")
    parser.add_argument("--stop-buffer", type=float, default=0.002, help="止损缓冲占 swing 区间的比例")
    parser.add_argument(
        "--trades-output",
        type=Path,
        help="可选，导出成交明细到 CSV 文件",
    )
    return parser


def main(args: list[str] | None = None) -> None:
    parser = build_parser()
    opts = parser.parse_args(args=args)

    data = load_ohlc_csv(opts.data)
    ote_zone = (opts.ote_low, opts.ote_high)
    backtester = MayneOTEBacktester(
        data,
        initial_capital=opts.initial_capital,
        risk_per_trade=opts.risk_per_trade,
        reward_risk=opts.reward_risk,
        swing_lookback=opts.swing_lookback,
        ote_zone=ote_zone,
        entry_fib=opts.entry_fib,
        max_setup_bars=opts.max_setup_bars,
        stop_buffer=opts.stop_buffer,
    )
    stats = backtester.run()
    print(json.dumps(stats, ensure_ascii=False, indent=2))

    if opts.trades_output:
        trades_df = backtester.trades_to_frame()
        trades_df.to_csv(opts.trades_output, index=False)
        print(f"成交明细已导出: {opts.trades_output}")


if __name__ == "__main__":
    main()
