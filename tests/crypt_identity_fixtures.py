"""Independent writer-side fixtures for explicit PDF stream crypt filters.

Only pypdf's ordinary writer encryption is used. Explicit Identity overrides the
stream-data encryption, while dictionary strings retain the ordinary StrF path.
No candidate Reader, decryptor or filter-normalization helper is imported.
"""

from __future__ import annotations

import io
import re
import zlib
from typing import Literal

from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DictionaryObject,
    EncodedStreamObject,
    NameObject,
    NullObject,
    NumberObject,
    TextStringObject,
)

LABEL = "dictionary string encryption check"
FIRST_TEXT = "Implicit AES revenue control text."
SECOND_TEXT = "Explicit Identity revenue evidence text."


def _raw_stream(content: bytes, object_number: int) -> bytes:
    start = content.index(f"{object_number} 0 obj\n".encode("ascii"))
    stream = content.index(b"stream\n", start)
    header = content[start:stream]
    match = re.search(rb"/Length\s+(\d+)", header)
    assert match is not None
    length = int(match.group(1))
    return content[stream + len(b"stream\n"):stream + len(b"stream\n") + length]


def build_fixture(
    *,
    global_identity: bool = False,
    explicit_name: str | None = "/Identity",
    flate: bool = False,
    truncate_flate: bool = False,
    blank: bool = False,
    user_password: str = "",
    algorithm: Literal["AES-128", "AES-256"] = "AES-128",
) -> dict:
    writer = PdfWriter()
    writer.pdf_header = "%PDF-2.0" if algorithm == "AES-256" else "%PDF-1.6"
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    font_ref = writer._add_object(font)
    raw_payloads = {}
    identity_streams = set()
    stream_numbers = []
    expected = ("", "") if blank else (FIRST_TEXT, SECOND_TEXT)
    for number, text in enumerate(expected, start=1):
        page = writer.add_blank_page(width=612, height=792)
        if blank:
            commands = b"q Q"
        else:
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref}),
            })
            commands = f"BT /F1 12 Tf 30 740 Td ({text}) Tj ET".encode("ascii")
        stream = EncodedStreamObject()
        stream[NameObject("/FixtureLabel")] = TextStringObject(LABEL)
        if number == 2 and explicit_name is not None:
            parameters = DictionaryObject({NameObject("/Type"): NameObject("/CryptFilterDecodeParms")})
            if explicit_name:
                parameters[NameObject("/Name")] = NameObject(explicit_name)
            if flate:
                stream[NameObject("/Filter")] = ArrayObject([NameObject("/Crypt"), NameObject("/FlateDecode")])
                stream[NameObject("/DecodeParms")] = ArrayObject([parameters, NullObject()])
                payload = zlib.compress(commands)
                if truncate_flate:
                    payload = payload[:-3]
            else:
                stream[NameObject("/Filter")] = NameObject("/Crypt")
                stream[NameObject("/DecodeParms")] = parameters
                payload = commands
        else:
            payload = commands
        stream._data = payload
        reference = writer._add_object(stream)
        page[NameObject("/Contents")] = reference
        raw_payloads[reference.idnum] = payload
        stream_numbers.append(reference.idnum)
        if number == 2 and explicit_name in ("", "/Identity"):
            identity_streams.add(reference.idnum)

    writer.encrypt(user_password, owner_password="synthetic-owner", algorithm=algorithm)
    encryption = writer._encryption
    assert encryption is not None and writer._encrypt_entry is not None
    permissions = int(writer._encrypt_entry["/P"])
    if permissions >= 2**31:
        writer._encrypt_entry[NameObject("/P")] = NumberObject(permissions - 2**32)
    if global_identity:
        encryption.StmF = "/Identity"
        writer._encrypt_entry[NameObject("/StmF")] = NameObject("/Identity")
    assert str(writer._encrypt_entry["/StrF"]) == "/StdCF"
    ordinary_encrypt = encryption.encrypt_object
    dictionary_checks = []

    def encrypt_object(obj, object_number, generation):
        encrypted = ordinary_encrypt(obj, object_number, generation)
        if object_number in raw_payloads:
            string_cipher = encrypted["/FixtureLabel"].original_bytes
            assert string_cipher != TextStringObject(LABEL).get_encoded_bytes()
            native_filter = encryption._make_crypt_filter(object_number, generation)
            assert native_filter.str_crypt.decrypt(string_cipher) == TextStringObject(LABEL).get_encoded_bytes()
            dictionary_checks.append(object_number)
        if object_number in identity_streams:
            # The explicit Identity crypt filter replaces only the stream cipher.
            # The object returned above already has its dictionary strings encrypted.
            encrypted._data = obj._data
        return encrypted

    encryption.encrypt_object = encrypt_object
    output = io.BytesIO()
    writer.write(output)
    content = output.getvalue()
    assert set(dictionary_checks) == set(stream_numbers)
    emitted = {number: _raw_stream(content, number) for number in stream_numbers}
    for number, payload in raw_payloads.items():
        if global_identity or number in identity_streams:
            assert emitted[number] == payload
        else:
            assert emitted[number] != payload and payload not in emitted[number]
    assert LABEL.encode("ascii") not in content
    return {
        "content": content,
        "expected_texts": expected,
        "stream_numbers": stream_numbers,
        "dictionary_strings_verified_encrypted": dictionary_checks,
        "implicit_stream_really_encrypted": not global_identity,
        "explicit_stream_data_plain": bool(identity_streams),
        "payload_bytes": {number: len(payload) for number, payload in raw_payloads.items()},
    }
