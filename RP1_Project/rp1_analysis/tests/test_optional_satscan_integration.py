from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import uuid
from dataclasses import asdict

import nbformat
from nbclient import NotebookClient
from pathlib import Path

import pandas as pd
import pytest

from rp1_analysis_v1.config import load_configuration_bundle, satscan_parameters
from rp1_analysis_v1.execution_contract import validate_secondary_completion_state
from rp1_analysis_v1.integration import (
    build_secondary_input_run_isolated,
    execute_canonical_notebook,
    finalise_interactive_run,
    validate_run_authority,
)
from rp1_analysis_v1.paths import ProjectPaths
from rp1_analysis_v1.presentation_export import export_one_presentation_figure
from rp1_analysis_v1.publication_sources import (
    PUBLICATION_AUTHORITY_DIR,
    PublicationSourceError,
    materialise_satscan_publication_sources,
)
from rp1_analysis_v1.satscan_integration import (
    OptionalSaTScanIntegrationError,
    inspect_satscan_results,
    validate_and_integrate_satscan_results_if_available,
)
from rp1_analysis_v1.secondary_clusters import (
    EXTERNAL_RESULTS_REQUIRED,
    RESULTS_VALIDATED,
    build_secondary_input_run,
)

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ROOT.parents[1]


def _paths() -> ProjectPaths:
    return ProjectPaths(ROOT)


def _run_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _product_hashes(root: Path) -> dict[str, str]:
    excluded_dirs = {"out", "build", "dist", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
    result: dict[str, str] = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root)
        if any(part in excluded_dirs or part.endswith(".egg-info") for part in rel.parts):
            continue
        if path.suffix == ".pyc":
            continue
        result[rel.as_posix()] = _sha(path)
    return result




def _run_file_hashes(run_dir: Path) -> dict[str, str]:
    return {
        path.relative_to(run_dir).as_posix(): _sha(path)
        for path in sorted(item for item in run_dir.rglob("*") if item.is_file())
    }


def _notebook_cell_source(cell_id: str) -> str:
    notebook = nbformat.read(ROOT / "RP1_Analysis_v1.ipynb", as_version=4)
    for cell in notebook.cells:
        if cell.get("id") == cell_id:
            return "".join(cell.get("source", ""))
    raise AssertionError(f"Notebook cell not found: {cell_id}")

def _registry(run_dir: Path) -> pd.DataFrame:
    return pd.read_csv(
        run_dir / "04_secondary_concentration/tables/secondary_run_registry.csv",
        keep_default_na=False,
    )


def _first_two_location_ids(path: Path) -> tuple[str, str]:
    ids: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        parts = raw.split()
        if parts:
            ids.append(parts[0])
        if len(ids) == 2:
            break
    if len(ids) != 2:
        raise AssertionError(f"Synthetic SaTScan fixture requires two governed location IDs: {path}")
    return ids[0], ids[1]



