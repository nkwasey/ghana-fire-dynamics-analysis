from __future__ import annotations


def test_import_package() -> None:
    import geo_data_prep  # noqa: F401


def test_import_subpackages() -> None:
    import geo_data_prep.cli  # noqa: F401
    import geo_data_prep.core  # noqa: F401
    import geo_data_prep.derive  # noqa: F401
    import geo_data_prep.exports  # noqa: F401
    import geo_data_prep.io  # noqa: F401
    import geo_data_prep.normalise  # noqa: F401
    import geo_data_prep.plots  # noqa: F401
    import geo_data_prep.qa  # noqa: F401
    import geo_data_prep.spatial  # noqa: F401
