from __future__ import annotations

import unittest

import eve_http_path


class HTTPPathTests(unittest.TestCase):
    def test_request_path_is_bounded_ascii_with_strict_utf8_percent_encoding(self):
        self.assertEqual(
            "/api/thread/caf%C3%A9",
            eve_http_path.require_request_path("/api/thread/caf%C3%A9"),
        )

        invalid = (
            "api/thread/id",
            "/api/thread/%",
            "/api/thread/%2",
            "/api/thread/%GG",
            "/api/thread/%FF",
            "/api/thread/%00",
            "/api/thread/raw space",
            "/api/thread/\N{LATIN SMALL LETTER E WITH ACUTE}",
            "/" + ("a" * eve_http_path.DEFAULT_MAX_PATH_CHARACTERS),
        )
        for path in invalid:
            with self.subTest(path=path[:80]):
                with self.assertRaises(ValueError):
                    eve_http_path.require_request_path(path)

    def test_request_target_accepts_only_bounded_origin_form(self):
        target = eve_http_path.parse_request_target("/api/messages?id=one")
        self.assertEqual("/api/messages", target.path)
        self.assertEqual("id=one", target.query)

        invalid = (
            "http://eve.example/api/messages",
            "//eve.example/api/messages",
            "/api/messages#fragment",
            "*",
            "/api/raw space",
            "/" + ("a" * eve_http_path.DEFAULT_MAX_REQUEST_TARGET_CHARACTERS),
        )
        for value in invalid:
            with self.subTest(value=value[:80]):
                with self.assertRaises(ValueError):
                    eve_http_path.parse_request_target(value)

    def test_exact_route_match_decodes_one_opaque_segment(self):
        self.assertEqual(
            "thread/with space",
            eve_http_path.match_route_segment(
                "/api/thread/thread%2Fwith%20space",
                prefix="/api/thread/",
                label="Thread id",
            ),
        )
        self.assertEqual(
            "message-1",
            eve_http_path.match_route_segment(
                "/api/messages/message-1/mark",
                prefix="/api/messages/",
                suffix="/mark",
                label="Message id",
            ),
        )

    def test_extra_or_missing_path_segments_do_not_partially_match(self):
        cases = (
            "/api/messages/",
            "/api/messages/message-1/extra",
            "/api/messages/message-1/extra/mark",
            "/api/other/message-1",
        )
        for path in cases:
            with self.subTest(path=path):
                self.assertIsNone(
                    eve_http_path.match_route_segment(
                        path,
                        prefix="/api/messages/",
                        label="Message id",
                    )
                )

    def test_route_segment_rejects_ambiguous_or_unbounded_decoded_ids(self):
        cases = (
            "/api/thread/%2E",
            "/api/thread/%2E%2E",
            "/api/thread/%20leading",
            "/api/thread/trailing%20",
            "/api/thread/" + ("a" * 513),
        )
        for path in cases:
            with self.subTest(path=path[:80]):
                with self.assertRaises(ValueError):
                    eve_http_path.match_route_segment(
                        path,
                        prefix="/api/thread/",
                        label="Thread id",
                    )

    def test_route_builder_round_trips_reserved_and_unicode_id_data(self):
        value = "conversation/plan ? caf\N{LATIN SMALL LETTER E WITH ACUTE}"
        path = eve_http_path.build_route_path(
            prefix="/api/thread/",
            segment=value,
            label="Thread id",
        )

        self.assertEqual(
            "/api/thread/conversation%2Fplan%20%3F%20caf%C3%A9",
            path,
        )
        self.assertEqual(
            value,
            eve_http_path.match_route_segment(
                path,
                prefix="/api/thread/",
                label="Thread id",
            ),
        )

    def test_programmer_owned_route_shape_arguments_are_validated(self):
        with self.assertRaisesRegex(ValueError, "prefix"):
            eve_http_path.match_route_segment(
                "/api/thread/id",
                prefix="api/thread/",
            )
        with self.assertRaisesRegex(ValueError, "suffix"):
            eve_http_path.build_route_path(
                prefix="/api/messages/",
                segment="id",
                suffix="mark",
            )


if __name__ == "__main__":
    unittest.main()
