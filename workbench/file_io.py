"""Read current files through short Windows sharing locks without changing access."""
import os
from pathlib import Path
import time


_WINDOWS = os.name == 'nt'
# Six attempts, at most 1.55 seconds of waiting; permanent denial still fails.
_READ_DELAYS = (.05, .1, .2, .4, .8)


def open_read(path, mode='rb', *, encoding=None, errors=None):
    """Open for reading, retrying only Windows access/sharing denial.

    The retry opens the requested file again: it does not return cached bytes,
    change permissions, or substitute content when the file is unavailable.
    """
    if mode not in {'r', 'rt', 'rb'}:
        raise ValueError('open_read only accepts read modes')
    target = Path(path)
    for attempt in range(len(_READ_DELAYS) + 1):
        try:
            return target.open(mode, encoding=encoding, errors=errors)
        except PermissionError as error:
            if (not _WINDOWS or getattr(error, 'winerror', None) not in {None, 5, 32, 33}
                    or attempt == len(_READ_DELAYS)):
                raise
            time.sleep(_READ_DELAYS[attempt])


def read_bytes(path):
    with open_read(path) as source:
        return source.read()


def read_text(path, encoding='utf-8', *, errors=None):
    with open_read(path, 'r', encoding=encoding, errors=errors) as source:
        return source.read()
