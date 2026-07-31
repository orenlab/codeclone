"""A sibling module that imports the helper the package never re-exports.

This module is what makes ``InternalHelper`` a *discriminating* twin rather
than an inert one. The import binds ``distillations.api:InternalHelper`` into
``referenced_qualnames`` (an intra-module call does not - proven by probe),
while the package ``__init__`` re-exports only ``DocumentedService`` and
``exported_function``.

The two candidate rules therefore disagree here, which is the whole point:
a rule keyed on "a referenced class living in a module the package imports"
roots ``InternalHelper.never_called_public_method``; only a rule keyed on the
export chain itself - the names the package actually re-exported - leaves it
dead.
"""

from .api import InternalHelper


def use_helper() -> InternalHelper:
    return InternalHelper()
