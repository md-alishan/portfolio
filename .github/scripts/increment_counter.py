"""Persist one counter increment per Istanbul calendar day."""
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def increment(html, now):
    if not 18 <= now.hour < 22:
        return html
    pattern = r'(<output\b[^>]*\bid="counter"[^>]*>)(\d+)(</output>)'
    matches = list(re.finditer(pattern, html))
    if len(matches) != 1:
        raise ValueError('Expected exactly one numeric counter output')
    match = matches[0]
    today = now.date().isoformat()
    opening = match[1]
    previous = re.search(r' data-updated="([^"]+)"', opening)
    if previous and previous[1] >= today:
        return html
    opening = re.sub(r' data-updated="[^"]*"', '', opening)
    opening = opening[:-1] + f' data-updated="{today}">'
    return html[:match.start()] + opening + str(int(match[2]) + 1) + match[3] + html[match.end():]


if __name__ == '__main__':
    path = Path('index.html')
    original = path.read_text()
    updated = increment(original, datetime.now(ZoneInfo('Europe/Istanbul')))
    if updated != original:
        path.write_text(updated)
        print('Counter increased by 1.')
    else:
        print('No change: already updated today or outside 18:00–22:00 Istanbul time.')
