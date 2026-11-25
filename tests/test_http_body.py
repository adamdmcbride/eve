from __future__ import annotations

import io
import unittest

import eve_http_body


class RepeatedHeaders:
    def __init__(self, values: dict[str, list[str]]) -> None:
        self.values = values

    def get_all(self, name: str):
        return self.values.get(name)


class FragmentedStream:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = list(chunks)

    def read(self, maximum: int) -> bytes:
        if not self.chunks:
            return b""
        chunk = self.chunks.pop(0)
        if len(chunk) <= maximum:
            return chunk
        self.chunks.insert(0, chunk[maximum:])
        return chunk[:maximum]


class FailingReadStream:
    def read(self, _maximum: int) -> bytes:
        raise AssertionError("a rejected declaration must not read the body")


class BrokenReadStream:
    def read(self, _maximum: int) -> bytes:
        raise TimeoutError("simulated stalled body")


class HTTPRequestBodyTests(unittest.TestCase):
    def test_reads_exact_declared_body_with_case_insensitive_mapping_header(self):
        body = eve_http_body.read_bounded_request_body(
            io.BytesIO(b'{"ok":true}'),
            {"content-length": "11"},
            maximum_bytes=32,
        )

        self.assertEqual(b'{"ok":true}', body)

    def test_fragmented_stream_is_read_until_exact_declared_length(self):
        body = eve_http_body.read_bounded_request_body(
            FragmentedStream([b"ab", b"c", b"def"]),
            {"Content-Length": "6"},
            maximum_bytes=6,
        )

        self.assertEqual(b"abcdef", body)

    def test_incomplete_stream_is_not_accepted_as_a_complete_request(self):
        with self.assertRaisesRegex(
            eve_http_body.IncompleteRequestBody,
            "4 of 5 declared bytes",
        ):
            eve_http_body.read_bounded_request_body(
                FragmentedStream([b"12", b"34"]),
                {"Content-Length": "5"},
                maximum_bytes=5,
            )

        with self.assertRaisesRegex(
            eve_http_body.IncompleteRequestBody,
            "could not be read completely",
        ):
            eve_http_body.read_bounded_request_body(
                BrokenReadStream(),
                {"Content-Length": "1"},
                maximum_bytes=1,
            )

    def test_oversized_declaration_fails_before_reading(self):
        with self.assertRaisesRegex(eve_http_body.RequestBodyTooLarge, "too large"):
            eve_http_body.read_bounded_request_body(
                FailingReadStream(),
                {"Content-Length": "9"},
                maximum_bytes=8,
            )

        with self.assertRaises(eve_http_body.RequestBodyTooLarge):
            eve_http_body.declared_request_length(
                {"Content-Length": "9" * 100},
                maximum_bytes=8,
            )

    def test_missing_duplicate_and_transfer_encoded_framing_fail_closed(self):
        with self.assertRaisesRegex(eve_http_body.RequestBodyFramingError, "required"):
            eve_http_body.declared_request_length({}, maximum_bytes=8)

        with self.assertRaisesRegex(eve_http_body.RequestBodyFramingError, "Multiple"):
            eve_http_body.declared_request_length(
                RepeatedHeaders({"Content-Length": ["2", "2"]}),
                maximum_bytes=8,
            )

        for value in ("chunked", ""):
            with self.subTest(transfer_encoding=value):
                with self.assertRaisesRegex(
                    eve_http_body.RequestBodyFramingError,
                    "Transfer-Encoding",
                ):
                    eve_http_body.declared_request_length(
                        {"Content-Length": "2", "Transfer-Encoding": value},
                        maximum_bytes=8,
                    )

    def test_content_length_uses_ascii_decimal_syntax_only(self):
        for value in ("-1", "+1", "1, 1", "١", ""):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    eve_http_body.RequestBodyFramingError,
                    "Invalid Content-Length",
                ):
                    eve_http_body.declared_request_length(
                        {"Content-Length": value},
                        maximum_bytes=8,
                    )

    def test_empty_body_must_be_explicitly_admitted(self):
        with self.assertRaisesRegex(eve_http_body.RequestBodyError, "empty"):
            eve_http_body.read_bounded_request_body(
                io.BytesIO(),
                {"Content-Length": "0"},
                maximum_bytes=8,
            )

        self.assertEqual(
            b"",
            eve_http_body.read_bounded_request_body(
                io.BytesIO(),
                {"Content-Length": "0"},
                maximum_bytes=8,
                allow_empty=True,
            ),
        )

    def test_invalid_limit_is_a_configuration_error(self):
        for value in (-1, "not-a-number"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "maximum_bytes"):
                    eve_http_body.declared_request_length(
                        {"Content-Length": "1"},
                        maximum_bytes=value,  # type: ignore[arg-type]
                    )


if __name__ == "__main__":
    unittest.main()
