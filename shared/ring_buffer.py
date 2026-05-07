"""
Lock-free ring buffer backed by shared memory.

Cross-platform implementation:
  - Linux/macOS: uses multiprocessing.shared_memory (POSIX shm)
  - Windows: uses a file-backed mmap in the temp directory

Uses msgpack-serialised snapshot dicts in fixed-size slots that can be
read by any process that shares the same memory segment name.

Slot layout (4096 bytes each):
  [0:2]  status   uint16  0 = empty, 1 = ready
  [2:4]  length   uint16  payload byte length
  [4:]   payload  bytes   msgpack-encoded snapshot dict
"""

from __future__ import annotations

import mmap
import os
import platform
import struct
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import msgpack

# Ring-buffer geometry
NUM_SLOTS   = 1024
SLOT_SIZE   = 4096
HEADER_SIZE = 4          # 2 bytes status + 2 bytes length
MAX_PAYLOAD = SLOT_SIZE - HEADER_SIZE   # 4092 bytes

_HDR = struct.Struct('>HH')   # big-endian: status(uint16), length(uint16)

_IS_WINDOWS = platform.system() == 'Windows'


class RingBuffer:
    """
    Fixed-slot ring buffer stored in shared memory.

    Multiple writers are NOT safe without external locking; this design
    assumes a single writer (the feed parser) and one or more readers
    (agent processes).

    On Windows, falls back to file-backed mmap since POSIX shared memory
    is not available natively.
    """

    def __init__(self, name: str = 'kairos_ring', create: bool = True) -> None:
        """
        Attach to or create the shared memory segment.

        Args:
            name:   Shared memory segment name (used by reader processes).
            create: True → create new segment; False → attach to existing.
        """
        self.name = name
        self._total_size = NUM_SLOTS * SLOT_SIZE
        self._write_index: int = 0   # next slot to write
        self._slots_written: int = 0

        if _IS_WINDOWS:
            self._init_windows(name, create)
        else:
            self._init_posix(name, create)

    def _init_windows(self, name: str, create: bool) -> None:
        """Initialise using file-backed mmap on Windows."""
        self._file_path = Path(tempfile.gettempdir()) / f'kairos_shm_{name}'

        if create:
            # Create or truncate the backing file
            with open(self._file_path, 'wb') as f:
                f.write(b'\x00' * self._total_size)
            self._file = open(self._file_path, 'r+b')
            self._mmap = mmap.mmap(self._file.fileno(), self._total_size)
        else:
            # Attach to existing
            if not self._file_path.exists():
                raise FileNotFoundError(
                    f'Shared memory file not found: {self._file_path}'
                )
            self._file = open(self._file_path, 'r+b')
            self._mmap = mmap.mmap(self._file.fileno(), self._total_size)

        self._shm = None   # not used on Windows
        self._buf = self._mmap

    def _init_posix(self, name: str, create: bool) -> None:
        """Initialise using POSIX shared memory (Linux/macOS)."""
        from multiprocessing.shared_memory import SharedMemory

        self._file = None
        self._file_path = None
        self._mmap = None

        if create:
            try:
                # Clean up any stale segment from a previous run
                old = SharedMemory(name=name, create=False,
                                   size=self._total_size)
                old.close()
                old.unlink()
            except FileNotFoundError:
                pass
            self._shm = SharedMemory(name=name, create=True,
                                     size=self._total_size)
            # Zero-initialise all slots
            self._shm.buf[:self._total_size] = b'\x00' * self._total_size
        else:
            self._shm = SharedMemory(name=name, create=False,
                                     size=self._total_size)

        self._buf = self._shm.buf

    # ------------------------------------------------------------------
    # Unified buffer access
    # ------------------------------------------------------------------

    def _read_buf(self, start: int, end: int) -> bytes:
        """Read bytes from the buffer (platform-independent)."""
        return bytes(self._buf[start:end])

    def _write_buf(self, start: int, data: bytes) -> None:
        """Write bytes to the buffer (platform-independent)."""
        end = start + len(data)
        self._buf[start:end] = data

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    def write(self, snapshot_dict: Any) -> bool:
        """
        Serialise snapshot_dict with msgpack and write to the next slot.

        Returns True on success, False if the payload exceeds MAX_PAYLOAD.
        The write index wraps around (ring semantics).
        """
        payload: bytes = msgpack.packb(snapshot_dict, use_bin_type=True)
        if len(payload) > MAX_PAYLOAD:
            return False

        slot_offset = self._write_index * SLOT_SIZE
        # Write header
        header = _HDR.pack(1, len(payload))
        self._write_buf(slot_offset, header)
        # Write payload
        self._write_buf(slot_offset + HEADER_SIZE, payload)

        self._write_index = (self._write_index + 1) % NUM_SLOTS
        self._slots_written += 1
        return True

    # ------------------------------------------------------------------
    # Read path
    # ------------------------------------------------------------------

    def _read_slot(self, index: int) -> Optional[Any]:
        """
        Read and deserialise a single slot by index.

        Returns the dict if the slot is ready, else None.
        """
        offset = index * SLOT_SIZE
        raw_header = self._read_buf(offset, offset + HEADER_SIZE)
        status, length = _HDR.unpack(raw_header)
        if status != 1 or length == 0:
            return None
        raw = self._read_buf(
            offset + HEADER_SIZE,
            offset + HEADER_SIZE + length,
        )
        return msgpack.unpackb(raw, raw=False)

    def read_latest(self) -> Optional[Any]:
        """
        Return the most recently written snapshot dict.

        Searches backwards from the current write index.
        Returns None if no ready slots exist.
        """
        for i in range(NUM_SLOTS):
            idx = (self._write_index - 1 - i) % NUM_SLOTS
            result = self._read_slot(idx)
            if result is not None:
                return result
        return None

    def read_all_new(self, last_index: int) -> Tuple[List[Any], int]:
        """
        Return all new snapshot dicts written since last_index.

        Args:
            last_index: The write index returned by the previous call
                        (or 0 for the very first call).

        Returns:
            Tuple (snapshots: list, new_last_index: int).
        """
        results: List[Any] = []
        current = self._write_index
        idx = last_index % NUM_SLOTS
        while idx != current % NUM_SLOTS:
            item = self._read_slot(idx)
            if item is not None:
                results.append(item)
            idx = (idx + 1) % NUM_SLOTS
        return results, current

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def slots_written(self) -> int:
        """Total number of slots written since this buffer was created."""
        return self._slots_written

    def close(self) -> None:
        """Detach from shared memory without unlinking the segment."""
        if _IS_WINDOWS:
            if self._mmap:
                self._mmap.close()
            if self._file:
                self._file.close()
        else:
            self._shm.close()

    def cleanup(self) -> None:
        """Detach and unlink (destroy) the shared memory segment."""
        if _IS_WINDOWS:
            if self._mmap:
                self._mmap.close()
                self._mmap = None
            if self._file:
                self._file.close()
                self._file = None
            if self._file_path and self._file_path.exists():
                try:
                    os.remove(self._file_path)
                except OSError:
                    pass
        else:
            self._shm.close()
            try:
                self._shm.unlink()
            except FileNotFoundError:
                pass
