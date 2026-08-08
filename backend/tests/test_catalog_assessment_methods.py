import unittest

from app.services.controls.catalog import load_baseline, load_catalog


class CatalogAssessmentMethodTests(unittest.TestCase):
    def test_ac_1_preserves_nist_methods_and_objects(self):
        control = load_catalog()["ac-1"]
        methods = {item["method"]: item for item in control.assessment_methods}

        self.assertIn("EXAMINE", methods)
        self.assertIn("INTERVIEW", methods)
        self.assertIn("Access control policy and procedures", methods["EXAMINE"]["objects"])
        self.assertTrue(any("personnel" in value.lower() for value in methods["INTERVIEW"]["objects"]))

    def test_catalog_exposes_all_nist_assessment_method_types(self):
        method_types = {
            item["method"]
            for control in load_catalog().values()
            for item in control.assessment_methods
        }
        self.assertEqual(method_types, {"EXAMINE", "INTERVIEW", "TEST"})

    def test_organization_defined_parameter_ids_are_preserved(self):
        control = load_catalog()["ac-1"]
        self.assertIn("ac-01_odp.01", control.organization_defined_parameters)

    def test_control_and_enhancement_display_ids_are_unique_in_every_baseline(self):
        for baseline in ("low", "moderate", "high"):
            display_ids = [control.display_id for control in load_baseline(baseline)]
            self.assertEqual(len(display_ids), len(set(display_ids)), baseline)

    def test_moderate_baseline_has_expected_totality(self):
        controls = load_baseline("moderate")
        self.assertEqual(len(controls), 324)
        self.assertEqual(sum(len(control.assessment_objectives) for control in controls), 1467)