def _set_fixture_mtime_after_authority(
    paths: tuple[Path, ...],
    authority_mtime_ns: int,
) -> None:
    """Give synthetic SaTScan results a filesystem-safe post-authority mtime."""

    second_ns = 1_000_000_000

    # Use a whole-second timestamp several seconds beyond the newest
    # authority.  This remains ordered on filesystems that truncate
    # or quantise sub-second modification times.
    target_ns = (
        (authority_mtime_ns // second_ns) + 5
    ) * second_ns

    existing = tuple(
        path
        for path in paths
        if path.exists()
    )

    if not existing:
        raise AssertionError(
            "Synthetic SaTScan fixture produced no result files"
        )

    for result_path in existing:
        os.utime(
            result_path,
            ns=(target_ns, target_ns),
        )

    observed_min_ns = min(
        result_path.stat().st_mtime_ns
        for result_path in existing
    )

    if observed_min_ns < authority_mtime_ns:
        raise AssertionError(
            "Synthetic SaTScan fixture could not establish a "
            "post-authority result timestamp on this filesystem: "
            f"authority={authority_mtime_ns}, "
            f"observed_result={observed_min_ns}"
        )


def _stage_synthetic_family(
    run_dir: Path,
    model_id: str,
    *,
    omit: str | None = None,
    version: str | None = None,
    model_label: str | None = None,
    study_start: str | None = None,
    study_end: str | None = None,
    cluster_start: str = "2020/1/1",
    cluster_end: str = "2020/3/1",
    centroid: str | None = None,
    membership_ids: tuple[str, str] | None = None,
    n_locations: int = 2,
    add_auxiliary: bool = False,
) -> None:
    """Create a self-contained genuine-family-shaped fixture for this exact run.

    The fixture intentionally has an extensionless main report and no external
    provenance JSON.  It exercises integration behaviour only; it is not a
    scientific Ghana result.
    """

    row = _registry(run_dir).set_index("model_id").loc[model_id].to_dict()
    report = run_dir / str(row["results_prefix"])
    cluster = run_dir / f'{row["results_prefix"]}.col.txt'
    membership = run_dir / f'{row["results_prefix"]}.gis.txt'
    report.parent.mkdir(parents=True, exist_ok=True)
    (report.parent / "EXTERNAL_RESULTS_REQUIRED.txt").unlink(missing_ok=True)

    geo = run_dir / str(row["coordinate_path"])
    loc1, loc2 = _first_two_location_ids(geo)
    if membership_ids is not None:
        loc1, loc2 = membership_ids
    centroid_id = centroid or loc1

    governed_start = pd.Period(str(row["temporal_start"]), freq="M")
    governed_end = pd.Period(str(row["temporal_end"]), freq="M")
    start_date = study_start or governed_start.start_time.strftime("%Y/%-m/%-d")
    end_date = study_end or governed_end.end_time.strftime("%Y/%-m/%-d")
    model = str(row["model"])
    expected_label = "Discrete Poisson" if model == "discrete_poisson" else "Space-Time Permutation"
    observed_label = model_label or expected_label
    observed_version = version or str(row["engine_version_authority"])

    if omit != "report":
        report.write_text(
            f"SaTScan v{observed_version}\n"
            "Retrospective Space-Time analysis\n"
            f"using the {observed_label} model.\n"
            f"Study period.......................: {start_date} to {end_date}\n"
            "Program completed\n",
            encoding="utf-8",
        )
    if omit != "col":
        cluster.write_text(
            "Cluster Location X Y RADIUS RADIUS_MAX START_DATE END_DATE NUMBER_LOC TEST_STAT P_VALUE OBSERVED EXPECTED RR\n"
            f"1 {centroid_id} 500000 900000 10000 10000 {cluster_start} {cluster_end} {n_locations} 12.3 0.01 5 2 2.5\n",
            encoding="utf-8",
        )
    if omit != "gis":
        membership.write_text(
            "Location Cluster P_VALUE\n"
            f"{loc1} 1 0.01\n"
            f"{loc2} 1 0.01\n",
            encoding="utf-8",
        )
    if add_auxiliary:
        (report.parent / f"{model_id}.llr.txt").write_text("optional auxiliary\n", encoding="utf-8")
        (report.parent / f"{model_id}.sci.txt").write_text("optional auxiliary\n", encoding="utf-8")

    authority_paths = [
        run_dir / str(row["prm_path"]),
        run_dir / str(row["case_path"]),
        geo,
    ]
    pop_rel = str(row.get("population_path", "") or "")
    if pop_rel:
        authority_paths.append(run_dir / pop_rel)
    authority_mtime_ns = max(
        path.stat().st_mtime_ns
        for path in authority_paths
    )

    result_paths = [
        report,
        cluster,
        membership,
    ]

    if add_auxiliary:
        result_paths.extend(
            sorted(
                report.parent.glob(
                    f"{model_id}.*.txt"
                )
            )
        )

    _set_fixture_mtime_after_authority(
        tuple(dict.fromkeys(result_paths)),
        authority_mtime_ns,
    )


@pytest.fixture(scope="module")
def secondary_template():
    paths = _paths()
    run_id = _run_id("pytest_optional_satscan_template")
    run = build_secondary_input_run(paths=paths, run_id=run_id)
    try:
        yield run.run_dir
    finally:
        shutil.rmtree(run.run_dir, ignore_errors=True)


def _clone_secondary(template: Path, prefix: str):
    paths = _paths()
    run_id = _run_id(prefix)
    target = paths.resolve_inside(f"out/runs/{run_id}")
    shutil.copytree(template, target, copy_function=shutil.copy2)
    return paths, run_id, target



def test_synthetic_fixture_timestamp_is_post_authority(
    secondary_template: Path,
) -> None:
    _paths_obj, _run_id_value, run_dir = _clone_secondary(
        secondary_template,
        "pytest_optional_satscan_mtime_portability",
    )

    try:
        for model_id in (
            "MCD64A1_POISSON_PRIMARY",
            "VIIRS_STP_PRIMARY",
        ):
            _stage_synthetic_family(
                run_dir,
                model_id,
            )

            row = (
                _registry(run_dir)
                .set_index("model_id")
                .loc[model_id]
                .to_dict()
            )

            authority_paths = [
                run_dir / str(row["prm_path"]),
                run_dir / str(row["case_path"]),
                run_dir / str(row["coordinate_path"]),
            ]

            pop_rel = str(
                row.get("population_path", "") or ""
            )

            if pop_rel:
                authority_paths.append(
                    run_dir / pop_rel
                )

            result_paths = [
                run_dir / str(row["results_prefix"]),
                run_dir / f'{row["results_prefix"]}.col.txt',
                run_dir / f'{row["results_prefix"]}.gis.txt',
            ]

            authority_max_ns = max(
                item.stat().st_mtime_ns
                for item in authority_paths
            )

            result_min_ns = min(
                item.stat().st_mtime_ns
                for item in result_paths
            )

            assert result_min_ns >= authority_max_ns

    finally:
        shutil.rmtree(
            run_dir,
            ignore_errors=True,
        )


def test_no_results_is_normal_external_boundary(secondary_template: Path) -> None:
    paths, run_id, run_dir = _clone_secondary(secondary_template, "pytest_optional_satscan_none")
    try:
        result = validate_and_integrate_satscan_results_if_available(paths=paths, secondary_run_id=run_id)
        assert result.external_execution_state == EXTERNAL_RESULTS_REQUIRED
        assert result.result_families_detected == ()
        assert result.validated_model_count == 0
        assert not (run_dir / "04_secondary_concentration/publication_sources").exists()
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


@pytest.mark.parametrize("model_id", ["MCD64A1_POISSON_PRIMARY", "VIIRS_STP_PRIMARY"])
def test_one_result_family_fails_closed(model_id: str, secondary_template: Path) -> None:
    paths, run_id, run_dir = _clone_secondary(secondary_template, "pytest_optional_satscan_one")
    try:
        _stage_synthetic_family(run_dir, model_id)
        with pytest.raises(OptionalSaTScanIntegrationError, match="both governed result families"):
            validate_and_integrate_satscan_results_if_available(paths=paths, secondary_run_id=run_id)
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def test_partial_companion_file_set_fails_closed(secondary_template: Path) -> None:
    paths, run_id, run_dir = _clone_secondary(secondary_template, "pytest_optional_satscan_partial")
    try:
        _stage_synthetic_family(run_dir, "MCD64A1_POISSON_PRIMARY", omit="col")
        with pytest.raises(OptionalSaTScanIntegrationError, match="Partial SaTScan result family"):
            validate_and_integrate_satscan_results_if_available(paths=paths, secondary_run_id=run_id)
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def test_wrong_input_identity_and_path_escape_fail_closed(secondary_template: Path) -> None:
    for mode in ("wrong_hash", "escape"):
        paths, run_id, run_dir = _clone_secondary(secondary_template, f"pytest_optional_satscan_{mode}")
        try:
            for model_id in ("MCD64A1_POISSON_PRIMARY", "VIIRS_STP_PRIMARY"):
                _stage_synthetic_family(run_dir, model_id)
            reg_path = run_dir / "04_secondary_concentration/tables/secondary_run_registry.csv"
            reg = pd.read_csv(reg_path, keep_default_na=False)
            if mode == "wrong_hash":
                reg.loc[0, "case_sha256"] = "0" * 64
            else:
                old_prefix = str(reg.loc[0, "results_prefix"])
                escape_prefix = "../../../../outside"
                prm = run_dir / str(reg.loc[0, "prm_path"])
                prm.write_text(
                    prm.read_text(encoding="utf-8").replace(
                        f"ResultsFile={old_prefix}", f"ResultsFile={escape_prefix}"
                    ),
                    encoding="utf-8",
                )
                reg.loc[0, "prm_sha256"] = _sha(prm)
                reg.loc[0, "results_prefix"] = escape_prefix
                reg.loc[0, "required_report_path"] = escape_prefix
                reg.loc[0, "required_cluster_path"] = escape_prefix + ".col.txt"
                reg.loc[0, "required_membership_path"] = escape_prefix + ".gis.txt"
            reg.to_csv(reg_path, index=False, lineterminator="\n")
            with pytest.raises(OptionalSaTScanIntegrationError):
                validate_and_integrate_satscan_results_if_available(paths=paths, secondary_run_id=run_id)
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)



