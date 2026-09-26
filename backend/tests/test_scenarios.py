"""D1 contract: one formula, honest missingness, independent pinned CSV."""
import asyncio
import csv
import io
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from types import MappingProxyType, SimpleNamespace
from pydantic import ValidationError

from test_handoff import make_archive, day_query
from backend.handoff.install import install
from backend.handoff.store import load_snapshot, Cell
from backend.handoff.api import HandoffError, calculate
from backend.handoff.features import SCENARIO, YEAR, ScenarioCapabilities, YearCapabilities
from backend.handoff.scenarios import Coefficients, ScenarioQuery, ScenarioExport, calculate_scenario, export


class ScenarioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        install(make_archive(root, missing=True), root / 'release')
        snapshot = load_snapshot(root / 'release')
        cells = dict(snapshot.cells)
        key = next(k for k in cells if k[0] == '1')
        cells[key] = Cell(100, 90, 80, 120, 0, 'ok')
        self.snapshot = replace(snapshot, cells=MappingProxyType(cells))

    def body(self, **kwargs):
        return ScenarioQuery(**day_query(**kwargs).model_dump(), coefficients=Coefficients(weather=1.1, event=1.2))

    def test_formula_reset_bounds_null_baseline_and_base_unchanged(self):
        before = calculate(self.snapshot, day_query(), 'x')
        result = calculate_scenario(self.snapshot, self.body(), 'x')
        self.assertAlmostEqual(result.rows[0].value, 132)
        self.assertAlmostEqual(result.rows[0].delta, 32)
        self.assertEqual(result.base, before)
        self.assertIsNone(result.rows[12].value)
        self.assertIsNone(result.rows[12].delta)
        self.assertEqual(result.base.coverage, 23/24)
        self.assertTrue(all(r.lower_90 is None and r.upper_90 is None for r in result.rows))
        reset = calculate_scenario(self.snapshot, self.body().model_copy(update={'coefficients': Coefficients()}), 'x')
        self.assertEqual(reset.rows[0].value, 100)
        self.assertEqual(reset.total, before.total)
        baseline = calculate_scenario(self.snapshot, self.body(route_ids=['5']), 'x')
        self.assertEqual(baseline.total, 0)
        self.assertTrue(all(r.status == 'cold_start_zero_baseline' for r in baseline.rows))
        missing = calculate_scenario(self.snapshot, self.body(start='2025-11-02T00:00:00+03:00', end='2025-11-03T00:00:00+03:00'), 'x')
        self.assertIsNone(missing.total)
        self.assertIsNone(missing.delta_total)
        daily = calculate_scenario(self.snapshot, self.body(resolution='day'), 'x')
        self.assertEqual(daily.rows[0].status, 'partial')
        self.assertEqual(daily.rows[0].coverage, 23/24)

    def test_four_factors_and_legacy_identity(self):
        import hashlib
        import json
        body = self.body()
        original = calculate_scenario(self.snapshot, body, 'x')
        key = {"calculation_version": "manual-multiply-v1", "base_result_id": original.base.result_id,
               "coefficients": {"weather": 1.1, "event": 1.2}}
        self.assertEqual(original.result_id, hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest())
        for name in ("closures", "changes"):
            updated = body.model_copy(update={"coefficients": Coefficients(weather=1.1, event=1.2, **{name: 0.5})})
            result = calculate_scenario(self.snapshot, updated, 'x')
            self.assertAlmostEqual(result.rows[0].value, 66)
            self.assertNotEqual(result.result_id, original.result_id)
            self.assertEqual(result.base, original.base)
            self.assertIsNone(result.rows[12].value)
            with self.assertRaises(ValidationError):
                Coefficients(**{name: 1.11})
        combined = calculate_scenario(self.snapshot, body.model_copy(update={
            "coefficients": Coefficients(weather=1.1, event=1.2, closures=0.5, changes=1.5)}), 'x')
        self.assertAlmostEqual(combined.rows[0].value, 99)

    def test_invalid_coefficients(self):
        for value in [float('nan'), float('inf'), -1, 0, 0.49, 1.51, 1.11, True, '1.1']:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                Coefficients(weather=value)

    def test_identity_and_csv(self):
        result = calculate_scenario(self.snapshot, self.body(), 'x')
        reset = calculate_scenario(self.snapshot, self.body().model_copy(update={'coefficients': Coefficients()}), 'x')
        self.assertNotEqual(result.result_id, reset.result_id)
        daily = calculate_scenario(self.snapshot, self.body(resolution='day'), 'x')
        self.assertNotEqual(result.result_id, daily.result_id)
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(handoff_snapshot=self.snapshot)), state=SimpleNamespace(request_id='x'))
        body = ScenarioExport(**{**self.body().model_dump(), 'forecast_run_id': self.snapshot.run_id, 'expected_result_id': result.result_id})
        async def read():
            return ''.join([chunk async for chunk in export(body, request).body_iterator])
        rows = list(csv.DictReader(io.StringIO(asyncio.run(read()).lstrip('\ufeff'))))
        self.assertAlmostEqual(float(rows[0]['value']), 132)
        self.assertEqual(float(rows[0]['base_value']), 100)
        self.assertEqual(rows[12]['value'], '')
        self.assertEqual(rows[0]['base_result_id'], result.base.result_id)
        with self.assertRaises(HandoffError) as caught:
            export(body.model_copy(update={'expected_result_id': reset.result_id}), request)
        self.assertEqual(caught.exception.status, 409)

    def test_year_is_qualitative(self):
        self.assertFalse(YEAR['numeric_supported'])
        self.assertIsNone(YEAR['value'])
        self.assertEqual([s['name'] for s in YEAR['scenarios']], ['recent_level', 'lower_service', 'higher_demand'])

    def test_capabilities_and_openapi_include_the_ui_contract(self):
        from backend.main import app
        from backend.handoff.api import HandoffCapabilities, capabilities
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(handoff_snapshot=self.snapshot)), state=SimpleNamespace(request_id='x'))
        result = HandoffCapabilities.model_validate(capabilities(request))
        self.assertTrue(result.scenario_supported)
        self.assertEqual(result.scenario, ScenarioCapabilities.model_validate(SCENARIO))
        self.assertEqual(result.year, YearCapabilities.model_validate(YEAR))
        schema = app.openapi()
        for path in ['/query', '/export']:
            responses = schema['paths']['/api/v2/scenarios' + path]['post']['responses']
            for status in ['404', '410', '413', '422', '503']:
                self.assertIn(status, responses)
        self.assertIn('409', schema['paths']['/api/v2/scenarios/export']['post']['responses'])
