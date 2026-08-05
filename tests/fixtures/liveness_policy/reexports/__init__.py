from typing import TYPE_CHECKING

from .impl import fetch_snapshot as fetch_snapshot
from .impl import parse_manifest as manifest_alias  # noqa: F401

if TYPE_CHECKING:
    from .impl import annotate_frame as annotate_frame
