"""Archive admission and promotion preserve source identity and the old baseline."""
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("archive_intake", ROOT / "tools/import_firms_archive_sp.py")
intake = importlib.util.module_from_spec(spec)
spec.loader.exec_module(intake)


def make_dbf(path, row):
    fields = list(row)
    sizes = [max(len(row[key]), 12) for key in fields]
    header_size, record_size = 33 + 32 * len(fields), 1 + sum(sizes)
    header = bytearray(32)
    header[0] = 3
    struct.pack_into("<IHH", header, 4, 1, header_size, record_size)
    output = bytearray(header)
    for field, size in zip(fields, sizes):
        descriptor = bytearray(32)
        descriptor[:len(field)] = field.encode("ascii")
        descriptor[11], descriptor[16] = ord("C"), size
        output.extend(descriptor)
    output.extend(b"\r ")
    for key, size in zip(fields, sizes):
        output.extend(row[key].encode("utf-8").ljust(size, b" "))
    output.extend(b"\x1a")
    path.write_bytes(output)


class ArchiveIntake(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.curated, self.annual = self.home / "curated", self.home / "annual"
        self.staged, self.active, self.backup = self.home / "staged", self.home / "active", self.home / "backup"
        partitions = []
        for sensor, year in (("modis", 2001), ("viirs", 2012)):
            source = intake.SENSORS[sensor]
            folder = self.curated / source["folder"]
            folder.mkdir(parents=True)
            stem = source["prefix"] + str(year)
            for ext in intake.EXTENSIONS:
                (folder / (stem + ext)).write_bytes((sensor + ext).encode())
            version = "61.03" if sensor == "modis" else "2"
            make_dbf(folder / (stem + ".dbf"), {
                "source": source["source"], "processing": "SP", "platform": "Terra" if sensor == "modis" else "Suomi-NPP",
                "instrument": source["instrument"], "version": version})
            zip_relative = source["archive_folder"] + "/" + stem + ".zip"
            zip_path = self.annual / zip_relative
            zip_path.parent.mkdir(parents=True)
            with zipfile.ZipFile(zip_path, "w") as stream:
                for ext in intake.EXTENSIONS:
                    stream.write(folder / (stem + ext), stem + ext)
            row = {"annual_shapefile_zip": zip_relative, "source": source["source"], "year": year,
                   "records": 1, "gee_upload_ready": True, "sha256": intake.sha(zip_path)}
            partitions.append(row)
            metadata = self.annual / "metadata" / source["archive_folder"]
            metadata.mkdir(parents=True)
            (metadata / (stem + "_provenance.json")).write_text(json.dumps({
                "contract": "ghana-firms-gee-annual-v1", "export": row,
                "accepted_partition": {"source": source["source"], "year": year, "processing_status": "SP",
                                       "record_count": 1, "shapefile_sha256": row["sha256"], "source_versions": [version]}}))
            (metadata / (stem + "_fields.json")).write_text(json.dumps({key: key for key in
                ("obs_id", "conf_raw", "fire_type", "source", "processing", "time_utc")}))
        (self.annual / "annual-export.json").write_text(json.dumps({
            "contract": "ghana-firms-gee-annual-export-v1", "partitions": partitions}))

    def test_stage_binds_both_products_and_local_companions(self):
        result = intake.stage(self.curated, self.annual, self.staged)
        self.assertEqual(result["families"], 2)
        self.assertEqual(result["components"], 10)
        manifest = json.loads((self.staged / intake.AUTHORITY).read_text())
        self.assertEqual(manifest["schema"], intake.SCHEMA)
        for family in manifest["families"]:
            spec = intake.SENSORS[family["sensor"]]
            for component in family["components"]:
                self.assertEqual((self.staged / component["path"]).read_bytes(),
                                 (self.curated / spec["folder"] / Path(component["path"]).name).read_bytes())
            self.assertTrue((self.staged / family["provenance"]["path"]).is_file())
            self.assertTrue((self.staged / family["field_dictionary"]["path"]).is_file())

    def test_changed_curated_component_fails_before_creating_stage(self):
        next((self.curated / "MODIS_SP").glob("*.shp")).write_bytes(b"altered")
        with self.assertRaisesRegex(ValueError, "differs from Archive"):
            intake.stage(self.curated, self.annual, self.staged)
        self.assertFalse(self.staged.exists())

    def test_extra_sidecar_and_missing_component_are_rejected(self):
        extra = self.curated / "VIIRS_SP/.VIIRS.dbf.temporary"
        extra.write_text("unrelated")
        with self.assertRaisesRegex(ValueError, "Unexpected curated"):
            intake.inspect_curated(self.curated, self.annual)
        extra.unlink()
        next((self.curated / "VIIRS_SP").glob("*.cpg")).unlink()
        with self.assertRaisesRegex(ValueError, "Missing or linked"):
            intake.inspect_curated(self.curated, self.annual)

    def test_archive_zip_or_provenance_tampering_is_rejected(self):
        provenance = next((self.annual / "metadata/MODIS").glob("*_provenance.json"))
        content = json.loads(provenance.read_text())
        content["accepted_partition"]["processing_status"] = "NRT"
        provenance.write_text(json.dumps(content))
        with self.assertRaisesRegex(ValueError, "provenance does not bind"):
            intake.inspect_curated(self.curated, self.annual)
        next((self.annual / "MODIS").glob("*.zip")).write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "ZIP identity differs"):
            intake.inspect_curated(self.curated, self.annual)

    def test_staged_data_and_companion_tampering_are_rejected(self):
        intake.stage(self.curated, self.annual, self.staged)
        provenance = next((self.staged / "data/raw/source_provenance/modis").glob("*_provenance.json"))
        provenance.write_text("changed")
        with self.assertRaisesRegex(ValueError, "identity differs"):
            intake.verify_bundle(self.staged)

    def test_staging_and_backup_never_overwrite_existing_paths(self):
        intake.stage(self.curated, self.annual, self.staged)
        with self.assertRaisesRegex(ValueError, "already exists"):
            intake.stage(self.curated, self.annual, self.staged)
        self.active.mkdir()
        self.backup.mkdir()
        with self.assertRaisesRegex(ValueError, "already exists"):
            intake.activate(self.staged, self.active, self.backup)

    def seed_old(self):
        for sensor in ("modis", "viirs"):
            path = self.active / "data/raw" / sensor / "old.shp"
            path.parent.mkdir(parents=True)
            path.write_text("original " + sensor)
        return intake.tree_inventory(self.active)

    def test_activation_preserves_old_inputs_and_new_manifest(self):
        intake.stage(self.curated, self.annual, self.staged)
        original = self.seed_old()
        result = intake.activate(self.staged, self.active, self.backup)
        self.assertEqual(result["status"], "PASS")
        for relative, record in original.items():
            self.assertEqual(intake.identity(self.backup / relative, relative), record)
        self.assertTrue((self.backup / "activation_complete.json").is_file())
        self.assertEqual(intake.verify_bundle(self.active)["families"], 2)

    def test_failure_after_promotion_restores_old_directories_and_stage(self):
        intake.stage(self.curated, self.annual, self.staged)
        original = self.seed_old()
        verify = intake.verify_bundle
        def fail_active(path):
            if path == self.active:
                raise ValueError("simulated post-promotion failure")
            return verify(path)
        with mock.patch.object(intake, "verify_bundle", side_effect=fail_active):
            with self.assertRaisesRegex(ValueError, "simulated"):
                intake.activate(self.staged, self.active, self.backup)
        self.assertEqual(intake.tree_inventory(self.active), original)
        self.assertEqual(intake.verify_bundle(self.staged)["families"], 2)
        self.assertTrue((self.backup / "activation_failed.json").is_file())

    def test_path_traversal_and_sensor_contamination_are_rejected(self):
        intake.stage(self.curated, self.annual, self.staged)
        manifest_path = self.staged / intake.AUTHORITY
        manifest = json.loads(manifest_path.read_text())
        manifest["families"][0]["components"][0]["path"] = "../outside.shp"
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "Incomplete admitted"):
            intake.verify_bundle(self.staged)


if __name__ == "__main__":
    unittest.main()