@pytest.mark.parametrize("missing_part", ["report", "col", "gis"])
def test_each_missing_core_result_member_fails_closed(missing_part: str, secondary_template: Path) -> None:
    paths, run_id, run_dir = _clone_secondary(secondary_template, f"pytest_optional_satscan_missing_{missing_part}")
    try:
        _stage_synthetic_family(run_dir, "MCD64A1_POISSON_PRIMARY", omit=missing_part)
        _stage_synthetic_family(run_dir, "VIIRS_STP_PRIMARY")
        with pytest.raises(OptionalSaTScanIntegrationError, match="Partial SaTScan result family"):
            validate_and_integrate_satscan_results_if_available(paths=paths, secondary_run_id=run_id)
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def test_wrong_resultsfile_in_current_prm_fails_closed(secondary_template: Path) -> None:
    paths, run_id, run_dir = _clone_secondary(secondary_template, "pytest_optional_satscan_wrong_resultsfile")
    try:
        for model_id in ("MCD64A1_POISSON_PRIMARY", "VIIRS_STP_PRIMARY"):
            _stage_synthetic_family(run_dir, model_id)
        reg_path = run_dir / "04_secondary_concentration/tables/secondary_run_registry.csv"
        reg = pd.read_csv(reg_path, keep_default_na=False)
        row = reg.iloc[0]
        prm = run_dir / str(row["prm_path"])
        prm.write_text(prm.read_text(encoding="utf-8").replace(str(row["results_prefix"]), "wrong/results/prefix"), encoding="utf-8")
        reg.loc[0, "prm_sha256"] = _sha(prm)
        reg.to_csv(reg_path, index=False, lineterminator="\n")
        with pytest.raises(OptionalSaTScanIntegrationError, match="ResultsFile authority mismatch"):
            validate_and_integrate_satscan_results_if_available(paths=paths, secondary_run_id=run_id)
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


@pytest.mark.parametrize("authority", ["prm", "case", "geo", "mcd_pop"])
def test_changed_deterministic_interface_authority_fails_closed(authority: str, secondary_template: Path) -> None:
    paths, run_id, run_dir = _clone_secondary(secondary_template, f"pytest_optional_satscan_changed_{authority}")
    try:
        for model_id in ("MCD64A1_POISSON_PRIMARY", "VIIRS_STP_PRIMARY"):
            _stage_synthetic_family(run_dir, model_id)
        reg = _registry(run_dir)
        row = reg.loc[reg["model_id"].eq("MCD64A1_POISSON_PRIMARY")].iloc[0]
        key = {"prm": "prm_path", "case": "case_path", "geo": "coordinate_path", "mcd_pop": "population_path"}[authority]
        target = run_dir / str(row[key])
        target.write_bytes(target.read_bytes() + b"\nTEST_MUTATION\n")
        with pytest.raises(OptionalSaTScanIntegrationError, match="authority mismatch|Parameter-file authority"):
            validate_and_integrate_satscan_results_if_available(paths=paths, secondary_run_id=run_id)
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def test_viirs_population_file_contract_violation_fails_closed(secondary_template: Path) -> None:
    paths, run_id, run_dir = _clone_secondary(secondary_template, "pytest_optional_satscan_viirs_pop")
    try:
        for model_id in ("MCD64A1_POISSON_PRIMARY", "VIIRS_STP_PRIMARY"):
            _stage_synthetic_family(run_dir, model_id)
        row = _registry(run_dir).set_index("model_id").loc["VIIRS_STP_PRIMARY"]
        prm = run_dir / str(row["prm_path"])
        prm.with_suffix(".pop").write_text("unexpected exposure\n", encoding="utf-8")
        with pytest.raises(OptionalSaTScanIntegrationError, match="unexpected population file"):
            validate_and_integrate_satscan_results_if_available(paths=paths, secondary_run_id=run_id)
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


