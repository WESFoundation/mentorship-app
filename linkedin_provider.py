"""Profile data from a LinkedIn URL (no PDF).

LinkedIn does not let a server read a profile from its URL (login wall; scraping is
against its terms), so the data comes from a licensed profile-data provider that is
called with the URL. This module keeps that behind one small interface:

    normalize_url(url)                 -> canonical https://www.linkedin.com/in/<slug>
    fetch_profile(url)                 -> provider-neutral dict (see `_EMPTY`)
    map_to_fields(profile, role)       -> {form field name: value} for the edit-profile form

Configuration (environment):
    LINKEDIN_PROVIDER   "peopledatalabs" | "mock"      (unset = feature reports 'not configured')
    LINKEDIN_API_KEY    the provider's API key
    LINKEDIN_API_BASE   optional override of the provider's base URL

The URL is only ever passed to the provider as a parameter; this server never requests it.
Add another vendor by writing a `_fetch_<name>(url)` that returns the neutral dict and
registering it in `PROVIDERS`.
"""
import os
import re
import logging

import requests

from ai_service import PROFILE_FIELDS, _clean

logger = logging.getLogger(__name__)


class LinkedInError(Exception):
    """A problem to show the user as-is (safe, no secrets)."""

    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


_URL_RE = re.compile(
    r"^(?:https?://)?(?:[a-z]{2,3}\.|www\.)?linkedin\.com/in/([A-Za-z0-9\-_%À-ɏ]{3,100})/?(?:[?#].*)?$")


def normalize_url(raw):
    """Accept a personal profile URL only; return the canonical form or raise."""
    raw = (raw or "").strip()
    m = _URL_RE.match(raw)
    if not m:
        raise LinkedInError("Please enter your personal LinkedIn profile link, like "
                            "https://www.linkedin.com/in/your-name", 400)
    return f"https://www.linkedin.com/in/{m.group(1)}"


_EMPTY = {
    "headline": "", "summary": "", "industry": "", "current_title": "", "current_company": "",
    "previous_title": "", "skills": [], "certifications": [], "years_experience": None,
    "education": [],   # newest first: {"school", "degree", "field", "end_year"}
}


def _year(value):
    m = re.search(r"(19|20)\d{2}", str(value or ""))
    return m.group(0) if m else ""


# ---------------------------------------------------------------- providers
def _fetch_peopledatalabs(url):
    key = os.environ.get("LINKEDIN_API_KEY")
    if not key:
        raise LinkedInError("LinkedIn lookup is not configured on this server (LINKEDIN_API_KEY is missing).", 503)
    base = (os.environ.get("LINKEDIN_API_BASE") or "https://api.peopledatalabs.com").rstrip("/")
    try:
        resp = requests.get(f"{base}/v5/person/enrich", headers={"X-Api-Key": key},
                            params={"profile": url, "min_likelihood": 6}, timeout=30)
    except requests.RequestException as err:
        logger.warning("Profile provider request failed: %s", err)
        raise LinkedInError("Could not reach the profile lookup service. Please try again.")
    if resp.status_code == 404:
        raise LinkedInError("We couldn't find public details for that LinkedIn profile. "
                            "Please fill the form by hand.", 404)
    if resp.status_code == 429:
        raise LinkedInError("The lookup service is busy. Please try again shortly.", 429)
    if resp.status_code != 200:
        logger.warning("Profile provider error %s: %s", resp.status_code, resp.text[:200])
        raise LinkedInError("The profile lookup service returned an error. Please try again.")
    d = (resp.json() or {}).get("data") or {}

    out = dict(_EMPTY, skills=[], certifications=[], education=[])
    out["headline"] = d.get("headline") or d.get("job_title") or ""
    out["summary"] = d.get("summary") or ""
    out["industry"] = d.get("industry") or ""
    out["current_title"] = d.get("job_title") or ""
    out["current_company"] = d.get("job_company_name") or ""
    out["skills"] = [str(s) for s in (d.get("skills") or [])][:15]
    out["certifications"] = [str(c.get("name") if isinstance(c, dict) else c) for c in (d.get("certifications") or [])][:10]
    yrs = d.get("inferred_years_experience")
    out["years_experience"] = int(yrs) if isinstance(yrs, (int, float)) else None
    exp = d.get("experience") or []
    prior = [e for e in exp if isinstance(e, dict) and not e.get("is_primary")]
    if prior:
        title = (prior[0].get("title") or {}).get("name") if isinstance(prior[0].get("title"), dict) else prior[0].get("title")
        out["previous_title"] = title or ""
    for e in d.get("education") or []:
        if not isinstance(e, dict):
            continue
        out["education"].append({
            "school": ((e.get("school") or {}).get("name") or "") if isinstance(e.get("school"), dict) else "",
            "degree": ", ".join(e.get("degrees") or []),
            "field": ", ".join(e.get("majors") or []),
            "end_year": _year(e.get("end_date")),
        })
    out["education"].sort(key=lambda x: x["end_year"] or "0", reverse=True)
    return out


