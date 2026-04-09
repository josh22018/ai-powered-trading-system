"""
ITCH 5.0 message type constants, struct formats, and dataclasses.

Covers: Add Order (A), Add Order MPID (F), Delete Order (D),
Execute Order (E), Execute Order with Price (C), Cancel Order (X),
Replace Order (U), System Event (S), Stock Directory (R).
"""

import struct
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Message type constants
# ---------------------------------------------------------------------------
MSG_SYSTEM_EVENT     = b'S'
MSG_STOCK_DIRECTORY  = b'R'
MSG_ADD_ORDER        = b'A'
MSG_ADD_ORDER_MPID   = b'F'
MSG_DELETE_ORDER     = b'D'
MSG_EXECUTE_ORDER    = b'E'
MSG_EXECUTE_PRICE    = b'C'
MSG_CANCEL_ORDER     = b'X'
MSG_REPLACE_ORDER    = b'U'

# ---------------------------------------------------------------------------
# Struct format strings  (all big-endian, no alignment padding)
# Field order matches NASDAQ ITCH 5.0 spec exactly.
# ---------------------------------------------------------------------------

# System Event: msg_type(1) + stock_locate(2) + tracking_number(2) +
#               timestamp(6) + event_code(1)  → total 12 bytes
FMT_SYSTEM_EVENT = '>cHH6sc'

# Stock Directory: msg_type(1) + stock_locate(2) + tracking_number(2) +
#   timestamp(6) + stock(8) + market_category(1) + financial_status(1) +
#   round_lot_size(4) + round_lots_only(1) + issue_classification(1) +
#   issue_sub_type(2) + authenticity(1) + short_sale_threshold(1) +
#   ipo_flag(1) + luld_ref_price_tier(1) + etp_flag(1) + etp_leverage(4) +
#   inverse_indicator(1)  → total 39 bytes
FMT_STOCK_DIRECTORY = '>cHH6s8sccIcc2scccccIc'

# Add Order (no MPID): msg_type(1) + stock_locate(2) + tracking_number(2) +
#   timestamp(6) + order_ref(8) + buy_sell(1) + shares(4) +
#   stock(8) + price(4)  → total 36 bytes
FMT_ADD_ORDER = '>cHH6sQcI8sI'

# Add Order with MPID: same as Add Order + mpid(4)  → total 40 bytes
FMT_ADD_ORDER_MPID = '>cHH6sQcI8sI4s'

# Delete Order: msg_type(1) + stock_locate(2) + tracking_number(2) +
#   timestamp(6) + order_ref(8)  → total 19 bytes
FMT_DELETE_ORDER = '>cHH6sQ'

# Execute Order: msg_type(1) + stock_locate(2) + tracking_number(2) +
#   timestamp(6) + order_ref(8) + executed_shares(4) +
#   match_number(8)  → total 31 bytes
FMT_EXECUTE_ORDER = '>cHH6sQIQ'

# Execute Order with Price: msg_type(1) + stock_locate(2) + tracking_number(2) +
#   timestamp(6) + order_ref(8) + executed_shares(4) + match_number(8) +
#   printable(1) + execution_price(4)  → total 36 bytes
FMT_EXECUTE_PRICE = '>cHH6sQIQcI'

# Cancel Order: msg_type(1) + stock_locate(2) + tracking_number(2) +
#   timestamp(6) + order_ref(8) + cancelled_shares(4)  → total 23 bytes
FMT_CANCEL_ORDER = '>cHH6sQI'

# Replace Order: msg_type(1) + stock_locate(2) + tracking_number(2) +
#   timestamp(6) + original_order_ref(8) + new_order_ref(8) +
#   shares(4) + price(4)  → total 35 bytes
FMT_REPLACE_ORDER = '>cHH6sQQII'

# Pre-compiled struct objects for performance
STRUCT_ADD_ORDER      = struct.Struct(FMT_ADD_ORDER)
STRUCT_ADD_ORDER_MPID = struct.Struct(FMT_ADD_ORDER_MPID)
STRUCT_DELETE_ORDER   = struct.Struct(FMT_DELETE_ORDER)
STRUCT_EXECUTE_ORDER  = struct.Struct(FMT_EXECUTE_ORDER)
STRUCT_EXECUTE_PRICE  = struct.Struct(FMT_EXECUTE_PRICE)
STRUCT_CANCEL_ORDER   = struct.Struct(FMT_CANCEL_ORDER)
STRUCT_REPLACE_ORDER  = struct.Struct(FMT_REPLACE_ORDER)
STRUCT_SYSTEM_EVENT   = struct.Struct(FMT_SYSTEM_EVENT)
STRUCT_STOCK_DIR      = struct.Struct(FMT_STOCK_DIRECTORY)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_timestamp(raw: bytes) -> int:
    """Parse a 6-byte big-endian ITCH timestamp into nanoseconds (int)."""
    # Pad to 8 bytes for unpack
    return int.from_bytes(raw, byteorder='big')


def parse_price(raw_price: int) -> float:
    """Convert a raw ITCH price integer to float USD (divide by 10_000)."""
    return raw_price / 10_000.0


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AddOrderMsg:
    """Represents an ITCH Add Order (A) or Add Order MPID (F) message."""
    stock_locate: int
    timestamp_ns: int
    order_ref: int
    side: str          # 'B' = buy, 'S' = sell
    shares: int
    stock: str
    price: float
    mpid: str = ''


@dataclass
class DeleteOrderMsg:
    """Represents an ITCH Delete Order (D) message."""
    stock_locate: int
    timestamp_ns: int
    order_ref: int


@dataclass
class CancelOrderMsg:
    """Represents an ITCH Cancel Order (X) message."""
    stock_locate: int
    timestamp_ns: int
    order_ref: int
    cancelled_shares: int


@dataclass
class ExecuteOrderMsg:
    """Represents an ITCH Execute Order (E) or Execute with Price (C) message."""
    stock_locate: int
    timestamp_ns: int
    order_ref: int
    executed_shares: int
    match_number: int
    execution_price: float = 0.0   # only set for type C


@dataclass
class ReplaceOrderMsg:
    """Represents an ITCH Replace Order (U) message."""
    stock_locate: int
    timestamp_ns: int
    original_order_ref: int
    new_order_ref: int
    shares: int
    price: float
