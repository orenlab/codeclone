from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping


def report_run_identity(report_document: Mapping[str, object]) -> str:
    report_bytes = json.dumps(
        report_document,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(report_bytes).hexdigest()


def publish_run_reference(report_document: Mapping[str, object]) -> dict[str, str]:
    return {
        "run_id": report_run_identity(report_document),
        "report_digest": report_run_identity(report_document),
    }


# This file intentionally defines its own report_run_identity, and it is not a
# consumer of codeclone.utils.run_identity. It is analysed source: the semantic
# authority detector reads it as a corpus specimen -- one volatile identity
# producer feeding two published references -- and what the detector must see is
# exactly this shape. Semantic ownership does not apply to it, because ownership
# is a rule about the product's own answers, and this text is not one of them;
# it is a measurement input that happens to be written in Python.
#
# So the name is deliberately left colliding. Renaming it to keep the namespace
# tidy would edit the thing being measured to suit the architecture of the
# instrument measuring it, and the reading afterwards would be of a corpus we
# changed rather than the one we meant to observe.
#
# The comment sits below the definitions on purpose: the corpus is pinned by
# digest in tests/test_extractor.py, and the symbols' line spans are part of
# what the extractor records, so an explanation placed above them would move
# the specimen while explaining why we must not.