@pytest.mark.parametrize(
    "mode,kwargs,match",
    [
        ("version", {"version": "10.3.2"}, "version mismatch"),
        ("model", {"model_label": "Space-Time Permutation"}, "model identity"),
        ("period", {"study_end": "2024/11/30"}, "study period"),
    ],
)
def test_wrong_report_identity_fails_closed(mode: str, kwargs: dict[str, str], match: str, secondary_template: Path) -> None:
    paths, run_id, run_dir = _clone_secondary(secondary_template, f"pytest_optional_satscan_wrong_{mode}")
    try:
        _stage_synthetic_family(run_dir, "MCD64A1_POISSON_PRIMARY", **kwargs)
        _stage_synthetic_family(run_dir, "VIIRS_STP_PRIMARY")
        with pytest.raises(OptionalSaTScanIntegrationError, match=match):
            validate_and_integrate_satscan_results_if_available(paths=paths, secondary_run_id=run_id)
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def test_unknown_membership_location_fails_closed(secondary_template: Path) -> None:
    paths, run_id, run_dir = _clone_secondary(secondary_template, "pytest_optional_satscan_unknown_membership")
    try:
        row = _registry(run_dir).set_index("model_id").loc["MCD64A1_POISSON_PRIMARY"]
        geo = run_dir / str(row["coordinate_path"])
        _, loc2 = _first_two_location_ids(geo)
        _stage_synthetic_family(run_dir, "MCD64A1_POISSON_PRIMARY", membership_ids=("999999", loc2))
        _stage_synthetic_family(run_dir, "VIIRS_STP_PRIMARY")
        with pytest.raises(OptionalSaTScanIntegrationError, match="location outside the governed run"):
            validate_and_integrate_satscan_results_if_available(paths=paths, secondary_run_id=run_id)
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def test_unknown_cluster_centroid_fails_closed(secondary_template: Path) -> None:
    paths, run_id, run_dir = _clone_secondary(secondary_template, "pytest_optional_satscan_unknown_centroid")
    try:
        _stage_synthetic_family(run_dir, "MCD64A1_POISSON_PRIMARY", centroid="999999")
        _stage_synthetic_family(run_dir, "VIIRS_STP_PRIMARY")
        with pytest.raises(OptionalSaTScanIntegrationError, match="centroid"):
            validate_and_integrate_satscan_results_if_available(paths=paths, secondary_run_id=run_id)
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def test_inconsistent_cluster_membership_count_fails_closed(secondary_template: Path) -> None:
    paths, run_id, run_dir = _clone_secondary(secondary_template, "pytest_optional_satscan_bad_membership_count")
    try:
        _stage_synthetic_family(run_dir, "MCD64A1_POISSON_PRIMARY", n_locations=3)
        _stage_synthetic_family(run_dir, "VIIRS_STP_PRIMARY")
        with pytest.raises(OptionalSaTScanIntegrationError, match="membership count"):
            validate_and_integrate_satscan_results_if_available(paths=paths, secondary_run_id=run_id)
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def test_excessive_cluster_temporal_duration_fails_closed(secondary_template: Path) -> None:
    paths, run_id, run_dir = _clone_secondary(secondary_template, "pytest_optional_satscan_duration")
    try:
        _stage_synthetic_family(
            run_dir,
            "MCD64A1_POISSON_PRIMARY",
            cluster_start="2020/1/1",
            cluster_end="2021/1/1",
        )
        _stage_synthetic_family(run_dir, "VIIRS_STP_PRIMARY")
        with pytest.raises(OptionalSaTScanIntegrationError, match="temporal-window maximum"):
            validate_and_integrate_satscan_results_if_available(paths=paths, secondary_run_id=run_id)
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def test_stale_result_files_fail_closed(secondary_template: Path) -> None:
    paths, run_id, run_dir = _clone_secondary(secondary_template, "pytest_optional_satscan_stale")
    try:
        for model_id in ("MCD64A1_POISSON_PRIMARY", "VIIRS_STP_PRIMARY"):
            _stage_synthetic_family(run_dir, model_id)
        row = _registry(run_dir).set_index("model_id").loc["MCD64A1_POISSON_PRIMARY"]
        prm = run_dir / str(row["prm_path"])
        stale = max(1, prm.stat().st_mtime_ns - 10_000_000)
        for suffix in ("", ".col.txt", ".gis.txt"):
            path = run_dir / f'{row["results_prefix"]}{suffix}'
            os.utime(path, ns=(stale, stale))
        with pytest.raises(OptionalSaTScanIntegrationError, match="stale"):
            validate_and_integrate_satscan_results_if_available(paths=paths, secondary_run_id=run_id)
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def test_no_duplicate_txt_or_external_provenance_is_required(secondary_template: Path) -> None:
    paths, run_id, run_dir = _clone_secondary(secondary_template, "pytest_optional_satscan_exact_family")
    try:
        for model_id in ("MCD64A1_POISSON_PRIMARY", "VIIRS_STP_PRIMARY"):
            _stage_synthetic_family(run_dir, model_id)
        for row in _registry(run_dir).to_dict(orient="records"):
            prefix = run_dir / str(row["results_prefix"])
            assert prefix.is_file()
            assert not Path(str(prefix) + ".txt").exists()
            assert not Path(str(prefix) + ".provenance.json").exists()
        result = validate_and_integrate_satscan_results_if_available(paths=paths, secondary_run_id=run_id)
        assert result.external_execution_state == RESULTS_VALIDATED
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def test_optional_auxiliary_files_do_not_break_integration(secondary_template: Path) -> None:
    paths, run_id, run_dir = _clone_secondary(secondary_template, "pytest_optional_satscan_aux")
    try:
        for model_id in ("MCD64A1_POISSON_PRIMARY", "VIIRS_STP_PRIMARY"):
            _stage_synthetic_family(run_dir, model_id, add_auxiliary=True)
        result = validate_and_integrate_satscan_results_if_available(paths=paths, secondary_run_id=run_id)
        assert result.external_execution_state == RESULTS_VALIDATED
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)

