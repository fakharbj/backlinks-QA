"""Domain-metrics parsers — pure logic (no network)."""

from datetime import date

from app.integrations.domain_metrics import parse_moz, parse_rdap_created, parse_semrush


def test_rdap_registration_date():
    payload = {
        "events": [
            {"eventAction": "last changed", "eventDate": "2024-01-02T00:00:00Z"},
            {"eventAction": "registration", "eventDate": "1999-08-17T04:00:00Z"},
        ]
    }
    assert parse_rdap_created(payload) == date(1999, 8, 17)


def test_rdap_missing_returns_none():
    assert parse_rdap_created({"events": [{"eventAction": "expiration", "eventDate": "2030-01-01"}]}) is None
    assert parse_rdap_created({}) is None


def test_moz_shapes():
    assert parse_moz({"da": 55, "pa": 40, "spam_score": 2}) == {"da": 55, "pa": 40, "spam_score": 2}
    assert parse_moz({"domainAuthority": "33"}) == {"da": 33}
    assert parse_moz({}) == {}


def test_semrush_shapes():
    assert parse_semrush({"authority_score": 48, "organic_traffic": 12000, "organic_keywords": 800}) == {
        "semrush_as": 48,
        "semrush_traffic": 12000,
        "semrush_keywords": 800,
    }
    assert parse_semrush({"data": {"as": 10}}) == {"semrush_as": 10}
    assert parse_semrush({}) == {}
