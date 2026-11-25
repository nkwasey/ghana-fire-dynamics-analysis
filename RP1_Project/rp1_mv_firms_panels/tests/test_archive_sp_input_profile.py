"""Archive interface/admission tests derive expectations from supplied records."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from mv_firms_panels.core.config import FirmsSensorInput, load_config
from mv_firms_panels.core.hashing import sha256_file
from mv_firms_panels.core.input_profiles import (
    ARCHIVE_PROFILE,
    INTAKE_SCHEMA,
    InputProfileError,
    adapt_archive_sp,
    source_profile_evidence,
)
from mv_firms_panels.stages.prepare_year import PrepareYearError, prepare_year
from pydantic import ValidationError
from shapely.geometry import Point, box

ROOT = Path(__file__).resolve().parents[1]


def records(sensor="viirs"):
    viirs = sensor == "viirs"
    return gpd.GeoDataFrame(
        {
            "obs_id": ["gfa2:one", "gfa2:two"],
            "acq_date": ["2024-01-02"] * 2,
            "time_utc": ["01:03", "13:07"],
            "platform": ["Suomi-NPP" if viirs else "Aqua"] * 2,
            "instrument": ["VIIRS" if viirs else "MODIS"] * 2,
            "confidence": ["low", "nominal"],
            "conf_raw": ["l", "n"] if viirs else ["10", "55"],
            "frp_mw": [0.0, 45678.9],
            "bright_k": [300.0, 301.0],
            "bright_aux": [280.0, 281.0],
            "daynight": ["N", "D"],
            "district": ["source district"] * 2,
            "zone": ["source zone"] * 2,
            "scan_km": [1.0, 1.0],
            "track_km": [1.0, 1.0],
            "source": ["VIIRS_SNPP_SP" if viirs else "MODIS_SP"] * 2,
            "processing": ["SP"] * 2,
            "version": ["2" if viirs else "61.03"] * 2,
            "fire_type": ["0", "2"],
        },
        geometry=[Point(-1, 8), Point(-2, 9)],
        crs=4326,
    )


def staged(tmp_path, points, sensor="viirs"):
    """A self-contained, hash-bound annual fixture, not historical output values."""
    basename = f"Ghana_{'VIIRS_SNPP' if sensor == 'viirs' else 'MODIS'}_SP_2024"
    shp = tmp_path / "data" / "raw" / sensor / f"{basename}.shp"
    shp.parent.mkdir(parents=True, exist_ok=True)
    points.to_file(shp, driver="ESRI Shapefile", encoding="UTF-8")

    def identity(p):
        return {
            "path": p.relative_to(tmp_path).as_posix(),
            "sha256": sha256_file(p),
            "size_bytes": p.stat().st_size,
        }

    authority = tmp_path / "data/raw/source_provenance"
    authority.mkdir(parents=True, exist_ok=True)
    export = authority / "annual-export.json"
    export.write_text(json.dumps({"fixture": "annual export"}), encoding="utf-8")
    companions = {}
    for name in ("provenance", "field_dictionary"):
        path = authority / (name + ".json")
        path.write_text(json.dumps({"fixture": name}), encoding="utf-8")
        companions[name] = identity(path)
    family = {
        "sensor": sensor,
        "year": 2024,
        "path": shp.relative_to(tmp_path).as_posix(),
        "record_count": len(points),
        "source": "VIIRS_SNPP_SP" if sensor == "viirs" else "MODIS_SP",
        "processing": "SP",
        "platforms": ["Suomi-NPP"] if sensor == "viirs" else ["Aqua"],
        "allowed_versions": ["2"] if sensor == "viirs" else ["61.03"],
        "components": [identity(p) for p in sorted(shp.parent.glob(basename + ".*"))],
        **companions,
    }
    manifest = authority / "archive_sp_intake.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": INTAKE_SCHEMA,
                "input_profile": ARCHIVE_PROFILE,
                "archive_export": identity(export),
                "families": [family],
            }
        ),
        encoding="utf-8",
    )
    inp = FirmsSensorInput(
        file_glob=f"data/raw/{sensor}/*.shp",
        input_profile=ARCHIVE_PROFILE,
        admission_manifest=manifest.relative_to(tmp_path).as_posix(),
    )
    return shp, inp, manifest


@pytest.mark.parametrize("sensor", ["modis", "viirs"])
def test_lossless_archive_view_and_identity(tmp_path, sensor):
    points = records(sensor)
    shp, inp, manifest = staged(tmp_path, points, sensor)
    view, profile = adapt_archive_sp(
        points=points,
        input_config=inp,
        repo_root=tmp_path,
        sensor=sensor,
        year=2024,
        points_path=shp,
    )
    assert view["FRP"].tolist() == points["frp_mw"].tolist()
    assert view["CONFIDENCE"].tolist() == points["conf_raw"].tolist()
    assert view["LATITUDE"].tolist() == points.geometry.y.tolist()
    assert view["LONGITUDE"].tolist() == points.geometry.x.tolist()
    assert view["ACQ_TIME"].tolist() == ["0103", "1307"]
    assert view["TYPE"].tolist() == [0, 2]
    assert set(view["SATELLITE"]) == ({"N"} if sensor == "viirs" else {"Aqua"})
    assert view["obs_id"].tolist() == points["obs_id"].tolist()
    assert profile["frp_values_preserved"]
    evidence = source_profile_evidence(
        input_config=inp, repo_root=tmp_path, sensor=sensor, year=2024, points_path=shp
    )
    assert evidence["admission_manifest_sha256"] == sha256_file(manifest)


def test_viirs_accepts_producer_confidence_aliases_without_changing_raw_values(tmp_path):
    points = records()
    points["conf_raw"] = ["L", "Nominal"]
    shp, inp, _ = staged(tmp_path, points)

    view, _ = adapt_archive_sp(
        points=gpd.read_file(shp),
        input_config=inp,
        repo_root=tmp_path,
        sensor="viirs",
        year=2024,
        points_path=shp,
    )

    assert view["CONFIDENCE"].tolist() == ["L", "Nominal"]
    assert view["confidence"].tolist() == ["low", "nominal"]


@pytest.mark.parametrize(
    "field,bad,match",
    [
        ("source", "VIIRS_NOAA20_SP", "source"),
        ("processing", "NRT", "processing"),
        ("platform", "NOAA-20", "platform"),
        ("instrument", "MODIS", "instrument"),
        ("version", "1", "version"),
        ("time_utc", "24:00", "HH:MM"),
        ("time_utc", "0103", "HH:MM"),
        ("acq_date", "2023-01-02", "selected year"),
        ("acq_date", "2024-02-30", "date"),
        ("fire_type", "", "missing/blank"),
        ("fire_type", "0.5", "TYPE"),
        ("fire_type", "9", "TYPE"),
        ("conf_raw", "x", "l/n/h"),
        ("confidence", "high", "confidence"),
        ("frp_mw", float("inf"), "finite"),
        ("frp_mw", -1.0, "nonnegative"),
        ("daynight", "?", "daynight"),
        ("obs_id", "gfa2:two", "unique"),
    ],
)
def test_reject_invalid_archive_observations(tmp_path, field, bad, match):
    points = records()
    # Bind the valid file, then exercise record validation directly on altered values.
    shp, inp, _ = staged(tmp_path, points)
    points.loc[0, field] = bad
    with pytest.raises(InputProfileError, match=match):
        adapt_archive_sp(
            points=points,
            input_config=inp,
            repo_root=tmp_path,
            sensor="viirs",
            year=2024,
            points_path=shp,
        )


@pytest.mark.parametrize(
    "failure", ["missing_crs", "wrong_crs", "null", "empty", "nonfinite", "conflict", "3d"]
)
def test_geometry_is_governed(tmp_path, failure):
    points = records()
    shp, inp, _ = staged(tmp_path, points)
    if failure == "missing_crs":
        points = points.set_crs(None, allow_override=True)
    elif failure == "wrong_crs":
        points = points.to_crs(3857)
    elif failure == "null":
        points.loc[0, "geometry"] = None
    elif failure == "empty":
        points.loc[0, "geometry"] = Point()
    elif failure == "nonfinite":
        points.loc[0, "geometry"] = Point(float("inf"), 8)
    elif failure == "3d":
        points.loc[0, "geometry"] = Point(-1, 8, float("inf"))
    else:
        points["LATITUDE"] = [0.0, 0.0]
    with pytest.raises(InputProfileError):
        adapt_archive_sp(
            points=points,
            input_config=inp,
            repo_root=tmp_path,
            sensor="viirs",
            year=2024,
            points_path=shp,
        )


@pytest.mark.parametrize("suffix", [".shp", ".shx", ".dbf", ".prj", ".cpg"])
def test_every_sidecar_hash_is_bound(tmp_path, suffix):
    shp, inp, _ = staged(tmp_path, records())
    part = shp.with_suffix(suffix)
    part.write_bytes(part.read_bytes() + b"changed")
    with pytest.raises(InputProfileError, match="Changed Archive component"):
        source_profile_evidence(
            input_config=inp, repo_root=tmp_path, sensor="viirs", year=2024, points_path=shp
        )


def test_manifest_and_companion_admission(tmp_path):
    shp, inp, manifest = staged(tmp_path, records())
    doc = json.loads(manifest.read_text())
    doc["families"].append(doc["families"][0])
    manifest.write_text(json.dumps(doc))
    with pytest.raises(InputProfileError, match="exactly one"):
        source_profile_evidence(
            input_config=inp, repo_root=tmp_path, sensor="viirs", year=2024, points_path=shp
        )
    doc["families"].pop()
    manifest.write_text(json.dumps(doc))
    companion = tmp_path / doc["families"][0]["provenance"]["path"]
    companion.write_text("changed")
    with pytest.raises(InputProfileError, match="Changed Archive provenance"):
        source_profile_evidence(
            input_config=inp, repo_root=tmp_path, sensor="viirs", year=2024, points_path=shp
        )


def test_profile_configuration_is_explicit():
    assert FirmsSensorInput(file_glob="*.shp").input_profile == "native_firms_v1"
    with pytest.raises(ValidationError, match="requires admission_manifest"):
        FirmsSensorInput(file_glob="*.shp", input_profile=ARCHIVE_PROFILE)
    with pytest.raises(ValidationError, match="only supported"):
        FirmsSensorInput(file_glob="*.shp", admission_manifest="manifest.json")


@pytest.mark.parametrize("input_kind", ["points_gdf", "polygons_by_level", "land_mask_gdf"])
def test_governed_archive_writes_cannot_bind_unverified_in_memory_inputs(tmp_path, input_kind):
    points = records()
    shp, inp, _ = staged(tmp_path, points)
    cfg = load_config(
        ROOT / "configs/example_project.yaml", validate_paths=False
    ).config.model_copy(deep=True)
    inp.column_map = cfg.io.inputs.firms_points["viirs"].column_map
    cfg.io.inputs.firms_points["viirs"] = inp
    value = {"district": points} if input_kind == "polygons_by_level" else points
    with pytest.raises(PrepareYearError, match="file-backed inputs"):
        prepare_year(
            cfg=cfg,
            repo_root=tmp_path,
            sensor="viirs",
            year=2024,
            points_path=shp,
            **{input_kind: value},
            run_id="unverified_frame",
        )


@pytest.mark.parametrize(
    "failure", ["schema", "profile", "count", "escape", "missing", "extra", "archive_export"]
)
def test_admission_rejects_incomplete_or_inconsistent_family(tmp_path, failure):
    points = records()
    shp, inp, manifest = staged(tmp_path, points)
    doc = json.loads(manifest.read_text())
    if failure == "schema":
        doc["schema"] = "unknown"
    elif failure == "profile":
        doc["input_profile"] = "native_firms_v1"
    elif failure == "count":
        doc["families"][0]["record_count"] += 1
    elif failure == "escape":
        doc["families"][0]["path"] = "../outside.shp"
    elif failure == "missing":
        shp.with_suffix(".prj").unlink()
    elif failure == "archive_export":
        (tmp_path / doc["archive_export"]["path"]).write_text("changed")
    else:
        shp.with_suffix(".qix").write_bytes(b"unadmitted")
    manifest.write_text(json.dumps(doc))
    with pytest.raises(InputProfileError):
        adapt_archive_sp(
            points=points,
            input_config=inp,
            repo_root=tmp_path,
            sensor="viirs",
            year=2024,
            points_path=shp,
        )


@pytest.mark.parametrize("value", ["NaN", "101", "-1", "inf"])
def test_modis_native_confidence_domain(tmp_path, value):
    points = records("modis")
    shp, inp, _ = staged(tmp_path, points, "modis")
    points.loc[0, "conf_raw"] = value
    with pytest.raises(InputProfileError, match="confidence 0..100"):
        adapt_archive_sp(
            points=points,
            input_config=inp,
            repo_root=tmp_path,
            sensor="modis",
            year=2024,
            points_path=shp,
        )


def test_preparation_retains_independent_frp_and_trace(tmp_path, monkeypatch):
    import mv_firms_panels.stages.prepare_year as stage

    points = records()
    points["geometry"] = [Point(-1, 8), Point(-1, 8)]
    points["time_utc"] = "13:07"
    points["fire_type"] = "0"
    points["frp_mw"] = [100.0, 4.0]
    shp, inp, _ = staged(tmp_path, points)
    cfg = load_config(
        ROOT / "configs/example_project.yaml", validate_paths=False
    ).config.model_copy(deep=True)
    inp.column_map = cfg.io.inputs.firms_points["viirs"].column_map
    cfg.io.inputs.firms_points["viirs"] = inp
    cfg.io.inputs.land_mask = None
    cfg.outputs.prepare_year_qa_exports.enabled = False
    shutil.copytree(ROOT / "configs/schemas", tmp_path / "configs/schemas")

    def join(**kwargs):
        out = kwargs["points"].copy()
        out["unit_id"], out["unit_name"], out["level"] = "A1", "RP1 governed unit", kwargs["level"]
        return out

    monkeypatch.setattr(stage, "join_points_to_units", join)
    polygons = {
        level.level: gpd.GeoDataFrame(
            {level.unit_id_field: ["A1"], level.unit_name_field: ["RP1 governed unit"]},
            geometry=[box(-3, 7, 0, 10)],
            crs=4326,
        )
        for level in cfg.io.inputs.polygons
    }
    for level in cfg.io.inputs.polygons:
        path = tmp_path / level.path
        path.parent.mkdir(parents=True, exist_ok=True)
        polygons[level.level].to_file(path, driver="ESRI Shapefile", encoding="UTF-8")
    result = prepare_year(
        cfg=cfg,
        repo_root=tmp_path,
        sensor="viirs",
        year=2024,
        run_id="profile_test",
        points_path=shp,
    )
    assert set(result.fires_canonical.frp_mw) == {100.0}
    assert set(result.fires_canonical.conf_cat) == {"l"}
    assert set(result.fires_frp_canonical.frp_mw) == {4.0}
    assert set(result.fires_frp_canonical.conf_cat) == {"n"}
    assert "obs_id" not in result.fires_canonical.columns
    qa = result.qa_summary
    trace_path = tmp_path / qa["source_observation_trace_csv"]["path"]
    trace = pd.read_csv(trace_path)
    assert set(trace.loc[trace.stream == "count", "obs_id"]) == {points.obs_id.iloc[0]}
    assert set(trace.loc[trace.stream == "frp", "obs_id"]) == {points.obs_id.iloc[1]}
    assert qa["input_profile_evidence"]["profile"] == ARCHIVE_PROFILE
    assert qa["schema_file_identity"]
