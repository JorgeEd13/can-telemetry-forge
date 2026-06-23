"""Writers (F2): turn a :class:`SimulatedDataset` into files. Pure I/O — never
generate. See :mod:`.writers`.
"""

from __future__ import annotations

from .writers import FORMATS, write_dataset

__all__ = ["FORMATS", "write_dataset"]
