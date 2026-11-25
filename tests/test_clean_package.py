"""A source archive retains inputs and tests while excluding workflow products."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("clean_packager", ROOT / "tools/package_clean_source.py")
packager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packager)


class CleanPackage(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.source = self.home / "source"
        self.stage = self.home / "ghana-fire-dynamics-analysis"
        self.policy = packager.load_policy(ROOT)
        self.policy["include_roots"] = ["README.md", "configs", "docs", "geo_data_prep", "RP1_Project", "tests"]
        files = {
            "README.md": "Current project instructions\n",
            "configs/clean_source_package.json": json.dumps(self.policy),
            "geo_data_prep/data/raw/input.csv": "id,value\nA,1\n",
            "tests/fixtures/reference.json": '{"synthetic": true}',
            "RP1_Project/rp1_analysis/data/raw/panel.csv": "generated panel",
            "RP1_Project/rp1_analysis/out/result.csv": "generated result",
            "RP1_Project/rp1_analysis/presentation_all/RP1_PRESENTATION_FIGURE_MANIFEST.json": '{"generated":true}',
            "RP1_Project/rp1_analysis/presentation_all/F2.png": "generated PNG",
            "RP1_Project/rp1_analysis/presentation_one/F2.pdf": "generated PDF",
            "RP1_Project/rp1_analysis/presentation_rq3/F5.png": "generated PNG",
            "RP1_Project/rp1_analysis/custom_presentation/RP1_PRESENTATION_FIGURE_MANIFEST.json": '{"generated":true}',
            "RP1_Project/rp1_analysis/custom_presentation/F2.png": "generated PNG",
            "docs/example_run/EXECUTION_EVIDENCE_MANIFEST.json": '{"generated":true}',
            "docs/example_run/observed.csv": "generated run evidence",
            "configs/qualification/qualification_report.json": '{"generated":true}',
            "configs/qualification/runtime/results.csv": "generated qualification",
            "configs/Out/result.csv": "generated uppercase output",
            "configs/workflow_local.json": '{"archive":"local-path"}',
            "configs/.env": "FIRMS_MAP_KEY=synthetic",
            "configs/.env.local": "FIRMS_MAP_KEY=synthetic",
            "configs/firms_map_key.txt": "synthetic private value",
            "RP1_Project/rp1_analysis/docs/presentation_all/example.png": "governed documentation image",
            "RP1_Project/rp1_analysis/presentation_all_examples/README.md": "governed example documentation",
            "RP1_Project/rp1_mv_firms_panels/data/raw/boundaries/zones.shp": "staged geography",
            "RP1_Project/rp1_mv_firms_panels/data/metadata/unit_universe.csv": "generated universe",
            "RP1_Project/rp1_mv_firms_panels/data/raw/source_provenance/archive_sp_intake.json": '{"schema":"intake-fixture"}',
            "RP1_Project/rp1_mv_firms_panels/data/raw/modis/unexpected_original.csv": "raw source data",
            "RP1_Project/rp1_mv_firms_panels/data/raw/unknown/map_key.txt": "synthetic private value",
            "RP1_Project/rp1_mv_firms_panels/data/raw/viirs/.VIIRS_2012.dbf.unrelated": "temporary sidecar",
            "RP1_Project/configs/ba_source_lock_c1.json": "generated lock",
            "RP1_Project/configs/ba_source_lock_c3.json": "generated c3 lock",
            "RP1_Project/rp1_gee_ba_scripts/downloads/c1_release/export.csv": "GEE output",
            "RP1_Project/rp1_gee_ba_scripts/downloads/c3_release/export.csv": "c3 GEE output",
            "RP1_Project/rp1_gee_ba_scripts/downloads/c3_release/out/result.csv": "derived output",
            "RP1_Project/rp1_gee_ba_scripts/downloads/c3_release_extra/export.csv": "unrelated output",
            "RP1_Project/rp1_gee_ba_scripts/RP1_Project_MODIS_BA_c3_2001/export.csv": "direct c3 output",
            "RP1_Project/rp1_gee_ba_scripts/c3/build.py": "# pinned builder\n",
            "RP1_Project/rp1_gee_ba_scripts/c3/tests/fixtures/sample.csv": "unit_id,value\nA,0\n",
            "RP1_Project/rp1_gee_ba_scripts/c3/tests/fixtures/PROVENANCE.json": '{"bounded": true}',
            "RP1_Project/rp1_gee_ba_scripts/c3/tests/fixtures/asutifi_north_ba2012_202401.csv": "previous scientific output",
            "docs/C3_EXISTING_SCRIPT_INVENTORY.json": "generated inventory",
            "RP1_Project/rp1_gee_ba_scripts/c3/tests/reference/ee_core_previous.txt": "independent core",
            "RP1_Project/rp1_gee_ba_scripts/c3/tests/reference/HEADER_MAP.csv": "previous schema mapping",
            "RP1_Project/rp1_analysis/__pycache__/module.pyc": "cache",
            "RP1_Project/rp1_firms_archive/README.md": "Embedded Archive producer\n",
            "RP1_Project/rp1_firms_archive/tools/package_source.py": "SOURCE_FILES = ('README.md', 'tools/package_source.py', 'src/ghana_fire_archive/__init__.py', 'data/raw/README.md', 'data/metadata/README.md', 'data/reference/geography/geography-manifest.json')\n",
            "RP1_Project/rp1_firms_archive/src/ghana_fire_archive/__init__.py": "__version__='fixture'\n",
            "RP1_Project/rp1_firms_archive/data/raw/README.md": "Raw files are external runtime inputs\n",
            "RP1_Project/rp1_firms_archive/data/metadata/README.md": "Generated metadata is excluded\n",
            "RP1_Project/rp1_firms_archive/data/reference/geography/geography-manifest.json": '{"reference":true}',
            "RP1_Project/rp1_firms_archive/data/raw/source.csv": "runtime source",
            "RP1_Project/rp1_firms_archive/data/metadata/archive-manifest.json": "runtime receipt",
            "RP1_Project/rp1_firms_archive/private/map_key.txt": "synthetic secret",
            "RP1_Project/rp1_firms_archive/arbitrary-output.json": "unlisted runtime output",
            "RP1_Project/rp1_firms_archive/out/result.csv": "generated output",
        }
        for name, content in files.items():
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        notebook = {"nbformat": 4, "nbformat_minor": 5, "metadata": {}, "cells": [
            {"cell_type": "code", "source": ["value = 1\n"], "metadata": {"execution": {"time": "recorded"}},
             "outputs": [{"output_type": "stream", "text": ["result"]}], "execution_count": 1}]}
        (self.source / "RP1_Project/rp1_analysis/analysis.ipynb").write_text(json.dumps(notebook))

    def test_source_inputs_and_synthetic_fixtures_survive_without_products(self):
        result = packager.stage_source(self.source, self.stage)
        self.assertEqual(result["source_input_files"], 2)
        empty = self.stage / "RP1_Project/rp1_mv_firms_panels/data/raw"
        self.assertTrue(empty.is_dir())
        self.assertEqual(list(empty.iterdir()), [])
        self.assertTrue((self.source / "RP1_Project/rp1_mv_firms_panels/data/raw/source_provenance/archive_sp_intake.json").is_file())
        self.assertFalse((self.stage / "RP1_Project/rp1_mv_firms_panels/data/raw/viirs/.VIIRS_2012.dbf.unrelated").exists())
        original = "geo_data_prep/data/raw/input.csv"
        self.assertEqual((self.stage / original).read_bytes(), (self.source / original).read_bytes())
        self.assertTrue((self.stage / "tests/fixtures/reference.json").is_file())
        self.assertFalse((self.stage / "RP1_Project/rp1_analysis/data").exists())
        self.assertEqual((self.stage / "RP1_Project/rp1_gee_ba_scripts/downloads/c3_release/export.csv").read_bytes(),
                         (self.source / "RP1_Project/rp1_gee_ba_scripts/downloads/c3_release/export.csv").read_bytes())
        self.assertFalse((self.stage / "RP1_Project/rp1_gee_ba_scripts/downloads/c1_release").exists())
        self.assertFalse((self.stage / "RP1_Project/rp1_gee_ba_scripts/downloads/c3_release_extra").exists())
        self.assertFalse((self.stage / "RP1_Project/rp1_gee_ba_scripts/downloads/c3_release/out").exists())
        self.assertFalse((self.stage / "RP1_Project/configs/ba_source_lock_c1.json").exists())
        self.assertFalse((self.stage / "RP1_Project/configs/ba_source_lock_c3.json").exists())
        self.assertFalse((self.stage / "RP1_Project/rp1_gee_ba_scripts/RP1_Project_MODIS_BA_c3_2001").exists())
        self.assertFalse((self.stage / "docs/C3_EXISTING_SCRIPT_INVENTORY.json").exists())
        self.assertFalse((self.stage / 'RP1_Project/rp1_gee_ba_scripts/c3/tests/fixtures/PROVENANCE.json').exists())
        self.assertFalse((self.stage / 'RP1_Project/rp1_gee_ba_scripts/c3/tests/fixtures/asutifi_north_ba2012_202401.csv').exists())
        self.assertFalse((self.stage / 'RP1_Project/rp1_gee_ba_scripts/c3/tests/reference/ee_core_previous.txt').exists())
        self.assertFalse((self.stage / 'RP1_Project/rp1_gee_ba_scripts/c3/tests/reference/HEADER_MAP.csv').exists())
        for member in ('build.py', 'tests/fixtures/sample.csv'):
            self.assertTrue((self.stage / 'RP1_Project/rp1_gee_ba_scripts/c3' / member).is_file())
        notebook = json.loads((self.stage / "RP1_Project/rp1_analysis/analysis.ipynb").read_text())
        self.assertEqual(notebook["cells"][0]["outputs"], [])
        self.assertIsNone(notebook["cells"][0]["execution_count"])
        self.assertNotIn("execution", notebook["cells"][0]["metadata"])
        original = json.loads((self.source / "RP1_Project/rp1_analysis/analysis.ipynb").read_text())
        self.assertTrue(original["cells"][0]["outputs"])
        self.assertNotIn(b"\r\n", (self.stage / "RP1_Project/rp1_analysis/analysis.ipynb").read_bytes())
        self.assertNotIn(b"\r\n", (self.stage / packager.PACKAGE_MANIFEST).read_bytes())

    def test_archive_contains_exact_staged_files_and_refuses_replacement(self):
        packager.stage_source(self.source, self.stage)
        archive = self.home / "clean.zip"
        result = packager.archive_source(self.stage, archive)
        self.assertEqual(result["status"], "PASS")
        with zipfile.ZipFile(archive) as stream:
            self.assertIsNone(stream.testzip())
            self.assertTrue(all(name.startswith(self.stage.name + "/") for name in stream.namelist()))
            self.assertFalse(any("/out/" in name or "/downloads/c1_release/" in name for name in stream.namelist()))
            self.assertTrue(any("/downloads/c3_release/export.csv" in name for name in stream.namelist()))
            empty = self.stage.name + "/RP1_Project/rp1_mv_firms_panels/data/raw/"
            self.assertTrue(stream.getinfo(empty).is_dir())
            self.assertEqual(stream.read(empty), b"")
            self.assertFalse(any(name != empty and name.startswith(empty) for name in stream.namelist()))
            extracted = self.home / "extracted"
            stream.extractall(extracted)
            self.assertEqual(list((extracted / empty).iterdir()), [])
        with self.assertRaises(FileExistsError):
            packager.archive_source(self.stage, archive)

    def test_exact_generated_presentation_roots_are_excluded_and_preserved(self):
        packager.stage_source(self.source, self.stage)
        for name in ("presentation_all", "presentation_one", "presentation_rq3"):
            relative = "RP1_Project/rp1_analysis/" + name
            self.assertTrue((self.source / relative).is_dir())
            self.assertFalse((self.stage / relative).exists())
        self.assertTrue((self.stage / "RP1_Project/rp1_analysis/docs/presentation_all/example.png").is_file())
        self.assertTrue((self.stage / "RP1_Project/rp1_analysis/presentation_all_examples/README.md").is_file())
        (self.stage / "RP1_Project/rp1_analysis/presentation_one").mkdir()
        with self.assertRaisesRegex(ValueError, "Generated or linked"):
            packager.audit_tree(self.stage)

    def test_named_run_exports_and_local_credentials_are_excluded(self):
        packager.stage_source(self.source, self.stage)
        for member in ("RP1_Project/rp1_analysis/custom_presentation", "docs/example_run",
                       "configs/qualification", "configs/Out", "configs/workflow_local.json",
                       "configs/.env", "configs/.env.local", "configs/firms_map_key.txt"):
            self.assertTrue((self.source / member).exists())
            self.assertFalse((self.stage / member).exists())

    def test_rehashed_inventory_cannot_admit_an_unlisted_root(self):
        packager.stage_source(self.source, self.stage)
        extra = self.stage / "unexpected"
        extra.write_text("unexpected file")
        with (self.stage / packager.PACKAGE_MANIFEST).open("a", encoding="utf-8") as stream:
            stream.write(f"{packager.sha(extra)}  {extra.name}\n")
        with self.assertRaisesRegex(ValueError, "outside declared source roots"):
            packager.audit_tree(self.stage)

    def test_rehashed_input_inventory_requires_all_retained_inputs(self):
        packager.stage_source(self.source, self.stage)
        path = self.stage / packager.INPUT_MANIFEST
        input_manifest = json.loads(path.read_text(encoding="utf-8"))
        old_digest = packager.sha(path)
        input_manifest["files"].pop("RP1_Project/rp1_gee_ba_scripts/downloads/c3_release/export.csv")
        path.write_text(json.dumps(input_manifest), encoding="utf-8")
        index = self.stage / packager.PACKAGE_MANIFEST
        index.write_text(index.read_text(encoding="utf-8").replace(old_digest, packager.sha(path)), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "does not fully cover"):
            packager.audit_tree(self.stage)

    def test_junction_is_rejected_before_source_staging(self):
        link = self.source / "docs/linked"
        link.mkdir()
        original = Path.is_junction
        with patch.object(Path, "is_junction", lambda candidate: candidate == link or original(candidate)):
            with self.assertRaisesRegex(ValueError, "junctions are not packaged"):
                packager.stage_source(self.source, self.stage)
        self.assertFalse(self.stage.exists())

    def test_modified_staging_and_generated_contamination_are_rejected(self):
        packager.stage_source(self.source, self.stage)
        (self.stage / "README.md").write_text("changed")
        with self.assertRaisesRegex(ValueError, "differs from its inventory"):
            packager.audit_tree(self.stage)
        (self.stage / "README.md").write_bytes((self.source / "README.md").read_bytes())
        (self.stage / "out").mkdir()
        with self.assertRaisesRegex(ValueError, "Generated or linked"):
            packager.audit_tree(self.stage)

    def test_staging_cannot_replace_operational_source(self):
        with self.assertRaisesRegex(ValueError, "operational source"):
            packager.stage_source(self.source, self.source)
        with self.assertRaisesRegex(ValueError, "excluded output directory"):
            packager.stage_source(self.source, self.source / "release")

    def test_embedded_archive_uses_only_its_literal_positive_source_list(self):
        packager.stage_source(self.source, self.stage)
        project = "RP1_Project/rp1_firms_archive/"
        retained = ("README.md", "src/ghana_fire_archive/__init__.py", "tools/package_source.py",
                    "data/raw/README.md", "data/metadata/README.md", "data/reference/geography/geography-manifest.json")
        excluded = ("data/raw/source.csv", "data/metadata/archive-manifest.json", "private/map_key.txt",
                    "arbitrary-output.json", "out/result.csv")
        for member in retained:
            self.assertEqual((self.stage / (project + member)).read_bytes(),
                             (self.source / (project + member)).read_bytes())
        for member in excluded:
            self.assertTrue((self.source / (project + member)).is_file())
            self.assertFalse((self.stage / (project + member)).exists())
        (self.stage / (project + "arbitrary-output.json")).write_text("unlisted")
        with self.assertRaisesRegex(ValueError, "Generated or linked"):
            packager.audit_tree(self.stage)

    def test_embedded_allowlist_is_parsed_without_executing_code(self):
        script = self.source / "RP1_Project/rp1_firms_archive/tools/package_source.py"
        marker = self.home / "should-not-exist"
        script.write_text(f"SOURCE_FILES = (__import__('pathlib').Path({str(marker)!r}).touch(),)\n")
        with self.assertRaisesRegex(ValueError, "literal data"):
            packager.stage_source(self.source, self.stage)
        self.assertFalse(marker.exists())
        self.assertFalse(self.stage.exists())

    def test_even_allowlisted_private_credentials_cannot_be_packaged(self):
        script = self.source / "RP1_Project/rp1_firms_archive/tools/package_source.py"
        script.write_text("SOURCE_FILES = ('tools/package_source.py', 'private/map_key.txt')\n")
        with self.assertRaisesRegex(ValueError, "Runtime data or private"):
            packager.stage_source(self.source, self.stage)
        self.assertFalse(self.stage.exists())

    def test_empty_consumer_slot_does_not_copy_any_existing_data_or_change_sources(self):
        consumer = "RP1_Project/rp1_mv_firms_panels/data/raw"
        originals = {p.relative_to(self.source).as_posix(): p.read_bytes()
                     for p in (self.source / consumer).rglob("*") if p.is_file()}
        result = packager.stage_source(self.source, self.stage)
        self.assertEqual(result["empty_directories"], [consumer])
        self.assertEqual(list((self.stage / consumer).iterdir()), [])
        for name, data in originals.items():
            self.assertEqual((self.source / name).read_bytes(), data)
        inputs = json.loads((self.stage / packager.INPUT_MANIFEST).read_text())["files"]
        self.assertFalse(any(name.startswith(consumer + "/") for name in inputs))

    def test_nonempty_or_missing_consumer_slot_cannot_pass_audit_or_be_archived(self):
        packager.stage_source(self.source, self.stage)
        empty = self.stage / "RP1_Project/rp1_mv_firms_panels/data/raw"
        for name, directory in ((".gitkeep", False), ("modis", True)):
            candidate = empty / name
            candidate.mkdir() if directory else candidate.write_text("contamination")
            with self.assertRaisesRegex(ValueError, "not empty"):
                packager.audit_tree(self.stage)
            with self.assertRaisesRegex(ValueError, "not empty"):
                packager.archive_source(self.stage, self.home / "must-not-exist.zip")
            self.assertFalse((self.home / "must-not-exist.zip").exists())
            candidate.rmdir() if directory else candidate.unlink()
        empty.rmdir()
        with self.assertRaisesRegex(ValueError, "missing"):
            packager.audit_tree(self.stage)

    def test_empty_slot_policy_rejects_unsafe_or_unexcluded_paths_before_staging(self):
        for names in (["../escape"], ["RP1_Project/unexcluded"],
                      ["RP1_Project/rp1_mv_firms_panels/data/raw"] * 2,
                      ["RP1_Project/rp1_mv_firms_panels/data/raw", "RP1_Project/rp1_mv_firms_panels/data/raw/child"]):
            with self.subTest(names=names):
                policy = dict(self.policy, empty_directories=names)
                with self.assertRaises(ValueError):
                    packager.stage_source(self.source, self.stage, policy=policy)
                self.assertFalse(self.stage.exists())


if __name__ == "__main__":
    unittest.main()
