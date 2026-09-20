"""geo_data_prep.exports

Stage 1 export artefacts.

These modules implement *export* outputs that sit downstream of the core
processing steps (normalisation, overlay, QA). They are designed to be called
from a future pipeline/CLI command, but are fully testable as pure functions
given suitable GeoDataFrames.

Export modules:
- unit_universe.csv
- per-zone Shapefile splits
- "combined" boundaries export (two Shapefiles + manifest JSON)
"""

from .combined import CombinedWriteOutputs, write_combined_boundaries
from .splits import SplitWriteOutputs, write_zone_splits
from .universe import UnitUniverseColumns, build_unit_universe_dataframe, write_unit_universe_csv

__all__ = [
    "write_unit_universe_csv",
    "build_unit_universe_dataframe",
    "UnitUniverseColumns",
    "write_zone_splits",
    "SplitWriteOutputs",
    "write_combined_boundaries",
    "CombinedWriteOutputs",
]
