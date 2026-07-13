# ruff: noqa

# The repository lint floor is Python 3.10, so 3.11-only grammar is stored as
# source data and parsed by the version-gated wire test.
SOURCE = """\
def exception_group():
    handled = 0
    try:
        raise ExceptionGroup("group", [ValueError("value")])
    except* ValueError as errors:
        handled = len(errors.exceptions)
    return handled
"""
