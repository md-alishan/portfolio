import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from increment_counter import increment


class CounterTests(unittest.TestCase):
    html = '<p>Counter: <output id="counter" aria-live="polite">1</output></p>'

    def at(self, day=14, hour=19):
        return datetime(2026, 9, day, hour, tzinfo=ZoneInfo('Europe/Istanbul'))

    def test_one_increment_per_day_and_next_day(self):
        updated = increment(self.html, self.at())
        self.assertIn('>2</output>', updated)
        self.assertIn('data-updated="2026-09-14"', updated)
        self.assertEqual(increment(updated, self.at(hour=21)), updated)
        self.assertIn('>3</output>', increment(updated, self.at(day=15)))

    def test_outside_window(self):
        for hour in (0, 17, 22, 23):
            self.assertEqual(increment(self.html, self.at(hour=hour)), self.html)
        self.assertIn('>2</output>', increment(self.html, self.at(hour=18)))

    def test_malformed_counter_fails_without_writing(self):
        for html in ('<p>Missing</p>', self.html * 2, self.html.replace('>1<', '>oops<')):
            with self.assertRaises(ValueError):
                increment(html, self.at())

    def test_preserves_other_content(self):
        updated = increment('before' + self.html + 'after', self.at())
        self.assertTrue(updated.startswith('before<p>Counter: '))
        self.assertTrue(updated.endswith('</p>after'))


if __name__ == '__main__':
    unittest.main()
