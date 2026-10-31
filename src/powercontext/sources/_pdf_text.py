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

"""Honor the original PDF's explicit marked-content replacement text."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pypdf import PageObject
from pypdf.generic import (
    ArrayObject,
    ByteStringObject,
    DictionaryObject,
    IndirectObject,
    NameObject,
    NumberObject,
    TextStringObject,
    create_string_object,
)

from powercontext.sources._pdf_font_encodings import normalized_font_encodings


@dataclass
class _MarkedText:
    replacement: str | None
    emitted: bool = False


def _resolved(value: object) -> object:
    return value.get_object() if isinstance(value, IndirectObject) else value


def _replacement_text(value: object) -> str | None:
    value = _resolved(value)
    if isinstance(value, bytes):
        value = create_string_object(value)
    return str(value) if isinstance(value, TextStringObject) else None


class _ActualTextVisitor:
    def __init__(self, resources: DictionaryObject) -> None:
        self._marked: list[_MarkedText] = []
        self._resources = [resources]
        self._form_depths: list[int] = []

    def before(self, operator: bytes, operands: list[Any], _cm: list[float], _tm: list[float]) -> None:
        if operator in (b"BMC", b"BDC"):
            properties = _resolved(operands[1]) if operator == b"BDC" and len(operands) >= 2 else None
            if isinstance(properties, NameObject):
                named = _resolved(self._resources[-1].get("/Properties"))
                properties = _resolved(named.get(properties)) if isinstance(named, DictionaryObject) else None
            replacement = (
                _replacement_text(properties.get("/ActualText")) if isinstance(properties, DictionaryObject) else None
            )
            self._marked.append(_MarkedText(replacement))
        elif operator == b"EMC" and self._marked:
            self._marked.pop()
        elif operator == b"Do" and operands:
            current = self._resources[-1]
            objects = _resolved(current.get("/XObject"))
            form = _resolved(objects.get(operands[0])) if isinstance(objects, DictionaryObject) else None
            resources = _resolved(form.get("/Resources")) if isinstance(form, DictionaryObject) else None
            self._form_depths.append(len(self._marked))
            self._resources.append(resources if isinstance(resources, DictionaryObject) else current)
        marked = next((item for item in self._marked if item.replacement is not None), None)
        if marked is not None and operator in (b"Tj", b"TJ", b"'", b'"') and operands:
            # Pinned pypdf treats str operands as decoded Unicode. Only this
            # extraction's parsed operand changes; PDF bytes and fonts do not.
            replacement = TextStringObject("" if marked.emitted else marked.replacement or "")
            if operator == b"TJ":
                values = []
                emitted = False
                for value in operands[0]:
                    if isinstance(value, (str, bytes)):
                        values.append(ByteStringObject(b"") if emitted else replacement)
                        emitted = True
                    else:
                        # The replacement owns internal whitespace; kerning
                        # numbers must not add gaps into its logical text.
                        values.append(NumberObject(0))
                operands[0] = ArrayObject(values)
                marked.emitted = marked.emitted or emitted
            else:
                operands[2 if operator == b'"' else 0] = replacement
                marked.emitted = True

    def after(self, operator: bytes, _operands: list[Any], _cm: list[float], _tm: list[float]) -> None:
        if operator == b"Do" and self._form_depths:
            del self._marked[self._form_depths.pop() :]
            self._resources.pop()


def extract_pdf_page_text(page: PageObject) -> str:
    """Extract one physical page, retaining explicit ActualText replacements."""

    resources = _resolved(page.get("/Resources"))
    resources = resources if isinstance(resources, DictionaryObject) else DictionaryObject()
    with normalized_font_encodings(resources):
        visitor = _ActualTextVisitor(resources)
        return page.extract_text(visitor_operand_before=visitor.before, visitor_operand_after=visitor.after) or ""
