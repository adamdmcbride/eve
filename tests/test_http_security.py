import unittest

import eve_http_security


class AdvertisedEndpointSecurityTests(unittest.TestCase):
    def test_advertised_host_accepts_canonical_dns_and_ipv4_only(self):
        self.assertEqual(
            "eve-main.local",
            eve_http_security.canonical_advertised_host("EVE-MAIN.LOCAL"),
        )
        self.assertEqual(
            "192.168.10.4",
            eve_http_security.canonical_advertised_host("192.168.10.4"),
        )

        for value in (
            "",
            " eve-main.local",
            "eve-main.local ",
            "eve_main.local",
            "eve-main.local:8787",
            "eve-main.local/path",
            "eve-main.local;curl bad.example",
            "eve-main.local\r\nX-Eve: injected",
            "éve.local",
            "0.0.0.0",
            "999.999.999.999",
            "::1",
            "[::1]",
        ):
            with self.subTest(value=value):
                self.assertEqual("", eve_http_security.canonical_advertised_host(value))

    def test_advertised_host_resolution_never_uses_a_wildcard_bind(self):
        self.assertEqual(
            "eve-main.local",
            eve_http_security.advertised_host_for_bind(
                "0.0.0.0",
                "EVE-MAIN.LOCAL",
            ),
        )
        self.assertEqual(
            "localhost",
            eve_http_security.advertised_host_for_bind("0.0.0.0"),
        )
        self.assertEqual(
            "localhost",
            eve_http_security.advertised_host_for_bind("::1"),
        )
        with self.assertRaisesRegex(ValueError, "advertised_host"):
            eve_http_security.advertised_host_for_bind("127.0.0.1", "bad/host")

    def test_network_port_requires_one_bounded_ascii_decimal(self):
        self.assertEqual(1, eve_http_security.require_network_port("00001"))
        self.assertEqual(65_535, eve_http_security.require_network_port(65_535))

        for value in (
            "",
            "0",
            "65536",
            " 8787",
            "+8787",
            "8_787",
            "８７８７",
            True,
            8787.0,
        ):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "1 through 65535"):
                    eve_http_security.require_network_port(value)

    def test_http_authority_revalidates_both_components(self):
        self.assertEqual(
            "eve-main.local:8787",
            eve_http_security.http_authority("EVE-MAIN.LOCAL", "8787"),
        )
        with self.assertRaises(ValueError):
            eve_http_security.http_authority("eve.local/bad", 8787)


class HTTPMutationSecurityTests(unittest.TestCase):
    def test_only_canonical_http_loopback_origins_are_accepted(self):
        self.assertEqual(
            "http://localhost:3000",
            eve_http_security.canonical_loopback_origin("HTTP://LOCALHOST:3000"),
        )
        self.assertEqual(
            "http://[::1]:8787",
            eve_http_security.canonical_loopback_origin("http://[::1]:8787"),
        )
        for value in (
            "https://localhost:3000",
            "http://localhost:3000/path",
            "http://user@localhost:3000",
            "http://evil.example:3000",
            "null",
            "http://localhost:3000\r\nX-Eve: injected",
            "http://localhost:" + ("3" * 600),
        ):
            self.assertEqual("", eve_http_security.canonical_loopback_origin(value))

    def test_json_media_type_accepts_parameters_and_structured_suffixes(self):
        self.assertTrue(eve_http_security.is_json_media_type("application/json"))
        self.assertTrue(
            eve_http_security.is_json_media_type("Application/JSON; charset=utf-8")
        )
        self.assertTrue(eve_http_security.is_json_media_type("application/problem+json"))
        self.assertFalse(eve_http_security.is_json_media_type("text/plain"))
        self.assertFalse(eve_http_security.is_json_media_type("multipart/form-data"))
        self.assertFalse(eve_http_security.is_json_media_type(""))

    def test_no_origin_json_clients_remain_compatible(self):
        decision = eve_http_security.evaluate_json_mutation_request(
            origin="",
            sec_fetch_site="",
            content_type="application/json",
            server_port=8787,
        )

        self.assertTrue(decision.allowed)
        self.assertEqual("allowed", decision.reason)

    def test_same_origin_and_declared_loopback_frontend_are_allowed(self):
        same_origin = eve_http_security.evaluate_json_mutation_request(
            origin="http://localhost:8787",
            sec_fetch_site="same-origin",
            content_type="application/json; charset=utf-8",
            server_port=8787,
        )
        frontend = eve_http_security.evaluate_json_mutation_request(
            origin="http://127.0.0.1:3000",
            sec_fetch_site="same-site",
            content_type="application/json",
            server_port=8787,
            extra_origins={"http://127.0.0.1:3000", "http://localhost:3000"},
        )

        self.assertTrue(same_origin.allowed)
        self.assertTrue(frontend.allowed)

    def test_cross_site_fetch_metadata_fails_even_with_an_allowed_origin(self):
        decision = eve_http_security.evaluate_json_mutation_request(
            origin="http://localhost:8787",
            sec_fetch_site="cross-site",
            content_type="application/json",
            server_port=8787,
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(403, decision.status)
        self.assertEqual("cross_site_fetch", decision.reason)

    def test_foreign_origin_and_simple_content_type_fail_closed(self):
        foreign = eve_http_security.evaluate_json_mutation_request(
            origin="https://untrusted.example",
            sec_fetch_site="",
            content_type="application/json",
            server_port=8787,
        )
        simple = eve_http_security.evaluate_json_mutation_request(
            origin="",
            sec_fetch_site="",
            content_type="text/plain",
            server_port=8787,
        )

        self.assertFalse(foreign.allowed)
        self.assertEqual(403, foreign.status)
        self.assertEqual("untrusted_origin", foreign.reason)
        self.assertFalse(simple.allowed)
        self.assertEqual(415, simple.status)
        self.assertEqual("json_content_type_required", simple.reason)

    def test_external_origin_cannot_be_added_as_a_trusted_frontend(self):
        with self.assertRaisesRegex(ValueError, "loopback"):
            eve_http_security.trusted_mutation_origins(
                8787,
                {"https://app.example.com"},
            )

    def test_consumed_mutation_fields_are_bounded_and_printable(self):
        cases = (
            {"origin": "x" * 513, "sec_fetch_site": "", "content_type": "application/json"},
            {"origin": "", "sec_fetch_site": "same\norigin", "content_type": "application/json"},
            {"origin": "", "sec_fetch_site": "", "content_type": "application/json;" + ("x" * 260)},
        )
        for fields in cases:
            with self.subTest(fields=fields):
                decision = eve_http_security.evaluate_json_mutation_request(
                    **fields,
                    server_port=8787,
                )
                self.assertFalse(decision.allowed)
                self.assertEqual(400, decision.status)
                self.assertEqual("invalid_request_header", decision.reason)


if __name__ == "__main__":
    unittest.main()
