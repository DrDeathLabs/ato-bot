import os
import unittest

os.environ.setdefault("SECRET_KEY", "test-secret-key-with-at-least-32-characters")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

from app.core.config import Settings
from app.core.features import feature_enabled, feature_registry


class FeatureRegistryTests(unittest.TestCase):
    def _settings(self, **overrides):
        values = {
            "secret_key": "test-secret-key-with-at-least-32-characters",
            "database_url": "postgresql+asyncpg://test:test@localhost/test",
            **overrides,
        }
        return Settings(**values)

    def test_experimental_features_are_disabled_by_default(self):
        settings = self._settings()
        self.assertFalse(feature_enabled(settings, "cato_dashboard"))
        self.assertFalse(feature_enabled(settings, "external_integrations"))
        self.assertFalse(feature_enabled(settings, "continuous_telemetry"))

    def test_experimental_setting_enables_the_related_runtime_slice(self):
        settings = self._settings(enable_experimental_cato=True)
        self.assertTrue(feature_enabled(settings, "cato_dashboard"))
        self.assertTrue(feature_enabled(settings, "external_integrations"))
        self.assertTrue(feature_enabled(settings, "continuous_telemetry"))

    def test_registry_uses_only_documented_maturity_states(self):
        statuses = {item["status"] for item in feature_registry(self._settings())}
        self.assertEqual(statuses, {"supported", "beta", "experimental", "deprecated", "unreachable"})