def test_validated_results_are_run_local_and_complete(secondary_template: Path) -> None:
    paths, run_id, run_dir = _clone_secondary(secondary_template, "pytest_optional_satscan_valid")
    static_root = paths.root / PUBLICATION_AUTHORITY_DIR
    before = _product_hashes(static_root)
    try:
        for model_id in ("MCD64A1_POISSON_PRIMARY", "VIIRS_STP_PRIMARY"):
            _stage_synthetic_family(run_dir, model_id)
        result = validate_and_integrate_satscan_results_if_available(paths=paths, secondary_run_id=run_id)
        assert result.external_execution_state == RESULTS_VALIDATED
        assert result.validated_model_count == 2
        assert dict(result.significant_cluster_counts) == {"mcd64a1": 1, "viirs": 1}
        assert dict(result.membership_counts) == {"mcd64a1": 2, "viirs": 2}
        assert set(result.publication_source_paths) == {
            "table3_satscan_clusters", "cluster_membership_source",
            "cluster_recurrence_source", "supplement_s6_satscan",
        }
        source_root = run_dir / "04_secondary_concentration/publication_sources"
        assert source_root.is_dir()
        assert _product_hashes(static_root) == before
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def test_legacy_repository_materialiser_fails_closed() -> None:
    with pytest.raises(PublicationSourceError, match="mutation is prohibited"):
        materialise_satscan_publication_sources(
            parsed_by_model={}, scenarios=[], location_authority=pd.DataFrame(),
            run_registry=pd.DataFrame(), run_dir=ROOT,
        )



def test_preexisting_results_validated_resume_is_read_only_and_section_04_compatible(
    secondary_template: Path,
) -> None:
    paths, run_id, run_dir = _clone_secondary(
        secondary_template,
        "pytest_optional_satscan_prevalidated_resume",
    )
    try:
        for model_id in ("MCD64A1_POISSON_PRIMARY", "VIIRS_STP_PRIMARY"):
            _stage_synthetic_family(run_dir, model_id)

        first = validate_and_integrate_satscan_results_if_available(
            paths=paths, secondary_run_id=run_id
        )
        assert first.external_execution_state == RESULTS_VALIDATED
        assert first.validated_model_count == 2

        inspection_before = inspect_satscan_results(paths=paths, secondary_run_id=run_id)
        assert inspection_before.external_execution_state == RESULTS_VALIDATED
        assert inspection_before.integration_state == "INTEGRATED"
        assert inspection_before.validated_model_count == 2

        before = _run_file_hashes(run_dir)
        bundle = load_configuration_bundle(ROOT / "config")

        secondary = build_secondary_input_run_isolated(paths=paths, run_id=run_id)
        assert secondary.execution_state == RESULTS_VALIDATED

        section_04_01 = _notebook_cell_source("rp1-code-04-01")
        namespace = {
            "asdict": asdict,
            "pd": pd,
            "display": lambda _value: None,
            "satscan_parameters": satscan_parameters,
            "contracts": bundle,
            "build_secondary_input_run_isolated": build_secondary_input_run_isolated,
            "validate_secondary_completion_state": validate_secondary_completion_state,
            "paths": paths,
            "run_ids": {"secondary": run_id},
        }
        exec(compile(section_04_01, str(ROOT / "RP1_Analysis_v1.ipynb"), "exec"), namespace, namespace)
        assert namespace["secondary_gate"] == "PASS"
        assert namespace["secondary"].execution_state == RESULTS_VALIDATED

        second = validate_and_integrate_satscan_results_if_available(
            paths=paths, secondary_run_id=run_id
        )
        assert second.external_execution_state == RESULTS_VALIDATED
        assert second.validated_model_count == 2
        assert second.significant_cluster_counts == first.significant_cluster_counts
        assert second.membership_counts == first.membership_counts
        assert second.publication_source_paths == first.publication_source_paths

        inspection_after = inspect_satscan_results(paths=paths, secondary_run_id=run_id)
        assert inspection_after.external_execution_state == RESULTS_VALIDATED
        assert inspection_after.integration_state == "INTEGRATED"
        assert inspection_after.validated_model_count == 2
        assert _run_file_hashes(run_dir) == before
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


