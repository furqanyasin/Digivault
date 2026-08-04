"""Email authentication checks — SPF, DKIM and DMARC."""


from apps.domains.services import check_email_auth


def test_all_three_present():
    """A fully configured domain: SPF on the apex, DMARC at _dmarc, DKIM on a
    probed selector."""
    records = {
        "acme.test": ["v=spf1 include:_spf.google.com ~all"],
        "_dmarc.acme.test": ["v=DMARC1; p=reject; rua=mailto:d@acme.test"],
        "google._domainkey.acme.test": ["v=DKIM1; k=rsa; p=MIGf..."],
    }
    out = check_email_auth("acme.test", resolve_txt=lambda n: records.get(n) or (_ for _ in ()).throw(Exception("NXDOMAIN")))
    assert out["spf_status"] == "pass"
    assert out["dmarc_status"] == "pass"
    assert out["dkim_status"] == "pass"
    assert out["dkim_selector"] == "google"
    assert "include:_spf.google.com" in out["spf_record"]


def test_nothing_configured():
    """No records at all reads as missing, not error — the lookups succeeded."""
    out = check_email_auth("bare.test", resolve_txt=lambda n: [])
    assert out["spf_status"] == "missing"
    assert out["dmarc_status"] == "missing"
    assert out["dkim_status"] == "missing"


def test_lookup_failure_is_error_not_missing():
    """A resolver failure must be distinguishable from a domain that genuinely
    has no policy — otherwise a DNS outage looks like a misconfiguration."""
    def boom(name):
        raise RuntimeError("resolver down")
    out = check_email_auth("broken.test", resolve_txt=boom)
    assert out["spf_status"] == "error"
    assert out["dmarc_status"] == "error"
    # DKIM has no error state: every selector legitimately 404s, so absence
    # across all of them is indistinguishable from a failure.
    assert out["dkim_status"] == "missing"


def test_chunked_txt_is_joined():
    """Long policies arrive split into 255-byte chunks and must be rejoined, or a
    DMARC record reads as truncated and fails the prefix check."""
    long_dmarc = "v=DMARC1; p=quarantine; " + "rua=mailto:a@b.test; " * 20
    records = {"_dmarc.x.test": [long_dmarc]}
    out = check_email_auth("x.test", resolve_txt=lambda n: records.get(n, []))
    assert out["dmarc_status"] == "pass"
    assert out["dmarc_record"].startswith("v=DMARC1")


def test_ignores_unrelated_txt_records():
    """Domains carry verification TXT records for all sorts of services; only a
    v=spf1 value counts as SPF."""
    records = {"y.test": ["google-site-verification=abc", "MS=ms12345"]}
    out = check_email_auth("y.test", resolve_txt=lambda n: records.get(n, []))
    assert out["spf_status"] == "missing"
