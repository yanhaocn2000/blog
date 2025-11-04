"""Implementation of Mayne's structure + OTE swing strategy backtest."""
from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Dict, List, Optional, Tuple

import pandas as pd


@dataclass
class Trade:
    """Record of a single trade taken by the backtester."""

    direction: str
    entry_time: pd.Timestamp
    entry_index: int
    entry_price: float
    stop_price: float
    target_price: float
    exit_time: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    result: Optional[str] = None
    pnl: float = 0.0
    r_multiple: float = 0.0


def load_ohlc_csv(path: str, tz: Optional[str] = None) -> pd.DataFrame:
    """Load OHLC data from a CSV file.

    The CSV file must contain the columns ``timestamp``, ``open``, ``high``, ``low`` and
    ``close``. Additional columns are ignored.

    Parameters
    ----------
    path:
        File path of the CSV file.
    tz:
        Optional timezone string applied to the parsed timestamps.

    Returns
    -------
    pandas.DataFrame
        Data indexed by ``timestamp`` ordered in ascending order.
    """

    df = pd.read_csv(path)
    required = {"timestamp", "open", "high", "low", "close"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"缺少必要列: {', '.join(sorted(missing))}")

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    if tz:
        df["timestamp"] = df["timestamp"].dt.tz_convert(tz)
    df = df.set_index("timestamp").sort_index()
    float_cols = ["open", "high", "low", "close"]
    df[float_cols] = df[float_cols].astype(float)
    return df