@pytest.mark.parametrize("missing_part", ["report", "col", "gis"])
def test_prevalidated_resume_fails_closed_when_core_result_member_is_missing(
    missing_part: str, secondary_template: Path
) -> None:
    paths, run_id, run_dir = _clone_secondary(
        secondary_template, f"pytest_optional_satscan_prevalidated_missing_{missing_part}"
    )
    try:
        for model_id in ("MCD64A1_POISSON_PRIMARY", "VIIRS_STP_PRIMARY"):
            _stage_synthetic_family(run_dir, model_id)
        validate_and_integrate_satscan_results_if_available(paths=paths, secondary_run_id=run_id)
        row = _registry(run_dir).set_index("model_id").loc["MCD64A1_POISSON_PRIMARY"]
        key = {
            "report": "required_report_path",
            "col": "required_cluster_path",
            "gis": "required_membership_path",
        }[missing_part]
        (run_dir / str(row[key])).unlink()
        with pytest.raises(OptionalSaTScanIntegrationError, match="Partial SaTScan result family|missing its governed external result families"):
            validate_and_integrate_satscan_results_if_available(paths=paths, secondary_run_id=run_id)
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def test_prevalidated_resume_fails_closed_on_run_local_source_hash_mismatch(
    secondary_template: Path,
) -> None:
    paths, run_id, run_dir = _clone_secondary(
        secondary_template, "pytest_optional_satscan_prevalidated_source_hash"
    )
    try:
        for model_id in ("MCD64A1_POISSON_PRIMARY", "VIIRS_STP_PRIMARY"):
            _stage_synthetic_family(run_dir, model_id)
        validate_and_integrate_satscan_results_if_available(paths=paths, secondary_run_id=run_id)
        manifest_path = run_dir / "04_secondary_concentration/publication_sources/M_SATSCAN_PUBLICATION_SOURCE_MANIFEST.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entry = manifest["sources"]["table3_satscan_clusters"]
        source = run_dir / str(entry["path"])
        source.write_bytes(source.read_bytes() + b"\n")
        with pytest.raises(OptionalSaTScanIntegrationError, match="source hash mismatch"):
            validate_and_integrate_satscan_results_if_available(paths=paths, secondary_run_id=run_id)
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)



def test_prevalidated_resume_rejects_wrong_scenario_identity(secondary_template: Path) -> None:
    paths, run_id, run_dir = _clone_secondary(
        secondary_template, "pytest_optional_satscan_prevalidated_wrong_scenario"
    )
    try:
        for model_id in ("MCD64A1_POISSON_PRIMARY", "VIIRS_STP_PRIMARY"):
            _stage_synthetic_family(run_dir, model_id)
        validate_and_integrate_satscan_results_if_available(paths=paths, secondary_run_id=run_id)
        reg_path = run_dir / "04_secondary_concentration/tables/secondary_run_registry.csv"
        reg = pd.read_csv(reg_path, keep_default_na=False)
        reg.loc[0, "scenario_id"] = "WRONG_SCENARIO"
        reg.to_csv(reg_path, index=False, lineterminator="\n")
        with pytest.raises(OptionalSaTScanIntegrationError, match="scenario IDs differ"):
            validate_and_integrate_satscan_results_if_available(paths=paths, secondary_run_id=run_id)
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def test_prevalidated_resume_rejects_changed_result_family(secondary_template: Path) -> None:
    paths, run_id, run_dir = _clone_secondary(
        secondary_template, "pytest_optional_satscan_prevalidated_changed_result"
    )
    try:
        for model_id in ("MCD64A1_POISSON_PRIMARY", "VIIRS_STP_PRIMARY"):
            _stage_synthetic_family(run_dir, model_id)
        validate_and_integrate_satscan_results_if_available(paths=paths, secondary_run_id=run_id)
        row = _registry(run_dir).set_index("model_id").loc["MCD64A1_POISSON_PRIMARY"]
        cluster = run_dir / str(row["required_cluster_path"])
        text = cluster.read_text(encoding="utf-8")
        cluster.write_text(text.replace("12.3 0.01 5 2 2.5", "12.4 0.01 5 2 2.5"), encoding="utf-8")
        authority_paths = [
            run_dir / str(row["prm_path"]),
            run_dir / str(row["case_path"]),
            run_dir / str(row["coordinate_path"]),
            run_dir / str(row["population_path"]),
        ]
        _set_fixture_mtime_after_authority((cluster,), max(item.stat().st_mtime_ns for item in authority_paths))
        with pytest.raises(OptionalSaTScanIntegrationError, match="currently validated result family"):
            validate_and_integrate_satscan_results_if_available(paths=paths, secondary_run_id=run_id)
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)

@pytest.mark.parametrize(
    "mutation,match",
    [
        ("registry_state", "run registry state is inconsistent"),
        ("validated_model_count", "validated_model_count is inconsistent"),
        ("unsupported_state", "Unsupported secondary completion state"),
    ],
)
def test_prevalidated_resume_rejects_inconsistent_recorded_state(
    mutation: str, match: str, secondary_template: Path
) -> None:
    paths, run_id, run_dir = _clone_secondary(
        secondary_template, f"pytest_optional_satscan_prevalidated_{mutation}"
    )
    try:
        for model_id in ("MCD64A1_POISSON_PRIMARY", "VIIRS_STP_PRIMARY"):
            _stage_synthetic_family(run_dir, model_id)
        validate_and_integrate_satscan_results_if_available(paths=paths, secondary_run_id=run_id)
        if mutation == "registry_state":
            reg_path = run_dir / "04_secondary_concentration/tables/secondary_run_registry.csv"
            reg = pd.read_csv(reg_path, keep_default_na=False)
            reg.loc[0, "execution_state"] = EXTERNAL_RESULTS_REQUIRED
            reg.to_csv(reg_path, index=False, lineterminator="\n")
        else:
            status_path = run_dir / "04_secondary_concentration/secondary_external_execution_status.json"
            status = json.loads(status_path.read_text(encoding="utf-8"))
            if mutation == "validated_model_count":
                status["validated_model_count"] = 1
            else:
                status["external_execution_state"] = "INPUTS_READY"
            status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with pytest.raises(OptionalSaTScanIntegrationError, match=match):
            validate_and_integrate_satscan_results_if_available(paths=paths, secondary_run_id=run_id)
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)

