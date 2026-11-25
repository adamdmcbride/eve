import unittest
from email.message import Message

import eve_http_headers


class HTTPHeaderContractTests(unittest.TestCase):
    def test_header_values_preserve_duplicates_and_case_insensitive_mappings(self):
        message = Message()
        message.add_header("Origin", "http://localhost:3000")
        message.add_header("Origin", "http://127.0.0.1:3000")

        self.assertEqual(
            ["http://localhost:3000", "http://127.0.0.1:3000"],
            eve_http_headers.header_values(message, "Origin"),
        )
        self.assertEqual(
            ["application/json"],
            eve_http_headers.header_values(
                {"content-type": "application/json"},
                "Content-Type",
            ),
        )

    def test_optional_header_normalizes_only_outer_http_whitespace(self):
        self.assertEqual(
            "same-origin",
            eve_http_headers.optional_ascii_header(
                {"Sec-Fetch-Site": " \tsame-origin\t "},
                "Sec-Fetch-Site",
                maximum_characters=32,
            ),
        )
        self.assertEqual(
            "",
            eve_http_headers.optional_ascii_header({}, "Origin"),
        )

    def test_duplicate_consumed_headers_are_rejected(self):
        message = Message()
        message.add_header("Origin", "http://localhost:3000")
        message.add_header("Origin", "http://localhost:3000")

        with self.assertRaisesRegex(
            eve_http_headers.RequestHeaderError,
            "Multiple Origin",
        ):
            eve_http_headers.optional_ascii_header(message, "Origin")

    def test_ascii_field_rejects_controls_unicode_oversize_and_non_text(self):
        cases = (
            "line\nbreak",
            "value\x7f",
            "éve",
            "x" * 9,
            123,
        )
        for value in cases:
            with self.subTest(value=repr(value)):
                with self.assertRaises(eve_http_headers.RequestHeaderError):
                    eve_http_headers.require_ascii_field_value(
                        value,
                        label="X-Eve-Test",
                        maximum_characters=8,
                    )

    def test_programmer_contract_rejects_invalid_names_and_limits(self):
        with self.assertRaisesRegex(ValueError, "HTTP token"):
            eve_http_headers.header_values({}, "Bad Header")
        with self.assertRaises(TypeError):
            eve_http_headers.optional_ascii_header(
                {},
                "Origin",
                maximum_characters=True,
            )
        with self.assertRaisesRegex(ValueError, "positive"):
            eve_http_headers.require_ascii_field_value(
                "value",
                label="field",
                maximum_characters=0,
            )


if __name__ == "__main__":
    unittest.main()
