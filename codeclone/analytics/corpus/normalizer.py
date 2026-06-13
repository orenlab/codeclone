# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from ...contracts import CORPUS_NORMALIZER_VERSION
from .keys import sha256_hex

_DIGEST_PATTERN = re.compile(
    r"\b[a-f0-9]{8,64}\b",
    re.IGNORECASE,
)
_UUID_PATTERN = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_ISO_TIMESTAMP_PATTERN = re.compile(
    r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\b"
)
_ABS_PATH_PATTERN = re.compile(r"(?:/[\w./-]+|(?:[A-Za-z]:\\)[\w\\./-]+)")
_TEMPLATE_PREFIXES = (
    "implement ",
    "fix ",
    "refactor ",
    "add ",
    "update ",
    "validate ",
)


@dataclass(frozen=True, slots=True)
class NormalizedText:
    text: str
    digest: str
    normalizer_version: str


def normalize_corpus_text(raw: str) -> NormalizedText:
    text = unicodedata.normalize("NFC", raw)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    text = _DIGEST_PATTERN.sub("<digest>", text)
    text = _UUID_PATTERN.sub("<uuid>", text)
    text = _ISO_TIMESTAMP_PATTERN.sub("<timestamp>", text)
    text = _ABS_PATH_PATTERN.sub("<path>", text)
    lowered = text.lower()
    for prefix in _TEMPLATE_PREFIXES:
        if lowered.startswith(prefix):
            text = text[len(prefix) :].lstrip()
            break
    digest = sha256_hex(text)
    return NormalizedText(
        text=text,
        digest=digest,
        normalizer_version=CORPUS_NORMALIZER_VERSION,
    )


def source_content_digest(raw: str) -> str:
    return normalize_corpus_text(raw).digest


__all__ = ["NormalizedText", "normalize_corpus_text", "source_content_digest"]