def test_complete_notebook_both_success_states_preserve_product_bytes() -> None:
    paths = _paths()
    before = _product_hashes(REPOSITORY_ROOT)
    run_ids: list[str] = []
    try:
        no_id = _run_id("pytest_optional_satscan_notebook_none")
        run_ids.append(no_id)
        no_result = execute_canonical_notebook(paths=paths, run_id=no_id, timeout_seconds=3600)
        assert no_result.executed_code_cells == no_result.code_cells == 14
        no_validated = validate_run_authority(paths=paths, run_id=no_id)
        assert no_validated.secondary_external_state == EXTERNAL_RESULTS_REQUIRED

        with_id = _run_id("pytest_optional_satscan_notebook_valid")
        run_ids.append(with_id)
        prepared = build_secondary_input_run_isolated(paths=paths, run_id=f"{with_id}_sec")
        for model_id in ("MCD64A1_POISSON_PRIMARY", "VIIRS_STP_PRIMARY"):
            _stage_synthetic_family(prepared.run_dir, model_id)
        with_result = execute_canonical_notebook(paths=paths, run_id=with_id, timeout_seconds=3600)
        assert with_result.executed_code_cells == with_result.code_cells == 14
        yes_validated = validate_run_authority(paths=paths, run_id=with_id)
        assert yes_validated.secondary_external_state == RESULTS_VALIDATED
        pub = paths.resolve_inside(f"out/runs/{with_id}_pub")
        tables = pd.read_csv(pub / "90_integrated/T_TABLE_REGISTRY.csv")
        figures = pd.read_csv(pub / "90_integrated/T_FIGURE_REGISTRY.csv")
        assert set(tables.loc[tables["table_id"].isin(["T3", "S6"]), "availability"]) == {"AVAILABLE"}
        assert set(figures.loc[figures["figure_id"].eq("F6"), "availability"]) == {"AVAILABLE"}
    finally:
        for run_id in run_ids:
            for suffix in ("_sec", "_pub", "_close"):
                shutil.rmtree(paths.resolve_inside(f"out/runs/{run_id}{suffix}"), ignore_errors=True)
    after = _product_hashes(REPOSITORY_ROOT)
    assert before == after


