# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Temporary AGL style-name aliases for the pinned PDF font decoder."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from pypdf._codecs import adobe_glyphs
from pypdf.generic import ArrayObject, DictionaryObject, IndirectObject, NameObject

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pypdf.generic import PdfObject


def _resolved(value: object) -> object:
    return value.get_object() if isinstance(value, IndirectObject) else value


def _fonts(resources: DictionaryObject) -> Iterator[DictionaryObject]:
    pending = [resources]
    seen = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        fonts = _resolved(current.get("/Font"))
        if isinstance(fonts, DictionaryObject):
            for value in fonts.values():
                font = _resolved(value)
                if isinstance(font, DictionaryObject):
                    yield font
        objects = _resolved(current.get("/XObject"))
        if not isinstance(objects, DictionaryObject):
            continue
        for value in objects.values():
            form = _resolved(value)
            if isinstance(form, DictionaryObject) and form.get("/Subtype") == "/Form":
                nested = _resolved(form.get("/Resources"))
                if isinstance(nested, DictionaryObject):
                    pending.append(nested)


def _glyph_alias(value: object) -> NameObject | None:
    if not isinstance(value, NameObject) or "." not in value or value in adobe_glyphs:
        return None
    base = value.partition(".")[0]
    return NameObject(base) if base in adobe_glyphs else None


def _normalized_encoding(font: DictionaryObject) -> DictionaryObject | None:
    if "/ToUnicode" in font:
        return None
    encoding = _resolved(font.get("/Encoding"))
    if not isinstance(encoding, DictionaryObject):
        return None
    differences = _resolved(encoding.get("/Differences"))
    if not isinstance(differences, ArrayObject):
        return None
    normalized = ArrayObject([_glyph_alias(value) or value for value in differences])
    if normalized == differences:
        return None
    result = DictionaryObject(encoding)
    result[NameObject("/Differences")] = normalized
    return result


@contextmanager
def normalized_font_encodings(resources: DictionaryObject) -> Iterator[None]:
    """Use known AGL base names during extraction, then restore resource fields.

    AGL excludes a glyph's period suffix from its Unicode meaning. Only the
    pinned decoder's unknown names with a known base get an encoding copy.
    Explicit ToUnicode maps and the original PDF bytes remain authoritative.
    """
    changed: list[tuple[DictionaryObject, PdfObject]] = []
    try:
        for font in _fonts(resources):
            replacement = _normalized_encoding(font)
            if replacement is not None:
                original = font.raw_get("/Encoding")
                changed.append((font, original))
                font[NameObject("/Encoding")] = replacement
        yield
    finally:
        for font, original in reversed(changed):
            font[NameObject("/Encoding")] = original
