import os
import unittest
import yaml


class TestWorkflowConfig(unittest.TestCase):
    def test_workflow_syntax_and_triggers(self):
        workflow_path = os.path.join(".github", "workflows", "scan.yml")
        self.assertTrue(os.path.exists(workflow_path), f"{workflow_path} must exist")

        with open(workflow_path, "r", encoding="utf-8") as f:
            workflow = yaml.safe_load(f)

        # YAML parses on triggers
        triggers = workflow.get("on") or workflow.get(True)  # PyYAML might parse 'on' as boolean True
        self.assertIsNotNone(triggers, "Workflow must define 'on' triggers")

        # Verify schedule exists
        self.assertIn("schedule", triggers)

        # Verify workflow_dispatch exists
        self.assertIn("workflow_dispatch", triggers)

        # Verify push trigger on main with config.yaml path filter
        self.assertIn("push", triggers)
        push_cfg = triggers["push"]
        self.assertIn("main", push_cfg.get("branches", []))
        self.assertIn("config.yaml", push_cfg.get("paths", []))

    def test_config_yaml_structure(self):
        config_path = "config.yaml"
        self.assertTrue(os.path.exists(config_path), f"{config_path} must exist")

        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        self.assertIsInstance(cfg, dict)
        self.assertIn("repos", cfg)
        self.assertIsInstance(cfg["repos"], list)
        self.assertGreater(len(cfg["repos"]), 0)


if __name__ == "__main__":
    unittest.main()
