import tempfile
import unittest
from pathlib import Path

from locate import canonical_hqh539_path, downloads_hqh539_path, sibling_module

WRAPPER_TEMPLATE = '''"""wrapper"""
import importlib.util
from pathlib import Path

def _canonical_hqh539_path(anchor: Path) -> Path:
    anchor = anchor.resolve()
    for parent in [anchor, *anchor.parents]:
        for candidate in (
            parent / "539_Engine" / "hqh539.py",
            parent / "Desktop" / "539_Engine" / "hqh539.py",
        ):
            if candidate.is_file():
                return candidate
    raise FileNotFoundError(anchor)

_ENGINE = _canonical_hqh539_path(Path(__file__))
_spec = importlib.util.spec_from_file_location("hqh539_canonical", _ENGINE)
_mod = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_mod)
T3 = _mod.T3
'''


class TestLocate(unittest.TestCase):
    def test_fake_tree_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine = root / "Desktop" / "539_Engine"
            labs = root / "Desktop" / "539Labs" / "python"
            downloads = root / "Downloads"
            engine.mkdir(parents=True)
            labs.mkdir(parents=True)
            downloads.mkdir(parents=True)
            (engine / "hqh539.py").write_text("# canonical\n", encoding="utf-8")
            (labs / "hqh539.py").write_text(WRAPPER_TEMPLATE, encoding="utf-8")
            (downloads / "hqh539.py").write_text(WRAPPER_TEMPLATE, encoding="utf-8")

            anchor = engine / "test_hqh539.py"
            self.assertEqual(
                canonical_hqh539_path(anchor),
                engine / "hqh539.py",
            )
            self.assertEqual(
                sibling_module(anchor, "539Labs", "python", "hqh539.py"),
                labs / "hqh539.py",
            )
            self.assertEqual(
                downloads_hqh539_path(downloads / "hqh539.py"),
                downloads / "hqh539.py",
            )

    def test_downloads_wrapper_finds_canonical(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine = root / "Desktop" / "539_Engine"
            downloads = root / "Downloads"
            engine.mkdir(parents=True)
            downloads.mkdir(parents=True)
            (engine / "hqh539.py").write_text(
                "def T3(n):\n    return n\n", encoding="utf-8"
            )
            wrapper = downloads / "hqh539.py"
            wrapper.write_text(WRAPPER_TEMPLATE, encoding="utf-8")

            import importlib.util

            module_spec = importlib.util.spec_from_file_location("dl_wrapper", wrapper)
            module = importlib.util.module_from_spec(module_spec)
            assert module_spec.loader is not None
            module_spec.loader.exec_module(module)
            self.assertEqual(module.T3(4), 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)