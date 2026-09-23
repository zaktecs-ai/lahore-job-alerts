"""Tests for the entry-level job matcher.

Run:  python -m pytest tests/ -v
"""

from src.matcher import JobMatcher, extract_experience
from src.models import Job


def make_matcher(overrides: dict | None = None) -> JobMatcher:
    from src.config import Settings

    settings = Settings.from_file()  # real config.yaml keywords lein
    for key, value in (overrides or {}).items():
        setattr(settings, key, value)
    return JobMatcher(settings)


def job(title: str, snippet: str = "", location: str = "Lahore, Pakistan") -> Job:
    return Job(
        company="Test Co",
        title=title,
        url="https://example.com/job/1",
        snippet=snippet,
        location=location,
    )


# ---------------------------------------------------------------------------
# experience extraction
# ---------------------------------------------------------------------------
def test_exp_range_dash():
    assert extract_experience("2-3 years") == (2, 3)


def test_exp_range_en_dash():
    assert extract_experience("Experience: 1-2 years") == (1, 2)


def test_exp_up_to():
    assert extract_experience("up to 2 years") == (0, 2)


def test_exp_less_than():
    assert extract_experience("less than 2 years") == (0, 2)


def test_exp_minimum():
    assert extract_experience("minimum 1 year experience") == (1, 1)


def test_exp_plus():
    assert extract_experience("3+ years") == (3, None)


def test_exp_none():
    assert extract_experience("no experience info given") == (None, None)


# ---------------------------------------------------------------------------
# matching outcomes
# ---------------------------------------------------------------------------
def test_junior_data_analyst_matches():
    m = make_matcher()
    assert m.match(job("Junior Data Analyst", "Fresh graduates welcome")).is_match


def test_data_engineer_2_3_boundary_accepted():
    # "2-3 years" ka START (2) range ke andar hai -> alert karo (user verify kare)
    m = make_matcher()
    assert m.match(job("Data Engineer", "We need 2-3 years experience")).is_match


def test_data_engineer_3_plus_rejected():
    m = make_matcher()
    assert not m.match(job("Data Engineer", "We need 3+ years experience")).is_match


def test_data_engineer_3_5_rejected():
    m = make_matcher()
    assert not m.match(job("Data Engineer", "3-5 years experience")).is_match


def test_data_engineer_1_2_accepted():
    m = make_matcher()
    assert m.match(job("Data Engineer", "1-2 years experience")).is_match


def test_web_scraper_title_unstated_matches():
    m = make_matcher()
    assert m.match(job("Web Scraper", "Build automation pipelines")).is_match


def test_senior_data_engineer_rejected():
    m = make_matcher()
    assert not m.match(job("Senior Data Engineer")).is_match


def test_lead_etl_rejected():
    m = make_matcher()
    assert not m.match(job("Lead ETL Developer")).is_match


def test_data_entry_operator_matches():
    m = make_matcher()
    assert m.match(job("Data Entry Operator", "0-1 years experience")).is_match


def test_experience_5_plus_rejected():
    m = make_matcher()
    r = m.match(job("Data Automation Engineer", snippet="5+ years of experience"))
    assert not r.is_match


def test_include_unstated_experience_false_blocks_plain_title():
    m = make_matcher({"include_unstated_experience": False})
    r = m.match(job("Web Scraper", "Join our Lahore team"))
    assert not r.is_match


# ---------------------------------------------------------------------------
# regression: experience bina "years" shabd ke + title blob (reported bugs)
# ---------------------------------------------------------------------------
def test_exp_labeled_range_without_years_word():
    """"Experience: 4-6" (bina 'years') bhi pakra jaye — Arpatech bug."""
    assert extract_experience("Experience: 4-6") == (4, 6)


def test_exp_labeled_range_with_category_after():
    assert extract_experience(
        "Experience: 4-6 Job Category: Software Engineering Job Type: Full Time"
    ) == (4, 6)


def test_exp_labeled_single_without_years_word():
    assert extract_experience("Experience Required: 3") == (3, 3)


def test_exp_labeled_months_are_not_years():
    """"Experience: 6 months" ko 6 years nahi samajhna (fresh-grad internship)."""
    lo, _hi = extract_experience("Experience: 6 months internship")
    assert lo is None or lo <= 2


def test_matcher_rejects_labeled_range_in_snippet():
    """Arpatech case: title 'Data Engineer' + snippet 'Experience: 4-6'."""
    m = make_matcher()
    r = m.match(job("Data Engineer", "Experience: 4-6 Job Category: Software Engineering"))
    assert not r.is_match
    assert "4+" in r.reason


def test_matcher_rejects_text_blob_title():
    """Weproms case: listing container ka poora text title ban gaya tha."""
    m = make_matcher()
    blob = (
        "Full-time / Contract Marketing Data Analyst Analyze channel "
        "performance, conversion quality, dashboards, attribution, and "
        "growth opportunities. Remote Salary: Open View role"
    )
    r = m.match(job(blob))
    assert not r.is_match
    assert "blob" in r.reason


def test_matcher_still_accepts_clean_junior_title_after_fixes():
    """Fixes ke baad sahi entry-level jobs accept hote rahein."""
    m = make_matcher()
    assert m.match(job("Junior Data Scientist", "0-2 years experience")).is_match