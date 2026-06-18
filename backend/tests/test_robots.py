"""robots.txt parsing & evaluation tests (RBT-*)."""

from app.crawler.robots import RobotsTxt

SAMPLE = """
User-agent: *
Disallow: /
Allow: /public
Crawl-delay: 2
Sitemap: https://acme.test/sitemap.xml

User-agent: Googlebot
Disallow: /secret
Allow: /
"""


def test_most_specific_group_wins():
    robots = RobotsTxt.parse(SAMPLE)
    # Googlebot uses only its own (most specific) group.
    assert robots.allowed("/anything", "Googlebot") is True
    assert robots.allowed("/secret/page", "Googlebot") is False


def test_star_group_for_other_agents():
    robots = RobotsTxt.parse(SAMPLE)
    assert robots.allowed("/public/post", "Bingbot") is True
    assert robots.allowed("/private", "Bingbot") is False


def test_longest_match_precedence():
    robots = RobotsTxt.parse("User-agent: *\nDisallow: /a\nAllow: /a/b")
    assert robots.allowed("/a/b/c", "Googlebot") is True   # Allow /a/b is longer
    assert robots.allowed("/a/x", "Googlebot") is False     # only Disallow /a matches


def test_wildcard_and_end_anchor():
    robots = RobotsTxt.parse("User-agent: *\nDisallow: /*.pdf$")
    assert robots.allowed("/files/report.pdf", "Googlebot") is False
    assert robots.allowed("/files/report.pdfx", "Googlebot") is True


def test_crawl_delay_and_sitemaps():
    robots = RobotsTxt.parse(SAMPLE)
    assert robots.crawl_delay("Bingbot") == 2.0
    assert "https://acme.test/sitemap.xml" in robots.sitemaps


def test_empty_robots_allows_all():
    robots = RobotsTxt.parse("")
    assert robots.empty is True
    assert robots.allowed("/anything", "Googlebot") is True


def test_disallow_blank_means_allow_all():
    robots = RobotsTxt.parse("User-agent: *\nDisallow:")
    assert robots.allowed("/anything", "Googlebot") is True
