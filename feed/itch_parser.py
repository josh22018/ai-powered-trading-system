"""
Async ITCH 5.0 binary feed parser.

Reads a raw ITCH file (2-byte length-prefix framing), dispatches each
message to the OrderBookManager, and pushes snapshots into the RingBuffer
after every order event.
"""

from __future__ import annotations

import asyncio
import logging
import struct
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from feed.itch_messages import (
    MSG_ADD_ORDER,
    MSG_ADD_ORDER_MPID,
    MSG_CANCEL_ORDER,
    MSG_DELETE_ORDER,
    MSG_EXECUTE_ORDER,
    MSG_EXECUTE_PRICE,
    MSG_REPLACE_ORDER,
    MSG_STOCK_DIRECTORY,
    MSG_SYSTEM_EVENT,
    STRUCT_ADD_ORDER,
    STRUCT_ADD_ORDER_MPID,
    STRUCT_CANCEL_ORDER,
    STRUCT_DELETE_ORDER,
    STRUCT_EXECUTE_ORDER,
    STRUCT_EXECUTE_PRICE,
    STRUCT_REPLACE_ORDER,
    STRUCT_STOCK_DIR,
    STRUCT_SYSTEM_EVENT,
    AddOrderMsg,
    CancelOrderMsg,
    DeleteOrderMsg,
    ExecuteOrderMsg,
    ReplaceOrderMsg,
    parse_price,
    parse_timestamp,
)
from feed.order_book import OrderBookManager
from shared.ring_buffer import RingBuffer

log = logging.getLogger(__name__)

_LEN_PREFIX = struct.Struct('>H')   # 2-byte big-endian length prefix

# Message types that carry order events (used for ring_buffer flush decision)
ORDER_EVENT_TYPES: Set[bytes] = {
    MSG_ADD_ORDER, MSG_ADD_ORDER_MPID,
    MSG_DELETE_ORDER, MSG_EXECUTE_ORDER, MSG_EXECUTE_PRICE,
    MSG_CANCEL_ORDER, MSG_REPLACE_ORDER,
}


def _decode_stock(raw: bytes) -> str:
    """Strip trailing spaces from an 8-byte padded stock symbol."""
    return raw.decode('ascii', errors='replace').strip()


def _unpack_add_order(body: bytes) -> Optional[AddOrderMsg]:
    """Parse an Add Order (A) message body into AddOrderMsg."""
    fields = STRUCT_ADD_ORDER.unpack(body)
    _, locate, _, ts_bytes, order_ref, side_b, shares, stock_b, price_raw = fields
    return AddOrderMsg(
        stock_locate=locate,
        timestamp_ns=parse_timestamp(ts_bytes),
        order_ref=order_ref,
        side=side_b.decode('ascii'),
        shares=shares,
        stock=_decode_stock(stock_b),
        price=parse_price(price_raw),
    )


def _unpack_add_order_mpid(body: bytes) -> Optional[AddOrderMsg]:
    """Parse an Add Order with MPID (F) message body into AddOrderMsg."""
    fields = STRUCT_ADD_ORDER_MPID.unpack(body)
    _, locate, _, ts_bytes, order_ref, side_b, shares, stock_b, price_raw, mpid_b = fields
    return AddOrderMsg(
        stock_locate=locate,
        timestamp_ns=parse_timestamp(ts_bytes),
        order_ref=order_ref,
        side=side_b.decode('ascii'),
        shares=shares,
        stock=_decode_stock(stock_b),
        price=parse_price(price_raw),
        mpid=mpid_b.decode('ascii', errors='replace').strip(),
    )


def _unpack_delete_order(body: bytes) -> Optional[DeleteOrderMsg]:
    """Parse a Delete Order (D) message body into DeleteOrderMsg."""
    _, locate, _, ts_bytes, order_ref = STRUCT_DELETE_ORDER.unpack(body)
    return DeleteOrderMsg(
        stock_locate=locate,
        timestamp_ns=parse_timestamp(ts_bytes),
        order_ref=order_ref,
    )


def _unpack_cancel_order(body: bytes) -> Optional[CancelOrderMsg]:
    """Parse a Cancel Order (X) message body into CancelOrderMsg."""
    _, locate, _, ts_bytes, order_ref, cancelled = STRUCT_CANCEL_ORDER.unpack(body)
    return CancelOrderMsg(
        stock_locate=locate,
        timestamp_ns=parse_timestamp(ts_bytes),
        order_ref=order_ref,
        cancelled_shares=cancelled,
    )


def _unpack_execute_order(body: bytes) -> Optional[ExecuteOrderMsg]:
    """Parse an Execute Order (E) message body into ExecuteOrderMsg."""
    _, locate, _, ts_bytes, order_ref, executed, match = STRUCT_EXECUTE_ORDER.unpack(body)
    return ExecuteOrderMsg(
        stock_locate=locate,
        timestamp_ns=parse_timestamp(ts_bytes),
        order_ref=order_ref,
        executed_shares=executed,
        match_number=match,
    )


def _unpack_execute_price(body: bytes) -> Optional[ExecuteOrderMsg]:
    """Parse an Execute Order with Price (C) message body into ExecuteOrderMsg."""
    _, locate, _, ts_bytes, order_ref, executed, match, _, price_raw = \
        STRUCT_EXECUTE_PRICE.unpack(body)
    return ExecuteOrderMsg(
        stock_locate=locate,
        timestamp_ns=parse_timestamp(ts_bytes),
        order_ref=order_ref,
        executed_shares=executed,
        match_number=match,
        execution_price=parse_price(price_raw),
    )


