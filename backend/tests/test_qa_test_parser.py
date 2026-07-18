"""Temp QA lab parser — the three real trial-task sheet layouts the owner
pasted must all parse correctly: headered, label-first, and section-header."""

from __future__ import annotations

from app.services.qa_test_service import parse_test_submission

BRIEF = (
    "Off-Page SEO Trial Task\t\t\t\n"
    "Create 3 Article Submission + 2 Business Listing + 2 Web 2.0 + 2 Forum Discussion Backlinks for Service Page: https://limo.black/service/airport-limo-service/\t\t\t\n"
    "Publish 1 Qoura Question & Answer to Relevent 2 Questions in Your Own Words for Service Page: https://limo.black/service/airport-limo-service/\t\t\t\n"
    "Obtain 1 relevant competitor for: https://limo.black/\t\t\t\n"
    "Note: Mentioned Backlinks DA, and Spam Score as well. Also put all data here in the Sheet.\t\t\t\n"
)


def test_format_a_header_row_with_competitor_section():
    text = BRIEF + (
        "\t\t\t\n"
        "URL\tLink Type\tDA\tStatus\tSpam Score\tAnchor Text\tTarget Page\t\t\n"
        "https://medium.com/@mollgixk/10-reasons\tArticle Submission\t95\tLive\t1%\tairport limo service\thttps://limo.black/service/airport-limo-service/\t\t\n"
        "https://articlebiz.com/checkArticle/x\tArticle Submission\t46\tPending\t5%\tairport transfer service\thttps://limo.black/service/airport-limo-service/\t\t\n"
        "\t\t\t\t\t\thttps://www.yelp.com/user_details?userid=X\t\t\n"  # stray row: URL only in Target Page col
        "https://www.yelp.com/user_details?userid=X\tBusiness listing\t\tPending\t\t\t\t\t\n"
        "https://limoblack.collectblogs.com/86890413/post\tweb2.1\t\tLive\t\t\t\t\t\n"
        "https://www.goodreads.com/review/show/8775832005\tforum \t\tsignin req\t\t\t\t\t\n"
        "https://qr.ae/pFMyiu\tAnswer Quora\t93\tLive\t10%\t\t\t\t\n"
        "\t\t\t\n"
        "Competiotor\t\t\t\n"
        "bozemancarservice.com\t\t\t\n"
        "montanachauffeur.com\t\t\t\n"
    )
    r = parse_test_submission(text)
    links = r["links"]
    backlinks = [x for x in links if not x["is_competitor"]]
    comps = [x for x in links if x["is_competitor"]]

    # Brief lines never become links; the stray target-only row is skipped.
    assert len(backlinks) == 6
    med = backlinks[0]
    assert med["source_url"].startswith("https://medium.com/")
    assert med["link_type"] == "Article"
    assert med["claimed_da"] == 95 and med["claimed_spam"] == 1
    assert med["anchor_text"] == "airport limo service"
    assert med["target_url"] == "https://limo.black/service/airport-limo-service/"
    yelp = next(x for x in backlinks if "yelp.com" in x["source_url"])
    assert yelp["link_type"] == "Business Listing"
    web = next(x for x in backlinks if "collectblogs" in x["source_url"])
    assert web["link_type"] == "Web 2.0"          # "web2.1" folds into Web 2.0
    quora = next(x for x in backlinks if "qr.ae" in x["source_url"])
    assert quora["link_type"] == "Quora" and quora["claimed_da"] == 93 and quora["claimed_spam"] == 10

    # The misspelled "Competiotor" section still collects the bare domains.
    assert {c["source_url"] for c in comps} == {
        "https://bozemancarservice.com/", "https://montanachauffeur.com/",
    }
    # The brief's most-mentioned URL becomes the inferred target.
    assert r["meta"]["inferred_target"] == "https://limo.black/service/airport-limo-service/"


def test_format_b_label_first_rows_with_inline_competitor():
    text = (
        "Off-Page SEO Trial Task\t\t\t\n"
        "Create 3 Article Submission backlinks for Service Page: https://limo.black/service/airport-limo-service/\t\t\t\n"
        "Obtain 1 relevant competitor for: https://limo.black/\tmontanachauffeur.com\t\t\n"
        "\t\t\t\n"
        "business directories \thttps://www.expressbusinessdirectory.com/directory/limo-black/\t 47 da \t1 spam score \n"
        "\t\t\t\n"
        "article submission \thttps://medium.com/@mollgixk/why-choosing\t95 da \t1 spam score \n"
        "quora questions \thttps://www.quora.com/unanswered/What-should-I-look\t \t\n"
        "\thttps://www.quora.com/What-are-the-top-benefits/answer/Limo-Blacjk?prompt_topic_bio=1\t \t\n"
    )
    r = parse_test_submission(text)
    links = r["links"]
    comps = [x for x in links if x["is_competitor"]]
    backlinks = [x for x in links if not x["is_competitor"]]

    # The inline competitor domain next to the brief sentence is captured.
    assert [c["source_url"] for c in comps] == ["https://montanachauffeur.com/"]

    assert len(backlinks) == 4
    bd = backlinks[0]
    assert bd["link_type"] == "Business Listing"
    assert bd["claimed_da"] == 47 and bd["claimed_spam"] == 1
    art = backlinks[1]
    assert art["link_type"] == "Article" and art["claimed_da"] == 95
    q1, q2 = backlinks[2], backlinks[3]
    assert q1["link_type"] == "Quora"
    # The unlabeled continuation row inherits the quora section.
    assert q2["link_type"] == "Quora"
    assert "answer/Limo-Blacjk" in q2["source_url"]


