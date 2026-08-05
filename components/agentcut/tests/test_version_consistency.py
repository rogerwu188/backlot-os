import ast
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class VersionConsistencyTest(unittest.TestCase):
    def test_packaging_and_runtime_versions_match(self):
        pyproject_text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        project_match = re.search(r'^version = "([^"]+)"$', pyproject_text, re.MULTILINE)
        self.assertIsNotNone(project_match)
        pyproject_version = project_match.group(1)

        setup_text = (ROOT / "setup.py").read_text(encoding="utf-8")
        setup_match = re.search(r'version="([^"]+)"', setup_text)
        self.assertIsNotNone(setup_match)

        init_tree = ast.parse(
            (ROOT / "agentcut" / "__init__.py").read_text(encoding="utf-8")
        )
        runtime_version = None
        for node in init_tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets):
                runtime_version = ast.literal_eval(node.value)
                break

        self.assertEqual(runtime_version, pyproject_version)
        self.assertEqual(setup_match.group(1), pyproject_version)


if __name__ == "__main__":
    unittest.main()