class MayneOTEBacktester:
    """Simplified backtest of Mayne 的结构 + OTE 波段模型。

    这个实现尝试复刻 Mayne 对 ICT 理论的核心思想：

    * 市场先扫掉外部流动性（突破前高/前低，形成假突破）
    * 回到内部流动性区域（回调到 61.8% - 79% 的 OTE 区域）
    * 在结构方向上寻找入场与固定的盈亏比管理

    为了便于学习，这里使用较为规则化的定义，能够在历史 K 线数据上快速回测。
    """

    def __init__(
        self,
        data: pd.DataFrame,
        initial_capital: float = 10_000.0,
        risk_per_trade: float = 0.01,
        reward_risk: float = 2.0,
        swing_lookback: int = 20,
        ote_zone: Tuple[float, float] = (0.618, 0.79),
        entry_fib: float = 0.705,
        max_setup_bars: int = 20,
        stop_buffer: float = 0.002,
    ) -> None:
        if data.empty:
            raise ValueError("历史数据为空，无法回测。")

        if not data.index.is_monotonic_increasing:
            data = data.sort_index()

        self.data = data
        self.initial_capital = float(initial_capital)
        self.capital = float(initial_capital)
        self.risk_per_trade = float(risk_per_trade)
        self.reward_risk = float(reward_risk)
        self.swing_lookback = int(swing_lookback)
        self.ote_zone = ote_zone
        self.entry_fib = entry_fib
        self.max_setup_bars = max_setup_bars
        self.stop_buffer = stop_buffer

        self.trades: List[Trade] = []
        self._structure_high: Optional[Dict[str, float]] = None
        self._structure_low: Optional[Dict[str, float]] = None
        self._pending_setup: Optional[Dict[str, float]] = None
        self._position: Optional[Dict[str, float]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def run(self) -> Dict[str, float]:
        """Run the backtest and return aggregated statistics."""

        for i, (ts, row) in enumerate(self.data.iterrows()):
            prior_high = self._structure_high
            prior_low = self._structure_low

            self._update_structure(i)
            self._manage_position(i, ts, row)

            if self._position is not None:
                # 有仓位时不考虑新 setup
                continue

            if self._pending_setup is not None:
                self._try_execute_setup(i, ts, row)

            if self._position is None and self._pending_setup is None:
                self._detect_setup(i, ts, row, prior_high, prior_low)

        return self.summary()

    def summary(self) -> Dict[str, float]:
        """Return performance statistics."""

        total_return = (self.capital - self.initial_capital) / self.initial_capital
        wins = sum(1 for t in self.trades if t.result == "win")
        losses = sum(1 for t in self.trades if t.result == "loss")
        breakeven = sum(1 for t in self.trades if t.result == "breakeven")
        total = len(self.trades)
        win_rate = wins / total if total else 0.0
        avg_r = mean([t.r_multiple for t in self.trades]) if self.trades else 0.0

        return {
            "initial_capital": self.initial_capital,
            "ending_capital": self.capital,
            "total_return": total_return,
            "num_trades": total,
            "wins": wins,
            "losses": losses,
            "breakeven": breakeven,
            "win_rate": win_rate,
            "average_r_multiple": avg_r,
        }

    def trades_to_frame(self) -> pd.DataFrame:
        """Convert trade list to pandas.DataFrame for further analysis."""

        if not self.trades:
            return pd.DataFrame(
                columns=[
                    "direction",
                    "entry_time",
                    "exit_time",
                    "entry_price",
                    "exit_price",
                    "stop_price",
                    "target_price",
                    "result",
                    "pnl",
                    "r_multiple",
                ]
            )

        return pd.DataFrame([t.__dict__ for t in self.trades])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _update_structure(self, i: int) -> None:
        start = max(0, i - self.swing_lookback + 1)
        window = self.data.iloc[start : i + 1]
        high_idx = window["high"].idxmax()
        low_idx = window["low"].idxmin()

        high_loc = self.data.index.get_loc(high_idx)
        low_loc = self.data.index.get_loc(low_idx)

        self._structure_high = {
            "index": int(high_loc),
            "price": float(self.data.iloc[high_loc]["high"]),
        }
        self._structure_low = {
            "index": int(low_loc),
            "price": float(self.data.iloc[low_loc]["low"]),
        }

    def _detect_setup(
        self,
        i: int,
        ts: pd.Timestamp,
        row: pd.Series,
        prior_high: Optional[Dict[str, float]],
        prior_low: Optional[Dict[str, float]],
    ) -> None:
        if prior_high and prior_low:
            # Bearish sweep: take out previous high and close back below
            if (
                row["high"] > prior_high["price"]
                and row["close"] < prior_high["price"]
                and prior_low["index"] < prior_high["index"]
            ):
                self._pending_setup = {
                    "direction": "short",
                    "leg_high": float(row["high"]),
                    "leg_low": float(prior_low["price"]),
                    "created_at": i,
                }
                return

        if prior_low and prior_high:
            # Bullish sweep: take out previous low and close back above
            if (
                row["low"] < prior_low["price"]
                and row["close"] > prior_low["price"]
                and prior_high["index"] < prior_low["index"]
            ):
                self._pending_setup = {
                    "direction": "long",
                    "leg_low": float(row["low"]),
                    "leg_high": float(prior_high["price"]),
                    "created_at": i,
                }
                return

    def _try_execute_setup(self, i: int, ts: pd.Timestamp, row: pd.Series) -> None:
        if self._pending_setup is None:
            return

        if i - self._pending_setup["created_at"] > self.max_setup_bars:
            self._pending_setup = None
            return

        direction = self._pending_setup["direction"]
        leg_high = self._pending_setup["leg_high"]
        leg_low = self._pending_setup["leg_low"]
        leg_range = max(leg_high - leg_low, 1e-6)

        if direction == "short":
            zone_low = leg_low + leg_range * self.ote_zone[0]
            zone_high = leg_low + leg_range * self.ote_zone[1]
            entry_price = leg_low + leg_range * self.entry_fib
            touched_zone = row["high"] >= zone_low and row["low"] <= zone_high
            if touched_zone:
                buffer = max(leg_range * self.stop_buffer, row["close"] * 0.0001)
                stop_price = leg_high + buffer
                entry = min(entry_price, row["close"])
                if stop_price <= entry:
                    stop_price = entry + abs(entry) * 0.001
                target_price = entry - self.reward_risk * (stop_price - entry)
                self._open_position(
                    direction=direction,
                    entry_time=ts,
                    entry_index=i,
                    entry_price=entry,
                    stop_price=stop_price,
                    target_price=target_price,
                )
                self._pending_setup = None

        elif direction == "long":
            zone_high = leg_high - leg_range * self.ote_zone[0]
            zone_low = leg_high - leg_range * self.ote_zone[1]
            entry_price = leg_high - leg_range * self.entry_fib
            touched_zone = row["low"] <= zone_high and row["high"] >= zone_low
            if touched_zone:
                buffer = max(leg_range * self.stop_buffer, row["close"] * 0.0001)
                stop_price = leg_low - buffer
                entry = max(entry_price, row["close"])
                if stop_price >= entry:
                    stop_price = entry - abs(entry) * 0.001
                target_price = entry + self.reward_risk * (entry - stop_price)
                self._open_position(
                    direction=direction,
                    entry_time=ts,
                    entry_index=i,
                    entry_price=entry,
                    stop_price=stop_price,
                    target_price=target_price,
                )
                self._pending_setup = None

    def _open_position(
        self,
        direction: str,
        entry_time: pd.Timestamp,
        entry_index: int,
        entry_price: float,
        stop_price: float,
        target_price: float,
    ) -> None:
        risk_amount = self.capital * self.risk_per_trade
        risk_per_unit = abs(stop_price - entry_price)
        if risk_per_unit <= 0:
            return
        position_size = risk_amount / risk_per_unit
        self._position = {
            "direction": direction,
            "entry_time": entry_time,
            "entry_index": entry_index,
            "entry_price": entry_price,
            "stop_price": stop_price,
            "target_price": target_price,
            "size": position_size,
        }

    def _manage_position(self, i: int, ts: pd.Timestamp, row: pd.Series) -> None:
        if self._position is None:
            return

        direction = self._position["direction"]
        entry_price = self._position["entry_price"]
        stop_price = self._position["stop_price"]
        target_price = self._position["target_price"]
        size = self._position["size"]

        exit_price = None
        result = None

        if direction == "long":
            if row["low"] <= stop_price:
                exit_price = stop_price
                result = "loss"
            elif row["high"] >= target_price:
                exit_price = target_price
                result = "win"
        else:
            if row["high"] >= stop_price:
                exit_price = stop_price
                result = "loss"
            elif row["low"] <= target_price:
                exit_price = target_price
                result = "win"

        if exit_price is None:
            return

        if result == "loss":
            pnl = (exit_price - entry_price) * size * (1 if direction == "long" else -1)
            r_multiple = -1.0
        else:
            pnl = (exit_price - entry_price) * size * (1 if direction == "long" else -1)
            r_multiple = self.reward_risk

        self.capital += pnl
        trade = Trade(
            direction=direction,
            entry_time=self._position["entry_time"],
            entry_index=self._position["entry_index"],
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            exit_time=ts,
            exit_price=exit_price,
            result=result,
            pnl=pnl,
            r_multiple=r_multiple,
        )
        self.trades.append(trade)
        self._position = None
