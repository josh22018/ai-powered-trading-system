"""
Level-2 order book built from ITCH 5.0 messages.

OrderBook maintains bid/ask price levels per ticker using SortedDict
from the sortedcontainers library. OrderBookManager routes messages
to the correct OrderBook via stock_locate → ticker mapping.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from sortedcontainers import SortedDict

from feed.itch_messages import (
    AddOrderMsg,
    CancelOrderMsg,
    DeleteOrderMsg,
    ExecuteOrderMsg,
    ReplaceOrderMsg,
)

# Number of price levels to include in snapshots
TOP_LEVELS = 10


class OrderBook:
    """
    Single-ticker limit order book.

    Bids are stored price-descending (highest bid first).
    Asks are stored price-ascending (lowest ask first).
    Internal `orders` dict maps order_ref → (side, shares, price) for O(1)
    lookup during cancel/execute/delete/replace events.
    """

    def __init__(self, ticker: str) -> None:
        """Initialise an empty order book for the given ticker symbol."""
        self.ticker: str = ticker
        # Negative-key trick makes SortedDict iterate bids high→low
        self._bids: SortedDict = SortedDict()   # key = -price
        self._asks: SortedDict = SortedDict()   # key = +price
        self.orders: Dict[int, Tuple[str, int, float]] = {}
        self.last_timestamp_ns: int = 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _add_to_level(self, side: str, price: float, shares: int) -> None:
        """Add shares to a price level, creating the level if needed."""
        if side == 'B':
            key = -price
            self._bids[key] = self._bids.get(key, 0) + shares
        else:
            self._asks[price] = self._asks.get(price, 0) + shares

    def _remove_from_level(self, side: str, price: float, shares: int) -> None:
        """Remove shares from a price level, deleting the level if empty."""
        if side == 'B':
            key = -price
            book = self._bids
        else:
            key = price
            book = self._asks

        if key not in book:
            return
        remaining = book[key] - shares
        if remaining <= 0:
            del book[key]
        else:
            book[key] = remaining

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def apply(self, msg: Any) -> None:
        """
        Apply an ITCH message to the order book.

        Handles: AddOrderMsg, DeleteOrderMsg, CancelOrderMsg,
        ExecuteOrderMsg, ReplaceOrderMsg.
        """
        if isinstance(msg, AddOrderMsg):
            self._apply_add(msg)
        elif isinstance(msg, DeleteOrderMsg):
            self._apply_delete(msg)
        elif isinstance(msg, CancelOrderMsg):
            self._apply_cancel(msg)
        elif isinstance(msg, ExecuteOrderMsg):
            self._apply_execute(msg)
        elif isinstance(msg, ReplaceOrderMsg):
            self._apply_replace(msg)

    def _apply_add(self, msg: AddOrderMsg) -> None:
        """Handle Add Order message."""
        self.last_timestamp_ns = msg.timestamp_ns
        self.orders[msg.order_ref] = (msg.side, msg.shares, msg.price)
        self._add_to_level(msg.side, msg.price, msg.shares)

    def _apply_delete(self, msg: DeleteOrderMsg) -> None:
        """Handle Delete Order message — removes the full resting order."""
        self.last_timestamp_ns = msg.timestamp_ns
        entry = self.orders.pop(msg.order_ref, None)
        if entry is None:
            return
        side, shares, price = entry
        self._remove_from_level(side, price, shares)

    def _apply_cancel(self, msg: CancelOrderMsg) -> None:
        """Handle Cancel Order message — reduces order size by cancelled_shares."""
        self.last_timestamp_ns = msg.timestamp_ns
        entry = self.orders.get(msg.order_ref)
        if entry is None:
            return
        side, shares, price = entry
        new_shares = shares - msg.cancelled_shares
        self._remove_from_level(side, price, msg.cancelled_shares)
        if new_shares <= 0:
            del self.orders[msg.order_ref]
        else:
            self.orders[msg.order_ref] = (side, new_shares, price)

    def _apply_execute(self, msg: ExecuteOrderMsg) -> None:
        """Handle Execute Order message — reduces order size by executed shares."""
        self.last_timestamp_ns = msg.timestamp_ns
        entry = self.orders.get(msg.order_ref)
        if entry is None:
            return
        side, shares, price = entry
        exec_price = msg.execution_price if msg.execution_price else price
        self._remove_from_level(side, exec_price if exec_price == price else price,
                                msg.executed_shares)
        new_shares = shares - msg.executed_shares
        if new_shares <= 0:
            del self.orders[msg.order_ref]
        else:
            self.orders[msg.order_ref] = (side, new_shares, price)

    def _apply_replace(self, msg: ReplaceOrderMsg) -> None:
        """Handle Replace Order — cancel original, insert new order."""
        self.last_timestamp_ns = msg.timestamp_ns
        entry = self.orders.pop(msg.original_order_ref, None)
        if entry is None:
            return
        side, old_shares, old_price = entry
        # Remove old level contribution
        self._remove_from_level(side, old_price, old_shares)
        # Add new order
        self.orders[msg.new_order_ref] = (side, msg.shares, msg.price)
        self._add_to_level(side, msg.price, msg.shares)

    def snapshot(self) -> Dict[str, Any]:
        """
        Return a dict snapshot of the current book state.

        Keys: ticker, timestamp_ns, bids (top 10), asks (top 10),
              mid_price, spread, total_bid_volume, total_ask_volume.
        Bids list: [(price, shares), ...] highest first.
        Asks list: [(price, shares), ...] lowest first.
        """
        bids: List[Tuple[float, int]] = [
            (-k, v) for k, v in list(self._bids.items())[:TOP_LEVELS]
        ]
        asks: List[Tuple[float, int]] = [
            (k, v) for k, v in list(self._asks.items())[:TOP_LEVELS]
        ]

        best_bid = bids[0][0] if bids else None
        best_ask = asks[0][0] if asks else None

        if best_bid is not None and best_ask is not None:
            mid_price = (best_bid + best_ask) / 2.0
            spread = best_ask - best_bid
        else:
            mid_price = best_bid or best_ask
            spread = None

        total_bid_vol = sum(v for _, v in bids)
        total_ask_vol = sum(v for _, v in asks)

        return {
            'ticker': self.ticker,
            'timestamp_ns': self.last_timestamp_ns,
            'bids': bids,
            'asks': asks,
            'mid_price': mid_price,
            'spread': spread,
            'total_bid_volume': total_bid_vol,
            'total_ask_volume': total_ask_vol,
        }


class OrderBookManager:
    """
    Manages one OrderBook per ticker.

    Maintains a stock_locate_map ({stock_locate_id: ticker}) populated
    from ITCH Stock Directory messages, and routes all order events to
    the appropriate OrderBook.
    """

    def __init__(self) -> None:
        """Initialise with empty book registry and locate map."""
        self.books: Dict[str, OrderBook] = {}
        self.stock_locate_map: Dict[int, str] = {}

    def _get_or_create(self, ticker: str) -> OrderBook:
        """Return existing OrderBook for ticker, creating one if absent."""
        if ticker not in self.books:
            self.books[ticker] = OrderBook(ticker)
        return self.books[ticker]

    def route(self, msg: Any) -> Optional[str]:
        """
        Route a message to the correct OrderBook and call apply().

        Resolves ticker via stock_locate_map from the message's
        stock_locate field. Returns ticker string or None if unknown.
        """
        locate = getattr(msg, 'stock_locate', None)
        ticker = self.stock_locate_map.get(locate) if locate is not None else None
        if ticker is None:
            return None
        book = self._get_or_create(ticker)
        book.apply(msg)
        return ticker

    def snapshot_all(self) -> List[Dict[str, Any]]:
        """Return a list of snapshots for every tracked ticker's order book."""
        return [book.snapshot() for book in self.books.values()]
