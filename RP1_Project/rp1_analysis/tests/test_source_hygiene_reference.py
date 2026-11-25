"""Archive input checks distinguish output policies and regex patterns."""
import json
from pathlib import Path

from source_hygiene_reference import (archive_input_literals, runtime_scan_text, runtime_source_files,
                                      LOCAL_ARCHIVE_IO_TOOLS, LOCAL_ARCHIVE_INTAKE_TOOLS,
                                      LOCAL_ARCHIVE_PRODUCERS, GENERATED_PRESENTATION_ROOTS,
                                      ARCHIVE_COMPONENT, LOCAL_ARCHIVE_COMPONENT_CODE,
                                      LOCAL_ARCHIVE_COMPONENT_DOCUMENTATION)

PROVENANCE = "RP1_Project/rp1_mv_firms_panels/data/raw/source_provenance/"


def _synthetic_archive_name(stem):
    """Construct in-memory scanner controls, never archive inputs to acquire."""
    return stem + ".zip"


def _write_authority(tmp_path, name, payload):
    path = tmp_path / PROVENANCE / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _export_identity():
    return {"source": "MODIS_SP", "year": 2024,
            "annual_shapefile_zip": _synthetic_archive_name("MODIS/Ghana_MODIS_SP_2024"), "sha256": "a" * 64}


def test_archive_dependency_literals_do_not_confuse_regex_with_inputs():
    source = "import re\npattern = re.compile(r'out/releases/[a-z]+\\.zip')\narchive = 'attachment.zip'\n"
    assert archive_input_literals(source) == ["attachment" + ".zip"]


def test_packaging_policy_exclusions_do_not_hide_archive_input_fields(tmp_path):
    path = tmp_path / "configs/clean_source_package.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"schema": "rp1-clean-source-package-v1",
                               "exclude_file_patterns": ["*" + ".zip"],
                               "input_archive": "attachment" + ".zip"}))
    text = runtime_scan_text(path, tmp_path)
    assert "*" + ".zip" not in text and "attachment" + ".zip" in text


def test_runtime_scan_prunes_generated_and_test_directories(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "module.py").write_text("source\n")
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "generated.py").write_text("generated\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_example.py").write_text("test\n")
    assert [p.relative_to(tmp_path).as_posix() for p in runtime_source_files(tmp_path)] == ["src/module.py"]


def test_qualification_suffix_exclusions_do_not_hide_archive_inputs(tmp_path):
    path = tmp_path / "RP1_Project/rp1_analysis/config/qualification_contract.yml"
    path.parent.mkdir(parents=True)
    path.write_text("schema_version: rp1-qualification-contract-v1\n"
                    "generated_artifacts:\n  file_suffixes: [" + ".zip" + "]\n"
                    "input_archive: attachment" + ".zip\n")
    text = runtime_scan_text(path, tmp_path)
    assert '".zip"' not in text and "attachment" + ".zip" in text


def test_archive_export_source_identity_is_data_and_runtime_fields_remain_visible(tmp_path):
    row = _export_identity()
    row["input_archive"] = _synthetic_archive_name("runtime_dependency")
    path = _write_authority(tmp_path, "annual-export.json", {
        "contract": "ghana-firms-gee-annual-export-v1", "partitions": [row]})
    before = path.read_bytes()
    text = runtime_scan_text(path, tmp_path)
    assert _synthetic_archive_name("Ghana_MODIS_SP_2024") not in text
    assert "a" * 64 in text and _synthetic_archive_name("runtime_dependency") in text
    assert path.read_bytes() == before
    assert path in list(runtime_source_files(tmp_path))


def test_archive_intake_masks_only_valid_hash_bound_archive_path_slot(tmp_path):
    row = _export_identity()
    path = _write_authority(tmp_path, "archive_sp_intake.json", {
        "schema": "rp1_firms_archive_sp_intake_v1", "input_profile": "ghana_firms_archive_sp_v1",
        "families": [{"source": row["source"], "year": row["year"],
                      "archive_zip": {"path": row["annual_shapefile_zip"], "sha256": row["sha256"]},
                      "runtime_input": _synthetic_archive_name("attachment")}]})
    text = runtime_scan_text(path, tmp_path)
    assert _synthetic_archive_name("Ghana_MODIS_SP_2024") not in text and _synthetic_archive_name("attachment") in text
    value = json.loads(path.read_text())
    value["families"][0]["archive_zip"]["path"] = _synthetic_archive_name("unrelated")
    path.write_text(json.dumps(value))
    assert _synthetic_archive_name("unrelated") in runtime_scan_text(path, tmp_path)


def test_annual_provenance_masks_only_matching_export_lineage_slots(tmp_path):
    row = _export_identity()
    path = _write_authority(tmp_path, "modis/Ghana_MODIS_SP_2024_provenance.json", {
        "contract": "ghana-firms-gee-annual-v1", "export": row,
        "accepted_partition": {"source": row["source"], "year": row["year"],
            "shapefile_sha256": row["sha256"],
            "shapefile_path": _synthetic_archive_name("artifacts/MODIS/2024/12345678/Ghana_MODIS_SP_2024"),
            "runtime_input": _synthetic_archive_name("attachment")}})
    text = runtime_scan_text(path, tmp_path)
    assert _synthetic_archive_name("Ghana_MODIS_SP_2024") not in text and _synthetic_archive_name("attachment") in text
    payload = json.loads(path.read_text())
    payload["accepted_partition"]["shapefile_sha256"] = "b" * 64
    path.write_text(json.dumps(payload))
    assert _synthetic_archive_name("Ghana_MODIS_SP_2024") in runtime_scan_text(path, tmp_path)


