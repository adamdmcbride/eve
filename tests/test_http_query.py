import unittest

import eve_http_query


class BoundedHTTPQueryTests(unittest.TestCase):
    def test_parse_decodes_utf8_and_keeps_a_read_only_value_map(self):
        query = eve_http_query.BoundedQuery.parse("status=ready&label=hello%20world")

        self.assertEqual("ready", query.value("status"))
        self.assertEqual("hello world", query.value("label"))
        with self.assertRaises(TypeError):
            query.values["status"] = ("changed",)  # type: ignore[index]

    def test_query_budget_field_budget_and_malformed_encoding_fail_closed(self):
        cases = (
            "x=" + ("a" * (eve_http_query.DEFAULT_MAX_QUERY_CHARACTERS + 1)),
            "&".join(f"field{index}=1" for index in range(33)),
            "broken-field",
            "value=%FF",
            "%00name=value",
        )

        for query_string in cases:
            with self.subTest(query_string=query_string[:80]):
                with self.assertRaises(ValueError):
                    eve_http_query.BoundedQuery.parse(query_string)

    def test_single_value_accessor_rejects_duplicates_blank_controls_and_length(self):
        duplicate = eve_http_query.BoundedQuery.parse("limit=1&limit=2")
        blank = eve_http_query.BoundedQuery.parse("status=")
        control = eve_http_query.BoundedQuery.parse("status=bad%00value")
        long_value = eve_http_query.BoundedQuery.parse("status=" + ("a" * 513))

        with self.assertRaisesRegex(ValueError, "at most once"):
            duplicate.value("limit")
        with self.assertRaisesRegex(ValueError, "cannot be empty"):
            blank.value("status")
        with self.assertRaisesRegex(ValueError, "printable text"):
            control.value("status")
        with self.assertRaisesRegex(ValueError, "512"):
            long_value.value("status")

    def test_integer_accessor_is_ascii_decimal_and_range_bounded(self):
        self.assertEqual(
            20,
            eve_http_query.BoundedQuery.parse("").integer(
                "limit",
                default=20,
                minimum=1,
                maximum=500,
            ),
        )
        self.assertEqual(
            7,
            eve_http_query.BoundedQuery.parse("limit=007").integer(
                "limit",
                minimum=1,
                maximum=500,
            ),
        )

        for raw in ("-1", "+1", "1.0", "１", "0", "501", "9" * 30):
            with self.subTest(raw=raw):
                query = eve_http_query.BoundedQuery.parse(f"limit={raw}")
                with self.assertRaises(ValueError):
                    query.integer("limit", minimum=1, maximum=500)

    def test_boolean_accessor_has_one_explicit_vocabulary(self):
        for raw in ("1", "true", "YES", "on"):
            with self.subTest(raw=raw):
                self.assertTrue(
                    eve_http_query.BoundedQuery.parse(f"compact={raw}").boolean(
                        "compact",
                        default=False,
                    )
                )
        for raw in ("0", "false", "NO", "off"):
            with self.subTest(raw=raw):
                self.assertFalse(
                    eve_http_query.BoundedQuery.parse(f"compact={raw}").boolean(
                        "compact",
                        default=True,
                    )
                )
        with self.assertRaisesRegex(ValueError, "must be one of"):
            eve_http_query.BoundedQuery.parse("compact=maybe").boolean(
                "compact",
                default=False,
            )


if __name__ == "__main__":
    unittest.main()
