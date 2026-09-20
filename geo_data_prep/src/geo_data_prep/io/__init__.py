"""I/O helpers.

Stage 1 is Shapefile-first: robust read/write helpers live in :mod:`geo_data_prep.io`.
"""

from .read import ReadError, ReadResult, read_shapefile
from .write import WriteError, WriteResult, write_shapefile

__all__ = [
    "ReadError",
    "ReadResult",
    "read_shapefile",
    "WriteError",
    "WriteResult",
    "write_shapefile",
]
