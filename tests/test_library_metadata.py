import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools.library_metadata import business_fields, digest, enrich_projection


class LibraryMetadataTests(unittest.TestCase):
    def test_numeric_json_encodings_do_not_split_content(self):
        self.assertEqual(digest({"bpm": 190, "notes": [{"time": 0}]}), digest({"bpm": 190.0, "notes": [{"time": 0.0}]}))
    def test_translation_and_release_do_not_split_a_shared_skill(self):
        original = {"id": "skill-1", "name": "名称", "sourceReleaseIds": ["global-one"],
                    "levels": [{"level": 1, "rawValue": 100}], "relatedCardIds": ["card-1"]}
        other = {**original, "name": "名前", "sourceReleaseIds": ["jp-two"], "relatedCardIds": ["card-2"]}
        self.assertEqual(digest(business_fields(original)), digest(business_fields(other)))
        other["levels"] = [{"level": 1, "rawValue": 200}]
        self.assertNotEqual(digest(business_fields(original)), digest(business_fields(other)))

    def test_chart_identity_tracks_source_notes_not_derived_analysis(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            (data / "music-charts").mkdir()
            path = data / "music-charts/chart.json"
            chart = {"id": "chart", "trackId": "song", "difficulty": "expert", "notes": [{"time": 1}],
                     "meta": {"runtimeAlgorithmVersion": "one"}, "comboEvents": [1], "statistics": {"count": 1}}
            catalog = {"musicCharts": [{"id": "chart", "trackId": "song", "difficulty": "expert"}]}
            def identity(value):
                path.write_text(json.dumps(value))
                return enrich_projection("catalog.json", catalog, data, data)["musicCharts"][0]["contentIdentity"]
            first = identity(chart)
            other = copy.deepcopy(chart)
            other.update(meta={"runtimeAlgorithmVersion": "two"}, comboEvents=[1, 2])
            self.assertEqual(first, identity(other))
            other["notes"][0]["time"] = 2
            self.assertNotEqual(first, identity(other))
