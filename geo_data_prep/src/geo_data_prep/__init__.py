"""Stage 1 geodata and metadata preparation without ArcPy.

The package keeps import-time behaviour lightweight and exposes the stable
module layout used by the Stage 1 geography workflow. Binding behaviour is
defined by the shipped configuration, contract documentation and tests.
"""

from __future__ import annotations

__all__ = ["__version__"]
__version__ = "0.1.1"
