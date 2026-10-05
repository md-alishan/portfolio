"""Maintain persisted counter state with repeatable, date-specific schedules."""
import hashlib
import os
import random
import re
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ISTANBUL = ZoneInfo('Europe/Istanbul')
MESSAGES = (
    'Update persisted counter state',
    'Advance counter value',
    'Persist counter revision',
    'Refresh counter state metadata',
    'Apply counter state transition',
    'Record counter progression',
    'Update counter output value',
    'Commit counter state change',
    'Persist updated output state',
    'Advance stored output value',
    'Refresh persisted counter value',
    'Record output state transition',
    'Update counter revision metadata',
    'Persist counter progression metadata',
)
COUNTER = re.compile(r'(<output\b[^>]*\bid="counter"[^>]*>)(\d+)(</output>)')


def plan(day, repository):
    # A stable random seed keeps the same plan across retries and fresh runners.
    seed = hashlib.sha256(f'counter-v2:{repository}:{day.isoformat()}'.encode()).digest()
    rng = random.Random(int.from_bytes(seed, 'big'))
    amount = rng.randint(1, 5)
    # Separate 20-minute slots, ending before 20:00 to leave scheduling headroom.
    times = sorted(rng.sample(range(6 * 60, 20 * 60 - 19, 20), amount))
    messages = rng.sample(MESSAGES, amount)
    return times, messages


def next_update(html, now, repository):
    now = now.astimezone(ISTANBUL)
    matches = list(COUNTER.finditer(html))
    if len(matches) != 1:
        raise ValueError('Expected exactly one numeric counter output')
    match = matches[0]
    opening = match[1]
    today = now.date().isoformat()
    dates = re.findall(r' data-updated="([^"]*)"', opening)
    counts = re.findall(r' data-progress="([^"]*)"', opening)
    if len(dates) > 1 or len(counts) > 1:
        raise ValueError('Duplicate counter progress attributes')
    previous = dates[0] if dates else None
    if previous:
        datetime.strptime(previous, '%Y-%m-%d')
        if previous > today:
            raise ValueError('Counter progress is dated in the future')
    if counts and (not counts[0].isdigit() or not 1 <= int(counts[0]) <= 5):
        raise ValueError('Invalid counter progress')
    if counts and not previous:
        raise ValueError('Counter progress requires a date')
    # Preserve an increment already made by the previous implementation today.
    completed = (int(counts[0]) if counts else 1) if previous == today else 0
    times, messages = plan(now.date(), repository)
    due = sum(minute <= now.hour * 60 + now.minute for minute in times)
    if completed >= due:
        return html, None
    opening = re.sub(r' data-(?:updated|progress)="[^"]*"', '', opening)
    opening = opening[:-1] + f' data-updated="{today}" data-progress="{completed + 1}">'
    updated = html[:match.start()] + opening + str(int(match[2]) + 1) + match[3] + html[match.end():]
    return updated, messages[completed]


def git(*args):
    return subprocess.check_output(['git', *args], text=True).strip()


def maintain(repository, clock=None):
    clock = clock or (lambda: datetime.now(ISTANBUL))
    if git('status', '--porcelain', '--untracked-files=no'):
        raise RuntimeError('Refusing to modify a checkout with existing changes')
    git('pull', '--ff-only', 'origin', 'main')
    path = Path('index.html')
    commits = 0
    for _ in range(5):
        original = path.read_text()
        updated, message = next_update(original, clock(), repository)
        if message is None:
            break
        path.write_text(updated)
        git('diff', '--check')
        git('add', '--', 'index.html')
        git('commit', '-m', message)
        # Persist progress after every commit, including partially completed runs.
        git('push', 'origin', 'HEAD:main')
        commits += 1
    print(f'Published {commits} counter state changes.')
    return commits


if __name__ == '__main__':
    maintain(os.environ['GITHUB_REPOSITORY'])
