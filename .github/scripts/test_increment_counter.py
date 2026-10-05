import os
import re
import subprocess
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import increment_counter as counter


class CounterTests(unittest.TestCase):
    html = '<p>Counter: <output id="counter" aria-live="polite">19</output></p>'
    repository = 'md-alishan/portfolio'

    def at(self, day=date(2026, 10, 5), minute=19 * 60 + 59):
        return datetime(day.year, day.month, day.day, minute // 60, minute % 60,
                        tzinfo=counter.ISTANBUL)

    def finish(self, html, now):
        messages = []
        for _ in range(6):
            html, message = counter.next_update(html, now, self.repository)
            if message is None:
                break
            messages.append(message)
        return html, messages

    def test_schedule_bounds_distribution_and_repeatability(self):
        amounts = set()
        slots = set()
        for offset in range(365):
            day = date(2026, 1, 1) + timedelta(days=offset)
            times, messages = counter.plan(day, self.repository)
            self.assertEqual((times, messages), counter.plan(day, self.repository))
            self.assertTrue(1 <= len(times) <= 5)
            self.assertEqual(times, sorted(set(times)))
            self.assertTrue(all(360 <= t <= 1180 for t in times))
            self.assertEqual(len(messages), len(set(messages)))
            amounts.add(len(times))
            slots.update(times)
        self.assertEqual(amounts, {1, 2, 3, 4, 5})
        self.assertGreater(len(slots), 30)

    def test_fourteen_eligible_messages(self):
        self.assertEqual(len(set(counter.MESSAGES)), 14)
        for message in counter.MESSAGES:
            self.assertNotRegex(message.lower(), r'daily|auto')

    def test_timing_one_commit_per_slot_and_repeat_safety(self):
        now = self.at()
        times, _ = counter.plan(now.date(), self.repository)
        html = self.html
        for ordinal, minute in enumerate(times, 1):
            unchanged, message = counter.next_update(html, self.at(minute=minute - 1), self.repository)
            self.assertEqual(unchanged, html)
            self.assertIsNone(message)
            html, message = counter.next_update(html, self.at(minute=minute), self.repository)
            self.assertIsNotNone(message)
            self.assertIn(f'>{19 + ordinal}</output>', html)
            self.assertEqual(counter.next_update(html, self.at(minute=minute), self.repository), (html, None))

    def test_late_recovery_and_date_rollover(self):
        late = self.at(minute=23 * 60 + 40)
        html, messages = self.finish(self.html, late)
        self.assertEqual(len(messages), len(counter.plan(late.date(), self.repository)[0]))
        tomorrow = late.date() + timedelta(days=1)
        self.assertEqual(counter.next_update(html, self.at(tomorrow, 0), self.repository), (html, None))
        new_html, messages = self.finish(html, self.at(tomorrow))
        self.assertEqual(len(messages), len(counter.plan(tomorrow, self.repository)[0]))
        self.assertIn(f'data-updated="{tomorrow}"', new_html)

    def test_legacy_progress_and_unrelated_markup(self):
        day = self.at().date()
        original = ('before' + self.html + 'after').replace('aria-live="polite"', f'aria-live="polite" data-updated="{day}"')
        updated, messages = self.finish(original, self.at())
        self.assertEqual(len(messages), len(counter.plan(day, self.repository)[0]) - 1)
        self.assertTrue(updated.startswith('before<p>Counter: '))
        self.assertTrue(updated.endswith('</p>after'))
        self.assertIn('aria-live="polite"', updated)

    def test_invalid_state_fails(self):
        cases = ['<p>Missing</p>', self.html * 2, self.html.replace('>19<', '>oops<')]
        for attrs in ['data-updated="2099-01-01"', 'data-updated="bad"',
                      'data-progress="2"', 'data-updated="2026-10-05" data-progress="6"',
                      'data-updated="2026-10-05" data-updated="2026-10-05"']:
            cases.append(self.html.replace('aria-live="polite"', attrs))
        for html in cases:
            with self.subTest(html=html), self.assertRaises(ValueError):
                counter.next_update(html, self.at(), self.repository)

    def test_utc_time_converted_to_istanbul(self):
        from datetime import timezone
        instant = self.at()
        self.assertEqual(counter.next_update(self.html, instant, self.repository),
                         counter.next_update(self.html, instant.astimezone(timezone.utc), self.repository))

    def test_real_git_commits_push_and_partial_failure_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote, checkout = root / 'remote.git', root / 'checkout'
            def run(*args, cwd=None):
                return subprocess.check_output(['git', *map(str, args)], cwd=cwd, stderr=subprocess.DEVNULL, text=True).strip()
            run('init', '--bare', remote)
            run('init', '-b', 'main', checkout)
            run('config', 'user.name', 'Test', cwd=checkout)
            run('config', 'user.email', 'test@example.test', cwd=checkout)
            (checkout / 'index.html').write_text(self.html)
            run('add', 'index.html', cwd=checkout)
            run('commit', '-m', 'Fixture', cwd=checkout)
            run('remote', 'add', 'origin', remote, cwd=checkout)
            run('push', '-u', 'origin', 'main', cwd=checkout)
            day = next(date(2026, 10, d) for d in range(1, 29)
                       if len(counter.plan(date(2026, 10, d), self.repository)[0]) == 5)
            now = self.at(day)
            old_cwd = Path.cwd()
            real_git = counter.git
            pushes = 0
            def failing_git(*args):
                nonlocal pushes
                if args[0] == 'push':
                    pushes += 1
                    if pushes == 2:
                        raise RuntimeError('Simulated network interruption')
                return real_git(*args)
            try:
                os.chdir(checkout)
                with patch.object(counter, 'git', side_effect=failing_git):
                    with self.assertRaises(RuntimeError):
                        counter.maintain(self.repository, lambda: now)
                # A fresh runner receives only the one successfully pushed update.
                run('fetch', 'origin')
                run('reset', '--hard', 'origin/main')
                self.assertEqual(counter.maintain(self.repository, lambda: now), 4)
                self.assertEqual(counter.maintain(self.repository, lambda: now), 0)
                self.assertEqual(run('rev-list', '--count', 'main'), '6')
                self.assertEqual(run('rev-parse', 'main'), run('rev-parse', 'refs/heads/main', cwd=remote))
                self.assertIn('>24</output>', Path('index.html').read_text())
                self.assertEqual(set(run('log', '-5', '--format=%s').splitlines()),
                                 set(counter.plan(day, self.repository)[1]))
                Path('index.html').write_text('user changes')
                with self.assertRaises(RuntimeError):
                    counter.maintain(self.repository, lambda: now)
            finally:
                os.chdir(old_cwd)


if __name__ == '__main__':
    unittest.main()
