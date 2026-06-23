import importlib.util
import json
import unittest
from pathlib import Path

from locate import canonical_hqh539_path, downloads_hqh539_path, sibling_module

ANCHOR = Path(__file__)
ENGINE_MODULE = canonical_hqh539_path(ANCHOR)
ENGINE_DIR = ENGINE_MODULE.parent
LABS_MODULE = sibling_module(ANCHOR, "539Labs", "python", "hqh539.py")
DOWNLOADS_MODULE = downloads_hqh539_path(ANCHOR)
GOLDEN = json.loads((ENGINE_DIR / "golden_vectors.json").read_text(encoding="utf-8"))


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestCrossImpl(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = _load_module("hqh539_engine", ENGINE_MODULE)
        cls.labs = _load_module("hqh539_labs", LABS_MODULE)
        cls.downloads = _load_module("hqh539_downloads", DOWNLOADS_MODULE)

    def test_api_surface_parity(self):
        for mod in (self.engine, self.labs, self.downloads):
            for name in ("T3", "iterate_n_steps", "hqh_539", "hqh_539_512", "hqh_539_256"):
                self.assertTrue(hasattr(mod, name), f"{mod.__name__} missing {name}")

    def test_t3_matches_across_impls(self):
        for n_str, expected in GOLDEN["t3"].items():
            n = int(n_str)
            self.assertEqual(self.engine.T3(n), expected)
            self.assertEqual(self.labs.T3(n), expected)
            self.assertEqual(self.downloads.T3(n), expected)

    def test_iterate_matches_across_impls(self):
        for n_str, expected in GOLDEN["iterate_n_steps_539"].items():
            n = int(n_str)
            self.assertEqual(self.engine.iterate_n_steps(n), expected)
            self.assertEqual(self.labs.iterate_n_steps(n), expected)
            self.assertEqual(self.downloads.iterate_n_steps(n), expected)

    def test_hash_matches_across_impls(self):
        cases = [
            (b"", b""),
            ("The universe counts in threes.".encode("utf-8"), b""),
            (str(10**18).encode("utf-8"), b""),
            ("The universe counts in threes.".encode("utf-8"), b"hqh539-2026"),
        ]
        for message, salt in cases:
            engine_digest = self.engine.hqh_539_512(message, salt)
            labs_digest = self.labs.hqh_539_512(message, salt)
            downloads_digest = self.downloads.hqh_539_512(message, salt)
            labs_alias = self.labs.hqh539(message, salt)
            self.assertEqual(engine_digest, labs_digest)
            self.assertEqual(engine_digest, downloads_digest)
            self.assertEqual(engine_digest, labs_alias)

    def test_256_matches_across_impls(self):
        msg = "The universe counts in threes."
        self.assertEqual(self.engine.hqh_539_256(msg), self.labs.hqh_539_256(msg))
        self.assertEqual(self.engine.hqh_539_256(msg), self.downloads.hqh_539_256(msg))
        self.assertEqual(self.engine.hqh_539_256(msg), GOLDEN["hqh_539_256_prefix"])

    def test_str_salt_accepted(self):
        msg = "The universe counts in threes."
        self.assertEqual(
            self.engine.hqh_539_512(msg, "hqh539-2026"),
            self.engine.hqh_539_512(msg, b"hqh539-2026"),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)