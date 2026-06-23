import json
import unittest
from pathlib import Path

from hqh539 import STEPS, T3, hqh_539_256, hqh_539_512, iterate_n_steps

GOLDEN = json.loads((Path(__file__).parent / "golden_vectors.json").read_text(encoding="utf-8"))


class TestT3(unittest.TestCase):
    def test_branch_oracle_values(self):
        for n_str, expected in GOLDEN["t3"].items():
            self.assertEqual(T3(int(n_str)), expected)


class TestIterateNSteps(unittest.TestCase):
    def test_exactly_539_uniform_iterations(self):
        n = 10**18
        state = n
        for _ in range(STEPS):
            state = T3(state)
        self.assertEqual(state, iterate_n_steps(n, STEPS))

    def test_large_seed_oracle_values(self):
        for n_str, expected in GOLDEN["iterate_n_steps_539"].items():
            self.assertEqual(iterate_n_steps(int(n_str), STEPS), expected)


class TestHQH539(unittest.TestCase):
    def test_output_length_and_hex(self):
        digest = hqh_539_512("probe")
        self.assertEqual(len(digest), 128)
        self.assertEqual(digest, digest.lower())
        self.assertTrue(all(c in "0123456789abcdef" for c in digest))

    def test_256_bit_truncation(self):
        full = hqh_539_512("The universe counts in threes.")
        short = hqh_539_256("The universe counts in threes.")
        self.assertEqual(len(short), 64)
        self.assertEqual(short, full[:64])
        self.assertEqual(short, GOLDEN["hqh_539_256_prefix"])

    def test_deterministic_repeated_calls(self):
        msg = "The universe counts in threes."
        salt = b"hqh539-2026"
        self.assertEqual(hqh_539_512(msg, salt), hqh_539_512(msg, salt))

    def test_salt_changes_digest(self):
        msg = "identical message"
        self.assertNotEqual(hqh_539_512(msg, b"salt-a"), hqh_539_512(msg, b"salt-b"))

    def test_golden_hash_vectors(self):
        self.assertEqual(hqh_539_512(b"", b""), GOLDEN["hqh_539_512"]["empty"])
        self.assertEqual(
            hqh_539_512("The universe counts in threes.", b""),
            GOLDEN["hqh_539_512"]["canonical"],
        )
        self.assertEqual(
            hqh_539_512(str(10**18), b""),
            GOLDEN["hqh_539_512"]["large_int"],
        )
        self.assertEqual(
            hqh_539_512("The universe counts in threes.", b"hqh539-2026"),
            GOLDEN["hqh_539_512"]["salted"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)