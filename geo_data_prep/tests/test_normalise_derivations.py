from __future__ import annotations

from geo_data_prep.normalise.ids import derive_zone_code, dist_id_from_label, zone_id_from_label
from geo_data_prep.normalise.text import to_lower_name, to_upper_canon


def test_zone_label_derivations_example() -> None:
    raw = "Coastal savanna"
    assert to_lower_name(raw) == "coastal savanna"
    assert to_upper_canon(raw) == "COASTAL SAVANNA"
    assert zone_id_from_label(raw) == "coastal_savanna"
    assert derive_zone_code(raw) == "CS"


def test_district_label_derivations_example() -> None:
    raw = "Awutu Senya"
    assert to_lower_name(raw) == "awutu senya"
    assert to_upper_canon(raw) == "AWUTU SENYA"
    assert dist_id_from_label(raw) == "Awutu_Senya"


def test_punctuation_preserved_in_canon_removed_in_ids() -> None:
    raw_zone = r"  Coastal\   savanna!  "
    # Canon preserves punctuation/backslash, but whitespace is normalised.
    assert to_upper_canon(raw_zone) == r"COASTAL\ SAVANNA!"
    assert zone_id_from_label(raw_zone) == "coastal_savanna"

    raw_dist = r"Awutu\  Senya!"
    assert to_upper_canon(raw_dist) == r"AWUTU\ SENYA!"
    assert dist_id_from_label(raw_dist) == "Awutu_Senya"


def test_zone_code_collision_policy_suffixes_deterministically() -> None:
    raw = "Coastal savanna"
    assert derive_zone_code(raw, used_codes={"CS"}) == "CS2"
