"""Main-domain input normalization — pure logic (no DB / no network)."""

from app.services.project_settings_service import normalize_domain_input


def test_bare_domain_kept():
    assert normalize_domain_input("acme.com") == "acme.com"


def test_uppercase_and_www_and_scheme_stripped():
    assert normalize_domain_input("HTTPS://WWW.Acme.com/page?utm_source=x") == "acme.com"


def test_subdomain_collapses_to_registrable():
    assert normalize_domain_input("blog.acme.co.uk") == "acme.co.uk"


def test_path_only_host_is_taken():
    assert normalize_domain_input("acme.com/clients/x") == "acme.com"


def test_invalid_inputs_return_none():
    assert normalize_domain_input("not a domain") is None
    assert normalize_domain_input("localhost") is None
    assert normalize_domain_input("") is None
