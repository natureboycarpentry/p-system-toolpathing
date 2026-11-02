"""Crash-proof step log for Generate (temporary diagnostics).

Each step is appended and fsynced before the Fusion call it names, so the last
line survives a native Fusion crash. File: ~/Library/Logs/LamelloPSystemCNC/generate.log
(on Windows: %LOCALAPPDATA%/LamelloPSystemCNC/generate.log).
"""

import os
import time


def _path():
    if os.name == 'nt':
        base = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'LamelloPSystemCNC')
    else:
        base = os.path.join(os.path.expanduser('~'), 'Library', 'Logs', 'LamelloPSystemCNC')
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, 'generate.log')


def start(title):
    try:
        with open(_path(), 'w', encoding='utf-8') as handle:
            handle.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")} {title}\n')
    except Exception:
        pass


def step(message):
    try:
        with open(_path(), 'a', encoding='utf-8') as handle:
            handle.write(f'{time.strftime("%H:%M:%S")} {message}\n')
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        pass