def test_provenance_location_or_schema_cannot_hide_runtime_archive_dependencies(tmp_path):
    payload = {"contract": "ghana-firms-gee-annual-export-v1", "partitions": [_export_identity()]}
    wrong_path = _write_authority(tmp_path, "runtime_config.json", payload)
    assert _synthetic_archive_name("Ghana_MODIS_SP_2024") in runtime_scan_text(wrong_path, tmp_path)
    payload["contract"] = "unrecognised"
    wrong_schema = _write_authority(tmp_path, "annual-export.json", payload)
    assert _synthetic_archive_name("Ghana_MODIS_SP_2024") in runtime_scan_text(wrong_schema, tmp_path)
    payload["contract"] = "ghana-firms-gee-annual-export-v1"
    payload["partitions"][0]["sha256"] = "invalid"
    wrong_schema.write_text(json.dumps(payload))
    assert _synthetic_archive_name("Ghana_MODIS_SP_2024") in runtime_scan_text(wrong_schema, tmp_path)


def test_archive_tool_roles_are_exact_and_intake_has_no_fixed_archive_dependency():
    assert LOCAL_ARCHIVE_COMPONENT_CODE == {ARCHIVE_COMPONENT + name for name in (
        'src/ghana_fire_archive/api.py', 'src/ghana_fire_archive/cli.py',
        'src/ghana_fire_archive/core.py', 'src/ghana_fire_archive/exports.py',
        'tools/package_source.py', 'tools/package_annual.py')}
    assert LOCAL_ARCHIVE_PRODUCERS == {"tools/stage_gee_handoff.py", "tools/package_clean_source.py",
                                       "tools/firms_archive_workflow.py"} | LOCAL_ARCHIVE_COMPONENT_CODE
    assert LOCAL_ARCHIVE_COMPONENT_DOCUMENTATION == {
        ARCHIVE_COMPONENT + 'README.md', ARCHIVE_COMPONENT + 'GEE_UPLOAD.md'}
    assert LOCAL_ARCHIVE_INTAKE_TOOLS == {"tools/import_firms_archive_sp.py"}
    assert "src/read_input.py" not in LOCAL_ARCHIVE_IO_TOOLS
    assert ARCHIVE_COMPONENT + 'src/ghana_fire_archive/unreviewed.py' not in LOCAL_ARCHIVE_IO_TOOLS
    assert ARCHIVE_COMPONENT + 'configs/input.yaml' not in LOCAL_ARCHIVE_IO_TOOLS
    repository = Path(__file__).resolve().parents[3]
    source = (repository / "tools/import_firms_archive_sp.py").read_text(encoding="utf-8")
    assert archive_input_literals(source) == []


def test_local_archive_producer_code_has_only_declared_local_output_archive_literals():
    repository = Path(__file__).resolve().parents[3]
    outputs = {
        ARCHIVE_COMPONENT + 'src/ghana_fire_archive/cli.py': [_synthetic_archive_name('Ghana_Fire_Archive_Annual_Shapefiles')],
        ARCHIVE_COMPONENT + 'src/ghana_fire_archive/exports.py': [_synthetic_archive_name('collection')],
    }
    for name in LOCAL_ARCHIVE_COMPONENT_CODE | {'tools/firms_archive_workflow.py'}:
        assert archive_input_literals((repository / name).read_text(encoding='utf-8')) == outputs.get(name, [])


def test_reference_origin_metadata_masks_only_valid_hash_bound_origin_slots(tmp_path):
    name = _synthetic_archive_name('data')
    source = {'archive_name': name, 'archive_sha256': 'a' * 64,
              'archive_safety': {'archive_name': name, 'archive_sha256': 'a' * 64, 'safe': True},
              'input_archive': _synthetic_archive_name('runtime_input')}
    path = tmp_path / ARCHIVE_COMPONENT / 'data/reference/geography/geography-manifest.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'source': source}))
    before = path.read_bytes()
    text = runtime_scan_text(path, tmp_path)
    assert name not in text and _synthetic_archive_name('runtime_input') in text
    assert path.read_bytes() == before
    source['archive_safety']['archive_sha256'] = 'b' * 64
    path.write_text(json.dumps({'source': source}))
    assert name in runtime_scan_text(path, tmp_path)


def test_generated_presentation_roots_are_not_runtime_sources_and_policies_agree(tmp_path):
    generated = [root + "/RP1_PRESENTATION_FIGURE_MANIFEST.json" for root in GENERATED_PRESENTATION_ROOTS]
    governed = ["RP1_Project/rp1_analysis/docs/presentation_all/example.py",
                "RP1_Project/rp1_analysis/presentation_all_examples/source.py"]
    for relative in generated + governed:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture")
    actual = {path.relative_to(tmp_path).as_posix() for path in runtime_source_files(tmp_path)}
    assert actual == set(governed)
    assert all((tmp_path / path).is_file() for path in generated)
    repository = Path(__file__).resolve().parents[3]
    package = json.loads((repository / "configs/clean_source_package.json").read_text(encoding="utf-8"))
    import yaml
    qualification = yaml.safe_load((repository / "RP1_Project/rp1_analysis/config/qualification_contract.yml").read_text(encoding="utf-8"))
    assert GENERATED_PRESENTATION_ROOTS <= set(package["exclude_paths"])
    assert GENERATED_PRESENTATION_ROOTS <= set(qualification["generated_artifacts"]["relative_paths"])