def _unpack_replace_order(body: bytes) -> Optional[ReplaceOrderMsg]:
    """Parse a Replace Order (U) message body into ReplaceOrderMsg."""
    _, locate, _, ts_bytes, orig_ref, new_ref, shares, price_raw = \
        STRUCT_REPLACE_ORDER.unpack(body)
    return ReplaceOrderMsg(
        stock_locate=locate,
        timestamp_ns=parse_timestamp(ts_bytes),
        original_order_ref=orig_ref,
        new_order_ref=new_ref,
        shares=shares,
        price=parse_price(price_raw),
    )


def _populate_stock_locate(body: bytes, manager: OrderBookManager) -> None:
    """Extract ticker ↔ stock_locate mapping from a Stock Directory (R) message."""
    try:
        fields = STRUCT_STOCK_DIR.unpack(body)
        locate = fields[1]
        stock_b = fields[4]
        ticker = _decode_stock(stock_b)
        manager.stock_locate_map[locate] = ticker
    except Exception as exc:
        log.warning('Failed to parse Stock Directory message: %s', exc)


# Dispatcher table: msg_type_byte → unpack callable
_DISPATCH = {
    MSG_ADD_ORDER:      _unpack_add_order,
    MSG_ADD_ORDER_MPID: _unpack_add_order_mpid,
    MSG_DELETE_ORDER:   _unpack_delete_order,
    MSG_CANCEL_ORDER:   _unpack_cancel_order,
    MSG_EXECUTE_ORDER:  _unpack_execute_order,
    MSG_EXECUTE_PRICE:  _unpack_execute_price,
    MSG_REPLACE_ORDER:  _unpack_replace_order,
}


async def parse_feed(
    filepath: str,
    order_book_manager: OrderBookManager,
    ring_buffer: RingBuffer,
    tickers_filter: Optional[List[str]] = None,
    max_messages: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Async ITCH 5.0 file parser.

    Opens filepath in binary mode, reads length-prefixed messages in a loop,
    dispatches each message type, updates the OrderBookManager, and writes
    consolidated snapshots to ring_buffer after every order event.

    Args:
        filepath:           Path to the ITCH binary file.
        order_book_manager: OrderBookManager instance to update.
        ring_buffer:        RingBuffer instance to publish snapshots to.
        tickers_filter:     If set, only route messages for these tickers.
        max_messages:       Stop after this many messages (None = no limit).

    Returns:
        Stats dict: messages_parsed, messages_skipped, parse_errors,
                    elapsed_time, slots_written.
    """
    stats: Dict[str, Any] = {
        'messages_parsed': 0,
        'messages_skipped': 0,
        'parse_errors': 0,
        'elapsed_time': 0.0,
        'slots_written': 0,
    }

    filter_set: Optional[Set[str]] = (
        set(tickers_filter) if tickers_filter else None
    )

    t0 = time.perf_counter()

    try:
        with open(filepath, 'rb') as fh:
            msg_count = 0
            while True:
                if max_messages is not None and msg_count >= max_messages:
                    break

                # Read 2-byte length prefix
                raw_len = fh.read(2)
                if len(raw_len) < 2:
                    break   # EOF

                (msg_len,) = _LEN_PREFIX.unpack(raw_len)
                body = fh.read(msg_len)
                if len(body) < msg_len:
                    log.warning('Truncated message at count %d', msg_count)
                    stats['parse_errors'] += 1
                    break

                msg_count += 1
                msg_type = body[0:1]

                # ---- Stock Directory ----
                if msg_type == MSG_STOCK_DIRECTORY:
                    _populate_stock_locate(body, order_book_manager)
                    stats['messages_parsed'] += 1
                    continue

                # ---- System Event (log and skip) ----
                if msg_type == MSG_SYSTEM_EVENT:
                    stats['messages_parsed'] += 1
                    continue

                # ---- Order events ----
                dispatcher = _DISPATCH.get(msg_type)
                if dispatcher is None:
                    stats['messages_skipped'] += 1
                    continue

                try:
                    msg_obj = dispatcher(body)
                except Exception as exc:
                    log.warning('Parse error (type=%s, count=%d): %s',
                                msg_type, msg_count, exc)
                    stats['parse_errors'] += 1
                    continue

                if msg_obj is None:
                    stats['messages_skipped'] += 1
                    continue

                # Apply ticker filter before routing
                if filter_set is not None:
                    locate = getattr(msg_obj, 'stock_locate', None)
                    ticker = order_book_manager.stock_locate_map.get(locate, '')
                    if ticker not in filter_set:
                        stats['messages_skipped'] += 1
                        continue

                order_book_manager.route(msg_obj)
                stats['messages_parsed'] += 1

                # Publish snapshots after every order event
                snapshots = order_book_manager.snapshot_all()
                for snap in snapshots:
                    ring_buffer.write(snap)

                # Yield to event loop every 1000 messages to stay async
                if msg_count % 1000 == 0:
                    await asyncio.sleep(0)

                # Progress report
                if msg_count % 10_000 == 0:
                    elapsed = time.perf_counter() - t0
                    print(f'  [parser] {msg_count:,} messages processed '
                          f'({elapsed:.1f}s)  '
                          f'parse_errors={stats["parse_errors"]}')

    except FileNotFoundError:
        log.error('ITCH file not found: %s', filepath)
        raise

    stats['elapsed_time'] = time.perf_counter() - t0
    stats['slots_written'] = ring_buffer.slots_written
    return stats