def test_direct_interactive_notebook_completion_validates_and_exports_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise the genuine direct-Jupyter completion path end to end.

    The canonical notebook is executed by nbclient only as a kernel transport;
    unlike ``execute_canonical_notebook`` no controlled-wrapper execution mode
    is supplied, so Section 99 must create the governed interactive completion
    authority itself.
    """

    paths = _paths()
    before_product = _product_hashes(REPOSITORY_ROOT)
    run_id = _run_id("pytest_direct_interactive")
    output_dir = tmp_path / "rq1_export"
    run_dirs = [
        paths.resolve_inside(f"out/runs/{run_id}{suffix}")
        for suffix in ("_sec", "_pub", "_close")
    ]
    notebook_path = paths.resolve_inside("RP1_Analysis_v1.ipynb")
    try:
        monkeypatch.setenv("RP1_ANALYSIS_V1_ROOT", str(paths.root))
        monkeypatch.setenv("RP1_NOTEBOOK_RUN_ID", run_id)
        monkeypatch.delenv("RP1_NOTEBOOK_EXECUTION_MODE", raising=False)
        monkeypatch.setenv("MPLBACKEND", "Agg")
        monkeypatch.setenv("OMP_NUM_THREADS", "1")
        monkeypatch.setenv("OPENBLAS_NUM_THREADS", "1")
        monkeypatch.setenv("MKL_NUM_THREADS", "1")
        monkeypatch.setenv("NUMEXPR_NUM_THREADS", "1")
        monkeypatch.setenv("PYTHONHASHSEED", "0")

        notebook = nbformat.read(notebook_path, as_version=4)
        with tempfile.TemporaryDirectory(prefix="rp1_direct_interactive_cwd_") as isolated_cwd:
            executed = NotebookClient(
                notebook,
                timeout=3600,
                kernel_name="python3",
                allow_errors=False,
                resources={"metadata": {"path": isolated_cwd}},
            ).execute()
        code_cells = [cell for cell in executed.cells if cell.cell_type == "code"]
        assert code_cells and all(cell.get("execution_count") is not None for cell in code_cells)

        closeout = paths.resolve_inside(f"out/runs/{run_id}_close")
        execution_path = closeout / "99_closeout/M_NOTEBOOK_EXECUTION.json"
        record = json.loads(execution_path.read_text(encoding="utf-8"))
        assert record["execution_mode"] == "interactive_jupyter"
        assert record["notebook_snapshot_required"] is False
        assert record["notebook_snapshot_available"] is False
        assert not (closeout / "99_closeout/RP1_Analysis_v1.executed.ipynb").exists()

        first = validate_run_authority(paths=paths, run_id=run_id)
        second = validate_run_authority(paths=paths, run_id=run_id)
        assert first.status == second.status == "PASS"
        repeated = finalise_interactive_run(paths=paths, run_id=run_id)
        assert repeated.status == "PASS"
        assert repeated.reused_existing_record is True

        source_before = {path.name: _run_file_hashes(path) for path in run_dirs}
        exported = export_one_presentation_figure(
            run_dir=closeout,
            output_dir=output_dir,
            export_id="rq1_acz_seasonality",
            paths=paths,
        )
        assert exported["status"] == "PASS"
        source_after = {path.name: _run_file_hashes(path) for path in run_dirs}
        assert source_after == source_before
        assert validate_run_authority(paths=paths, run_id=run_id).status == "PASS"
    finally:
        for path in run_dirs:
            shutil.rmtree(path, ignore_errors=True)
        shutil.rmtree(output_dir, ignore_errors=True)

    assert _product_hashes(REPOSITORY_ROOT) == before_product


def test_complete_notebook_resumes_preintegrated_results_validated_state_read_only(tmp_path: Path) -> None:
    """Begin from a genuinely integrated validated secondary authority.

    The synthetic SaTScan family is test-only.  It exists solely to exercise
    resume/validation/export contracts and is not Ghana study evidence.
    """

    paths = _paths()
    before_product = _product_hashes(REPOSITORY_ROOT)
    run_id = _run_id("pytest_optional_satscan_preintegrated")
    output_dir = tmp_path / "rq4_export"
    run_dirs = [
        paths.resolve_inside(f"out/runs/{run_id}{suffix}")
        for suffix in ("_sec", "_pub", "_close")
    ]
    try:
        prepared = build_secondary_input_run_isolated(paths=paths, run_id=f"{run_id}_sec")
        for model_id in ("MCD64A1_POISSON_PRIMARY", "VIIRS_STP_PRIMARY"):
            _stage_synthetic_family(prepared.run_dir, model_id)
        integrated = validate_and_integrate_satscan_results_if_available(
            paths=paths, secondary_run_id=f"{run_id}_sec"
        )
        assert integrated.external_execution_state == RESULTS_VALIDATED
        inspection = inspect_satscan_results(paths=paths, secondary_run_id=f"{run_id}_sec")
        assert inspection.integration_state == "INTEGRATED"
        secondary_before = _run_file_hashes(prepared.run_dir)

        executed = execute_canonical_notebook(paths=paths, run_id=run_id, timeout_seconds=3600)
        assert executed.executed_code_cells == executed.code_cells == 14
        assert _run_file_hashes(prepared.run_dir) == secondary_before

        first = validate_run_authority(paths=paths, run_id=run_id)
        second = validate_run_authority(paths=paths, run_id=run_id)
        assert first.status == second.status == "PASS"
        assert first.secondary_external_state == second.secondary_external_state == RESULTS_VALIDATED
        assert _run_file_hashes(prepared.run_dir) == secondary_before

        source_before = {
            path.name: _run_file_hashes(path)
            for path in run_dirs
            if path.is_dir()
        }
        exported = export_one_presentation_figure(
            run_dir=paths.resolve_inside(f"out/runs/{run_id}_close"),
            output_dir=output_dir,
            export_id="rq4_mcd64a1_clusters",
            paths=paths,
        )
        assert exported["status"] == "PASS"
        assert _run_file_hashes(prepared.run_dir) == secondary_before
        source_after = {
            path.name: _run_file_hashes(path)
            for path in run_dirs
            if path.is_dir()
        }
        assert source_after == source_before
        assert validate_run_authority(paths=paths, run_id=run_id).status == "PASS"
    finally:
        for path in run_dirs:
            shutil.rmtree(path, ignore_errors=True)
        shutil.rmtree(output_dir, ignore_errors=True)

    assert _product_hashes(REPOSITORY_ROOT) == before_product


def test_marker_only_state_a_status_remains_external_results_required(secondary_template: Path) -> None:
    paths, run_id, run_dir = _clone_secondary(secondary_template, "pytest_optional_satscan_status_state_a")
    try:
        markers = list(run_dir.glob("04_secondary_concentration/**/EXTERNAL_RESULTS_REQUIRED.txt"))
        assert len(markers) == 2
        result = inspect_satscan_results(paths=paths, secondary_run_id=run_id)
        assert result.external_execution_state == EXTERNAL_RESULTS_REQUIRED
        assert result.integration_state == "NOT_INTEGRATED"
        assert result.result_families_detected == ()
        assert result.validated_model_count == 0
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def test_observed_invalid_parameter_failure_shape_is_not_integrable(secondary_template: Path) -> None:
    paths, run_id, run_dir = _clone_secondary(secondary_template, "pytest_optional_satscan_observed_d09")
    try:
        row = _registry(run_dir).set_index("model_id").loc["MCD64A1_POISSON_PRIMARY"].to_dict()
        report = run_dir / str(row["results_prefix"])
        report.parent.mkdir(parents=True, exist_ok=True)
        (report.parent / "EXTERNAL_RESULTS_REQUIRED.txt").unlink(missing_ok=True)
        report.write_bytes(b"")

        with pytest.raises(OptionalSaTScanIntegrationError, match="Partial SaTScan result family"):
            inspect_satscan_results(paths=paths, secondary_run_id=run_id)
        with pytest.raises(OptionalSaTScanIntegrationError, match="Partial SaTScan result family"):
            validate_and_integrate_satscan_results_if_available(paths=paths, secondary_run_id=run_id)
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)
