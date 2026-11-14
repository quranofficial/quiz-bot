# -*- coding: utf-8 -*-
"""تاقیکردنەوەی مینیو و ڕێڕەوی دوگمەکان."""

import unittest
from types import SimpleNamespace

import keyboards
import texts as T


class FakeStorage:
    def db(self):
        return {"tree": [{"id": "root", "type": "folder"}], "pages": [{"id": "p1"}]}

    def get_event(self):
        return {"enabled": True}

    def menu_label(self, key):
        return None

    def menu_extras(self):
        return []

    def is_admin(self, user_id):
        return False


class KeyboardNavigationTest(unittest.TestCase):
    def setUp(self):
        self.storage = FakeStorage()
        self.user = SimpleNamespace(id=123)

    @staticmethod
    def callbacks(markup):
        return [
            button.callback_data
            for row in markup.inline_keyboard
            for button in row
        ]

    def test_main_menu_keeps_core_actions_and_account_entry(self):
        markup = keyboards.main_menu(self.storage, self.user)
        callbacks = self.callbacks(markup)

        for callback in ("nav:root", "mq", "qn", "ask", "fc", "pgs", "account"):
            with self.subTest(callback=callback):
                self.assertIn(callback, callbacks)

    def test_learning_actions_are_grouped_two_per_row(self):
        markup = keyboards.main_menu(self.storage, self.user)
        first_rows = markup.inline_keyboard[:2]
        self.assertEqual([len(row) for row in first_rows], [2, 2])

    def test_account_menu_has_all_personal_destinations(self):
        markup = keyboards.account_menu(self.storage)
        callbacks = self.callbacks(markup)

        for callback in ("mystats", "myinbox", "myq", "myrp", "home"):
            with self.subTest(callback=callback):
                self.assertIn(callback, callbacks)

    def test_admin_menu_retains_all_management_routes(self):
        markup = keyboards.admin_main(2, 3, 10, 1)
        callbacks = self.callbacks(markup)

        for callback in ("am:root", "impfile", "admtk", "admrp", "qnev",
                         "bcast", "usr", "admpgs", "menu", "admadm",
                         "setview", "stats", "pendq", "home"):
            with self.subTest(callback=callback):
                self.assertIn(callback, callbacks)


if __name__ == "__main__":
    unittest.main()