def _fetch_mock(url):
    """Deterministic data for development and tests (LINKEDIN_PROVIDER=mock)."""
    if url.endswith("/in/not-found"):
        raise LinkedInError("We couldn't find public details for that LinkedIn profile. "
                            "Please fill the form by hand.", 404)
    return dict(_EMPTY, headline="Senior Data Engineer", industry="Software", current_title="Senior Data Engineer",
                current_company="Acme Analytics", previous_title="Data Engineer",
                skills=["Python", "SQL", "Airflow"], certifications=["AWS Solutions Architect"],
                years_experience=9,
                education=[{"school": "University of Luxembourg", "degree": "M.Sc.", "field": "Computer Science", "end_year": "2015"},
                           {"school": "State College", "degree": "B.Sc.", "field": "Mathematics", "end_year": "2013"}])


PROVIDERS = {"peopledatalabs": _fetch_peopledatalabs, "mock": _fetch_mock}


def status():
    """(ready, reason) - why the URL lookup can or cannot run on this server."""
    name = (os.environ.get("LINKEDIN_PROVIDER") or "").strip().lower()
    if not name:
        return False, "LINKEDIN_PROVIDER is not set (use 'peopledatalabs')"
    if name not in PROVIDERS:
        return False, f"LINKEDIN_PROVIDER '{name}' is unknown (use one of: {', '.join(sorted(PROVIDERS))})"
    if name != "mock" and not (os.environ.get("LINKEDIN_API_KEY") or "").strip():
        return False, f"LINKEDIN_PROVIDER is '{name}' but LINKEDIN_API_KEY is empty"
    return True, f"provider '{name}'"


def is_configured():
    return status()[0]


def fetch_profile(url):
    name = (os.environ.get("LINKEDIN_PROVIDER") or "").strip().lower()
    if name not in PROVIDERS:
        raise LinkedInError("Filling from a LinkedIn link isn't set up on this server yet.", 503)
    return PROVIDERS[name](normalize_url(url))


# ------------------------------------------------------------------- mapping
def map_to_fields(p, role):
    """Provider-neutral profile -> the form's field names for this role (partial is fine)."""
    role = "mentor" if role == "mentor" else "mentee"
    top = (p.get("education") or [{}])[0] if p.get("education") else {}
    skills = ", ".join(p.get("skills") or [])
    yrs = p.get("years_experience")
    yrs = str(yrs) if isinstance(yrs, int) and 0 <= yrs <= 60 else ""
    if role == "mentor":
        raw = {
            "skills": skills, "role": p.get("current_title"), "organisation": p.get("current_company"),
            "years_of_experience": yrs, "degree_name": top.get("degree"), "field_of_study": top.get("field"),
            "university_name": top.get("school"), "graduation_year": top.get("end_year"),
            "certifications": ", ".join(p.get("certifications") or []),
        }
    else:
        raw = {
            "key_skills": skills, "current_role": p.get("current_title"), "current_organization": p.get("current_company"),
            "last_role": p.get("previous_title"), "years_experience": yrs, "course_stream": top.get("field"),
            "school_name": top.get("school"), "career_interest": p.get("headline"), "industry": p.get("industry"),
        }
    return _clean(raw, PROFILE_FIELDS[role])
