"""Frame-level J1939 encoder/decoder (F6, ADR-019).

This activates the seam ADR-013 left open. Since F1 each bus signal has carried its
PGN; F6's :class:`~.spec.FrameLayout` completes the *physical* picture — where the
parameter sits in the frame and how a raw integer maps to engineering units — and
this module turns one engineering value into the **actual bytes a J1939 node would
transmit**, and back.

Why a real encoder and not just a value-mutator: the Tier-3 fault class (malformed /
implausible **frames**, F6) only exists once signals are bytes. A bit flip, a stale
re-send, a J1939 *error/not-available* sentinel, or a short DLC are all things that
happen to a *frame*, not to a float — so the corruption is injected at the byte
layer and **decoded back** into the tidy table, exactly as a real receiver would see
it (ADR-019). The decoder is the receiver; the dataset stays decoded (no schema
change — ADR-016), with the raw frame optionally emitted as a side artifact.

J1939 conventions modeled (publicly documented SAE J1939-71):

* **Byte order is little-endian** (intel / LSB-first) for multi-byte parameters.
* A field of all-ones raw bits is **"parameter not available"**; the next value
  down (``0xFE`` for a byte, ``0xFExx`` band for two bytes) is the **error
  indicator**. We model the canonical pair: an all-ones field decodes to ``NaN``
  (not available) and the documented top-of-range error code decodes to ``NaN`` too
  — both are "no usable value", which is what a frame fault should surface.
* Frames are ``frame_bytes`` long (8 for the Tier-1 PGNs); unused bytes are ``0xFF``
  (the bus idle / not-available fill), so a truncated frame loses real bits.

Everything here is pure and deterministic; no randomness lives in the codec.
"""

from __future__ import annotations

import math

from .spec import FrameLayout, SignalSpec

# A frame is at most 8 bytes on classic CAN; the Tier-1 PGNs all use 8.
MAX_FRAME_BYTES = 8

# J1939 "not available" fill for an untransmitted/idle byte.
NA_BYTE = 0xFF


def _raw_max(bit_len: int) -> int:
    """Largest unsigned raw integer for a field of ``bit_len`` bits."""
    return (1 << bit_len) - 1


def _na_raw(bit_len: int) -> int:
    """The J1939 *not-available* raw code (all ones) for ``bit_len`` bits."""
    return _raw_max(bit_len)


def _error_raw(bit_len: int) -> int:
    """The J1939 *error-indicator* raw code (one below not-available)."""
    return _raw_max(bit_len) - 1


def value_to_raw(value: float, layout: FrameLayout) -> int:
    """Quantize an engineering value to its unsigned raw integer (clamped in-field).

    Applies the inverse linear J1939 scaling ``raw = round((value - offset) / scale)``
    and clamps into ``[0, raw_max - 2]`` — the **valid data** range, leaving the top
    two codes free for the not-available / error sentinels (so a genuine reading is
    never confused with a fault marker).
    """
    raw = round((value - layout.offset) / layout.scale)
    valid_max = _raw_max(layout.bit_len) - 2  # reserve NA + error codes
    return max(0, min(valid_max, int(raw)))


def raw_to_value(raw: int, layout: FrameLayout) -> float:
    """Decode an unsigned raw integer back to an engineering value.

    The two reserved top codes (not-available, error) decode to ``NaN`` — a frame
    that carries one of them has *no usable value*, which is exactly what a receiver
    reports.
    """
    if raw >= _error_raw(layout.bit_len):  # not-available or error
        return math.nan
    return raw * layout.scale + layout.offset


def encode_signal_frame(value: float, spec: SignalSpec) -> bytearray:
    """Encode one engineering ``value`` into the bytes of its J1939 frame.

    The frame is ``frame_bytes`` long, pre-filled with the not-available byte
    ``0xFF``; the signal's field is overwritten with its little-endian raw integer.
    Bus signals only (``spec.layout`` set); raising otherwise keeps the inert,
    non-bus fields (runtime/age/vibration) honest.
    """
    layout = spec.layout
    if layout is None:
        raise ValueError(f"signal {spec.name!r} has no frame layout (not a bus signal)")
    if math.isnan(value):
        # A NULL engineering value is transmitted as the not-available field.
        raw = _na_raw(layout.bit_len)
    else:
        raw = value_to_raw(value, layout)

    frame = bytearray([NA_BYTE]) * layout.frame_bytes
    _write_field(frame, layout, raw)
    return frame


def decode_signal_frame(frame: bytes | bytearray, spec: SignalSpec) -> float:
    """Decode a J1939 ``frame`` back to ``spec``'s engineering value.

    A frame too short to contain the field (a truncated DLC) yields ``NaN`` — the
    parameter's bits are simply absent, so a receiver has nothing to report.
    """
    layout = spec.layout
    if layout is None:
        raise ValueError(f"signal {spec.name!r} has no frame layout (not a bus signal)")
    raw = _read_field(frame, layout)
    if raw is None:  # truncated: field bits not present
        return math.nan
    return raw_to_value(raw, layout)


def _write_field(frame: bytearray, layout: FrameLayout, raw: int) -> None:
    """Place ``raw`` into ``frame`` at the layout's byte-aligned little-endian field."""
    start_byte = layout.start_bit // 8
    n_bytes = layout.bit_len // 8
    raw_bytes = int(raw).to_bytes(n_bytes, byteorder=layout.byte_order, signed=False)
    frame[start_byte : start_byte + n_bytes] = raw_bytes


def _read_field(frame: bytes | bytearray, layout: FrameLayout) -> int | None:
    """Read the field's raw integer, or ``None`` if the frame is too short."""
    start_byte = layout.start_bit // 8
    n_bytes = layout.bit_len // 8
    if len(frame) < start_byte + n_bytes:
        return None  # truncated frame — the field's bits are missing
    return int.from_bytes(
        bytes(frame[start_byte : start_byte + n_bytes]),
        byteorder=layout.byte_order,
        signed=False,
    )


def frame_to_hex(frame: bytes | bytearray) -> str:
    """Render a frame as space-free uppercase hex (e.g. ``FF3A1CFFFFFFFFFF``)."""
    return bytes(frame).hex().upper()


__all__ = [
    "MAX_FRAME_BYTES",
    "NA_BYTE",
    "value_to_raw",
    "raw_to_value",
    "encode_signal_frame",
    "decode_signal_frame",
    "frame_to_hex",
    "_na_raw",
    "_error_raw",
]
