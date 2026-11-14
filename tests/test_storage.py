# -*- coding: utf-8 -*-
"""تاقیکردنەوەی یەکەی بۆ یارمەتیدەرەکانی داتا."""

import unittest

import storage


class StorageHelpersTest(unittest.TestCase):
    def test_knum_converts_ascii_digits_to_eastern_arabic(self):
        self.assertEqual(storage.knum(12034), "١٢٠٣٤")

    def test_to_int_accepts_ascii_and_eastern_arabic_digits(self):
        self.assertEqual(storage.to_int("123"), 123)
        self.assertEqual(storage.to_int("١٢٣"), 123)
        self.assertEqual(storage.to_int(" ۱۲۳ "), 123)

    def test_to_int_rejects_invalid_values(self):
        self.assertIsNone(storage.to_int("12x"))
        self.assertIsNone(storage.to_int(None))

    def test_tree_stats_counts_nested_folders_and_questions(self):
        tree = [
            {
                "id": "root",
                "type": "folder",
                "children": [
                    {"id": "q1", "type": "question"},
                    {
                        "id": "nested",
                        "type": "folder",
                        "children": [{"id": "q2", "type": "question"}],
                    },
                ],
            },
            {"id": "q3", "type": "question"},
        ]
        self.assertEqual(storage.tree_stats(tree), (2, 3))

    def test_has_correct_requires_a_marked_correct_option(self):
        self.assertTrue(storage.has_correct({
            "options": [{"correct": False}, {"correct": True}]
        }))
        self.assertFalse(storage.has_correct({
            "options": [{"correct": False}, {}]
        }))
        self.assertFalse(storage.has_correct(None))


if __name__ == "__main__":
    unittest.main()