def test_format_c_section_headers_with_positional_metrics():
    text = BRIEF + (
        "\t\t\t\n"
        "Article Submission\tDA\tPA\tSS\n"
        "https://medium.com/@mollgixk/airport-limo\t95\t48\t1%\n"
        "https://wakelet.com/wake/G2cAABpZq4cc7WXf9WDwg\t74\t41\t1%\n"
        "Business Listing\t\t\t\n"
        "https://vimeo.com/imoblack\t95\t50\t3%\n"
        "Web 2.0 \t\t\t\n"
        "https://penzu.com/p/dca2cd81aab876fc\t77\t39\t6%\n"
        " Forum\t\t\t\n"
        "https://hackmd.openmole.org/s/XCmb7KJek\t44\t32\t4%\n"
        "Qoura\t\t\t\n"
        "https://qr.ae/pFMMVb\t\t\t\n"
    )
    r = parse_test_submission(text)
    links = [x for x in r["links"] if not x["is_competitor"]]
    assert len(links) == 6
    med = links[0]
    # Positional metrics: DA=95, PA skipped (no column), SS=1.
    assert med["link_type"] == "Article" and med["claimed_da"] == 95 and med["claimed_spam"] == 1
    vimeo = next(x for x in links if "vimeo" in x["source_url"])
    assert vimeo["link_type"] == "Business Listing" and vimeo["claimed_da"] == 95 and vimeo["claimed_spam"] == 3
    penzu = next(x for x in links if "penzu" in x["source_url"])
    assert penzu["link_type"] == "Web 2.0" and penzu["claimed_da"] == 77 and penzu["claimed_spam"] == 6
    hack = next(x for x in links if "hackmd" in x["source_url"])
    assert hack["link_type"] == "Forum"
    quora = next(x for x in links if "qr.ae" in x["source_url"])
    assert quora["link_type"] == "Quora"          # "Qoura" misspelling folds in


def test_plain_urls_and_target_domain_awareness():
    r = parse_test_submission(
        "https://one.example.com/a\nhttps://limo.black/service/x\nhttps://two.example.com/b\n",
        default_target="https://limo.black/",
    )
    links = r["links"]
    # The target-domain URL is never a backlink row.
    assert [x["source_url"] for x in links] == [
        "https://one.example.com/a", "https://two.example.com/b",
    ]
    assert r["meta"]["ignored_lines"] == 1


import uuid as _uuid

import pytest

pytestmark = pytest.mark.integration


def _register(client) -> dict:
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"qa+{_uuid.uuid4().hex[:8]}@linksentinel.test",
            "password": "Password-12345",
            "full_name": "Admin", "workspace_name": "QaLab Ws",
        },
    )
    assert reg.status_code == 201, reg.text
    return {"Authorization": f"Bearer {reg.json()['access_token']}"}


def test_lab_rows_are_manually_correctable(live_stack):
    """Owner rule: every parse is fixable by hand — add, edit (verdict resets
    to pending), flip competitor, delete."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        h = _register(client)
        made = client.post(
            "/api/v1/qa-tests",
            json={
                "candidate_name": "Trial Person",
                "links_text": "https://one.example.com/a\nhttps://two.example.com/b\tcompetitor",
                "default_target": "https://limo.black/",
                "run_now": False,
            },
            headers=h,
        )
        assert made.status_code == 201, made.text
        d = made.json()
        bid = d["id"]
        links = d["links"]
        assert len(links) == 2
        comp = next(x for x in links if x["is_competitor"])
        real = next(x for x in links if not x["is_competitor"])

        # Add a row the parser "missed".
        added = client.post(
            f"/api/v1/qa-tests/{bid}/links",
            json={"source_url": "https://three.example.com/c", "link_type": "Forum", "claimed_da": 40},
            headers=h,
        )
        assert added.status_code == 201, added.text
        assert len(added.json()["links"]) == 3

        # Edit: change the type + claims — state stays/reverts to pending.
        edited = client.patch(
            f"/api/v1/qa-tests/{bid}/links/{real['id']}",
            json={"link_type": "Web 2.0", "claimed_da": 90, "anchor_text": "limo"},
            headers=h,
        )
        assert edited.status_code == 200, edited.text
        row = next(x for x in edited.json()["links"] if x["id"] == real["id"])
        assert row["link_type"] == "Web 2.0" and row["claimed_da"] == 90
        assert row["state"] == "pending"

        # Flip the mis-parsed competitor into a real backlink.
        flipped = client.patch(
            f"/api/v1/qa-tests/{bid}/links/{comp['id']}",
            json={"is_competitor": False},
            headers=h,
        )
        row = next(x for x in flipped.json()["links"] if x["id"] == comp["id"])
        assert row["is_competitor"] is False and row["state"] == "pending"

        # Delete a row.
        gone = client.delete(f"/api/v1/qa-tests/{bid}/links/{real['id']}", headers=h)
        assert gone.status_code == 200
        assert all(x["id"] != real["id"] for x in gone.json()["links"])

        # A bad edit is rejected.
        bad = client.patch(
            f"/api/v1/qa-tests/{bid}/links/{comp['id']}",
            json={"source_url": "not a url"},
            headers=h,
        )
        assert bad.status_code in (400, 422)
