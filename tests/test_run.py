import os
import unittest

from run import load_dotenv, bootstrap_config


class TestRunner(unittest.TestCase):
    def setUp(self):
        self.test_env = "test.env"
        self.test_cfg = "test_config.yaml"
        self.test_example = "test_example.yaml"
        self._cleanup()

    def tearDown(self):
        self._cleanup()

    def _cleanup(self):
        for f in (self.test_env, self.test_cfg, self.test_example):
            if os.path.exists(f):
                os.remove(f)

    def test_load_dotenv_parses_variables(self):
        with open(self.test_env, "w", encoding="utf-8") as f:
            f.write("# comment\n")
            f.write("TEST_VAR_A=hello\n")
            f.write("TEST_VAR_B='world'\n")
            f.write('TEST_VAR_C="quoted"\n')

        loaded = load_dotenv(self.test_env)
        self.assertEqual(loaded.get("TEST_VAR_A"), "hello")
        self.assertEqual(loaded.get("TEST_VAR_B"), "world")
        self.assertEqual(loaded.get("TEST_VAR_C"), "quoted")

    def test_bootstrap_config_creates_copy(self):
        with open(self.test_example, "w", encoding="utf-8") as f:
            f.write("repos: []\n")

        created = bootstrap_config(self.test_cfg, self.test_example)
        self.assertTrue(created)
        self.assertTrue(os.path.exists(self.test_cfg))


if __name__ == "__main__":
    unittest.main()
