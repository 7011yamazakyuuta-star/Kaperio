import unittest

from scripts.audit_dependencies import runtime_inventory, validate_report


class DependencyAuditTests(unittest.TestCase):
    def test_installed_inventory_covers_declared_dependencies(self):
        inventory = runtime_inventory()
        self.assertIn('cryptography', inventory)
        self.assertIn('psutil', inventory)
        self.assertNotIn('pip-audit', inventory)

    def test_report_requires_complete_matching_clean_results(self):
        inventory = {'example': '1.0', 'second': '2.0'}
        rows = [{'name': name, 'version': version, 'vulns': []} for name, version in inventory.items()]
        validate_report({'dependencies': rows}, inventory)
        bad = [[], rows[:1], [rows[0], rows[0]],
               [dict(rows[0], version='0.9'), rows[1]],
               [dict(rows[0], skip_reason='unavailable'), rows[1]],
               [dict(rows[0], vulns=[{'id': 'synthetic'}]), rows[1]],
               [dict(rows[0], vulns=None), rows[1]]]
        for result in bad:
            with self.subTest(result=result), self.assertRaises(ValueError):
                validate_report({'dependencies': result}, inventory)
