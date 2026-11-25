import unittest

import eve_http_json


class HTTPJSONFieldTests(unittest.TestCase):
    def test_text_is_bounded_before_whitespace_is_trimmed(self):
        self.assertEqual(
            "x",
            eve_http_json.require_text_value(
                " x ",
                label="field",
                maximum_characters=3,
            ),
        )
        with self.assertRaisesRegex(ValueError, "too long"):
            eve_http_json.require_text_value(
                " x  ",
                label="field",
                maximum_characters=3,
            )

    def test_text_requires_the_declared_type_and_visible_content(self):
        with self.assertRaisesRegex(ValueError, "must be text"):
            eve_http_json.require_text_value(17, label="field")
        with self.assertRaisesRegex(ValueError, "is required"):
            eve_http_json.require_text_value(" \t\n", label="field", required=True, multiline=True)

    def test_multiline_text_allows_line_breaks_but_not_hidden_controls(self):
        self.assertEqual(
            "first\r\n\tsecond",
            eve_http_json.require_text_value(
                "first\r\n\tsecond",
                label="body",
                multiline=True,
            ),
        )
        with self.assertRaisesRegex(ValueError, "printable"):
            eve_http_json.require_text_value("first\nsecond", label="subject")
        with self.assertRaisesRegex(ValueError, "printable"):
            eve_http_json.require_text_value("first\x00second", label="body", multiline=True)

    def test_text_field_requires_an_object_and_uses_a_typed_default(self):
        self.assertEqual("fallback", eve_http_json.text_field({}, "name", default="fallback"))
        with self.assertRaisesRegex(ValueError, "JSON object"):
            eve_http_json.text_field([], "name")
        with self.assertRaisesRegex(ValueError, "must be text"):
            eve_http_json.text_field({}, "name", default=7)  # type: ignore[arg-type]

    def test_boolean_field_accepts_only_json_booleans(self):
        self.assertTrue(eve_http_json.boolean_field({}, "stream", default=True))
        self.assertFalse(eve_http_json.boolean_field({"stream": False}, "stream", default=True))
        for value in ("false", 0, 1, None):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "JSON Boolean"):
                eve_http_json.boolean_field({"stream": value}, "stream", default=True)

    def test_object_lists_have_finite_count_and_object_elements(self):
        items = [{"id": "one"}, {"id": "two"}]
        self.assertEqual(
            items,
            eve_http_json.object_list_value(items, label="attachments", maximum_items=2),
        )
        with self.assertRaisesRegex(ValueError, "at most 1"):
            eve_http_json.object_list_value(items, label="attachments", maximum_items=1)
        with self.assertRaisesRegex(ValueError, r"attachments\[1\] must be an object"):
            eve_http_json.object_list_value([{}, "bad"], label="attachments")
        with self.assertRaisesRegex(ValueError, "must be an array"):
            eve_http_json.object_list_field({"attachments": {}}, "attachments")

    def test_string_lists_bound_count_type_and_item_length(self):
        self.assertEqual(
            ["one", "two"],
            eve_http_json.string_list_value(
                "one  two",
                label="tags",
                maximum_items=2,
                allow_space_separated_string=True,
            ),
        )
        with self.assertRaisesRegex(ValueError, "at most 1"):
            eve_http_json.string_list_value(["one", "two"], label="tags", maximum_items=1)
        with self.assertRaisesRegex(ValueError, r"tags\[0\] must be text"):
            eve_http_json.string_list_value([1], label="tags")
        with self.assertRaisesRegex(ValueError, "too long"):
            eve_http_json.string_list_value(
                ["long"],
                label="tags",
                maximum_item_characters=3,
            )
        with self.assertRaisesRegex(ValueError, "must be an array"):
            eve_http_json.string_list_value("one two", label="tags")
        with self.assertRaisesRegex(ValueError, "printable"):
            eve_http_json.string_list_value(
                "one\vtwo",
                label="tags",
                allow_space_separated_string=True,
            )
        with self.assertRaisesRegex(ValueError, "too long"):
            eve_http_json.string_list_value(
                " " * 130,
                label="tags",
                maximum_items=2,
                maximum_item_characters=64,
                allow_space_separated_string=True,
            )

    def test_programmer_limits_fail_closed(self):
        with self.assertRaisesRegex(TypeError, "must be an integer"):
            eve_http_json.require_text_value("x", label="field", maximum_characters=True)
        with self.assertRaisesRegex(ValueError, "must be positive"):
            eve_http_json.object_list_value([], label="items", maximum_items=0)
        with self.assertRaisesRegex(TypeError, "default must be a Boolean"):
            eve_http_json.boolean_field({}, "flag", default=1)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
