"""Tests for the career-page parser.

Run:  python -m pytest tests/ -v
"""

from pathlib import Path

from src.parser import html_to_text, parse_ats_json, parse_html_jobs

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample_careers.html"


def test_parse_html_finds_jobs():
    html = FIXTURE.read_text(encoding="utf-8")
    jobs = parse_html_jobs(html, "https://example.com/careers/", "Example Co")
    titles = [j.title for j in jobs]
    assert any("Data Analyst" in t for t in titles)
    assert any("Web Scraper" in t for t in titles)
    assert len(jobs) >= 2


def test_parse_html_ignores_nav_and_footer():
    html = FIXTURE.read_text(encoding="utf-8")
    jobs = parse_html_jobs(html, "https://example.com/careers/", "Example Co")
    combined = " ".join(j.title for j in jobs).lower()
    assert "about the company" not in combined
    assert "privacy" not in combined


def test_parse_ats_json_bare_list():
    raw = (
        '[{"title": "Junior Data Analyst", "url": "https://x.com/j/1", '
        '"location": "Lahore"}]'
    )
    jobs = parse_ats_json(raw, "https://x.com/board", "Co")
    assert jobs
    assert jobs[0].title == "Junior Data Analyst"
    assert jobs[0].url == "https://x.com/j/1"


def test_parse_ats_json_envelope():
    raw = '{"data": [{"title": "ETL Developer", "url": "https://x.com/j/2"}]}'
    jobs = parse_ats_json(raw, "https://x.com/board", "Co")
    assert jobs and jobs[0].title == "ETL Developer"


# ---------------------------------------------------------------------------
# regression: title blobs + tag-split experience (real reported bugs)
# ---------------------------------------------------------------------------
def test_html_to_text_joins_split_label_and_value():
    """Tag-split label/value plain text mein judna chahiye (Arpatech bug).

    Page mein tha: <strong>Experience: </strong></span><span>4-6</span>
    """
    html = (
        '<div><span class="label"><strong>Experience: </strong></span>'
        '<span class="term">4-6</span></div>'
    )
    assert "Experience: 4-6" in html_to_text(html)


def test_html_to_text_strips_script_and_style():
    html = "<style>.a{color:red}</style><p>Hello</p><script>var x=1;</script>"
    text = html_to_text(html)
    assert "Hello" in text
    assert "color:red" not in text
    assert "var x" not in text


def test_parse_html_rejects_container_text_blob():
    """Poora listing text kabhi title nahi banana chahiye (Weproms bug)."""
    blob = (
        "Full-time / Contract Marketing Data Analyst Analyze channel "
        "performance, conversion quality, dashboards, attribution, and "
        "growth opportunities. Remote Salary: Open View role"
    )
    html = f'<div><a href="/careers/marketing-data-analyst/">{blob}</a></div>'
    assert parse_html_jobs(html, "https://example.com/careers/", "Co") == []


def test_parse_html_prefers_heading_over_generic_cta():
    """'View role' jaisa CTA title nahi — parent ka heading title bane."""
    html = (
        '<ul><li class="job"><h4>Data Analyst</h4>'
        "<p>Analyze data. Remote.</p>"
        '<a href="/jobs/data-analyst">View role</a></li></ul>'
    )
    jobs = parse_html_jobs(html, "https://example.com/careers/", "Co")
    titles = [j.title for j in jobs]
    assert "Data Analyst" in titles
    assert all(len(t.split()) <= 12 for t in titles)