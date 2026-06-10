"""SSRF guard — blocks internal/non-public fetch targets."""

import pytest

from apps.common.ssrf import BlockedURLError, assert_public_url


class TestAssertPublicUrl:
    @pytest.mark.parametrize("url", [
        "http://127.0.0.1/admin",
        "http://localhost:8000/api/",
        "http://0.0.0.0/",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://10.0.0.5/internal",
        "http://192.168.1.1/",
        "http://172.16.0.1/",
        "http://[::1]/",                               # IPv6 loopback
    ])
    def test_internal_targets_blocked(self, url):
        with pytest.raises(BlockedURLError):
            assert_public_url(url)

    @pytest.mark.parametrize("url", [
        "ftp://example.com/file",
        "file:///etc/passwd",
        "gopher://127.0.0.1:6379/",
        "redis://127.0.0.1:6379/",
    ])
    def test_non_http_schemes_blocked(self, url):
        with pytest.raises(BlockedURLError):
            assert_public_url(url)

    def test_no_host_blocked(self):
        with pytest.raises(BlockedURLError):
            assert_public_url("http:///path")

    def test_unresolvable_host_blocked(self):
        with pytest.raises(BlockedURLError):
            assert_public_url("https://nonexistent.invalid.tld.example/")

    def test_public_host_allowed(self):
        # google.com resolves to public IPs — should not raise.
        assert_public_url("https://www.google.com/") is None
