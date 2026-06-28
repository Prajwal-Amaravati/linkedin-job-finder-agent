"""
LinkedIn Job Scraper — searches LinkedIn's public guest API for job postings.
"""

import logging
import re
import time
from typing import List, Dict, Optional
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

from src.models.job import Job
from src.utils.config import load_config, get_job_scraper_settings, get_job_search_criteria

logger = logging.getLogger(__name__)

# LinkedIn experience-level filter codes
EXPERIENCE_LEVEL_MAP = {
    "internship": "1",
    "entry": "2",
    "associate": "3",
    "mid-senior": "4",
    "senior": "4",       # maps to mid-senior on LinkedIn
    "director": "5",
    "executive": "6",
}

DATE_POSTED_MAP = {
    "past_24h": "r86400",
    "past_week": "r604800",
    "past_month": "r2592000",
    "any": "",
}

JOB_TYPE_MAP = {
    "full-time": "F",
    "part-time": "P",
    "contract": "C",
    "temporary": "T",
    "internship": "I",
}


class JobScraper:
    """Scrapes LinkedIn's public (guest) job search pages."""

    def __init__(self, config: Optional[dict] = None):
        self.config = config or load_config()
        scraper_cfg = get_job_scraper_settings(self.config)
        self.search_cfg = get_job_search_criteria(self.config)

        self.base_url = scraper_cfg.get(
            "api_base_url",
            "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search",
        )
        self.headers = scraper_cfg.get("headers", {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        })
        self.delay = scraper_cfg.get("request_delay_seconds", 2)
        self.max_retries = scraper_cfg.get("max_retries", 3)
        self.timeout = scraper_cfg.get("timeout", 30)

    # ── Public API ─────────────────────────────────────────────────

    def search_jobs(self, criteria: Optional[dict] = None) -> List[Job]:
        """
        Run all configured searches and return a de-duplicated list of Jobs.
        ``criteria`` can override values from settings.yaml at runtime.
        """
        criteria = {**self.search_cfg, **(criteria or {})}
        all_jobs: Dict[str, Job] = {}

        target_roles = criteria.get("target_roles", ["Senior Software Engineer"])
        locations = criteria.get("locations", [{"name": "Remote", "priority": 1}])
        max_per_search = criteria.get("max_results_per_search", 50)
        target_companies = criteria.get("target_companies", [])

        # ── Strategy 1: role × location searches ──
        for role in target_roles:
            for loc_entry in locations:
                loc_name = loc_entry if isinstance(loc_entry, str) else loc_entry["name"]
                priority = loc_entry.get("priority", 2) if isinstance(loc_entry, dict) else 2
                logger.info("Searching: '%s' in '%s' (priority %d)", role, loc_name, priority)

                jobs = self._search_linkedin(
                    keywords=role,
                    location=loc_name,
                    max_results=max_per_search,
                    criteria=criteria,
                )
                for job in jobs:
                    job.priority = min(job.priority, priority)
                    if job.job_id not in all_jobs:
                        all_jobs[job.job_id] = job
                    else:
                        # Keep the best priority
                        all_jobs[job.job_id].priority = min(
                            all_jobs[job.job_id].priority, priority
                        )

        # ── Strategy 2: company-specific searches ──
        for company in target_companies[:20]:  # cap to avoid rate limits
            logger.info("Searching company: '%s'", company)
            jobs = self._search_linkedin(
                keywords=f"Software Engineer {company}",
                location="",
                max_results=10,
                criteria=criteria,
            )
            for job in jobs:
                if job.job_id not in all_jobs:
                    all_jobs[job.job_id] = job

        logger.info("Total unique jobs found: %d", len(all_jobs))
        return list(all_jobs.values())

    def scrape_jobs(self, criteria: dict) -> List[Job]:
        """Alias kept for backward compatibility."""
        return self.search_jobs(criteria)

    # ── Internal helpers ───────────────────────────────────────────

    def _search_linkedin(
        self,
        keywords: str,
        location: str,
        max_results: int = 50,
        criteria: Optional[dict] = None,
    ) -> List[Job]:
        """Hit LinkedIn's guest search API and parse results."""
        criteria = criteria or {}
        jobs: List[Job] = []

        exp_level = EXPERIENCE_LEVEL_MAP.get(
            criteria.get("experience_level", "senior"), "4"
        )
        date_filter = DATE_POSTED_MAP.get(
            criteria.get("date_posted", "past_week"), "r604800"
        )
        job_type = JOB_TYPE_MAP.get(
            criteria.get("job_type", "full-time"), "F"
        )

        for start in range(0, max_results, 25):
            params = {
                "keywords": keywords,
                "location": location,
                "f_E": exp_level,
                "f_JT": job_type,
                "f_TPR": date_filter,
                "start": start,
            }
            # Remove empty params
            params = {k: v for k, v in params.items() if v}

            for attempt in range(self.max_retries):
                try:
                    resp = requests.get(
                        self.base_url,
                        params=params,
                        headers=self.headers,
                        timeout=self.timeout,
                    )
                    if resp.status_code == 429:
                        wait = self.delay * (attempt + 2)
                        logger.warning("Rate limited – waiting %ds", wait)
                        time.sleep(wait)
                        continue
                    resp.raise_for_status()
                    break
                except requests.RequestException as exc:
                    logger.warning("Request failed (attempt %d): %s", attempt + 1, exc)
                    time.sleep(self.delay)
            else:
                logger.error("Giving up on search: %s @ %s", keywords, location)
                continue

            page_jobs = self._parse_search_results(resp.text)
            if not page_jobs:
                break
            jobs.extend(page_jobs)
            time.sleep(self.delay)

        return jobs

    def _parse_search_results(self, html: str) -> List[Job]:
        """Parse the HTML fragment returned by LinkedIn's guest search API."""
        soup = BeautifulSoup(html, "lxml")
        jobs: List[Job] = []

        for card in soup.find_all("div", class_="base-card"):
            try:
                job_id = card.get("data-entity-urn", "").split(":")[-1]
                if not job_id:
                    link_tag = card.find("a", class_="base-card__full-link")
                    if link_tag and link_tag.get("href"):
                        match = re.search(r"/view/(\d+)", link_tag["href"])
                        job_id = match.group(1) if match else ""

                title_tag = card.find("h3", class_="base-search-card__title")
                company_tag = card.find("h4", class_="base-search-card__subtitle")
                location_tag = card.find("span", class_="job-search-card__location")
                link_tag = card.find("a", class_="base-card__full-link")
                time_tag = card.find("time")

                title = title_tag.get_text(strip=True) if title_tag else "Unknown"
                company = company_tag.get_text(strip=True) if company_tag else "Unknown"
                location = location_tag.get_text(strip=True) if location_tag else "Unknown"
                url = link_tag["href"].split("?")[0] if link_tag else ""
                date_posted = time_tag.get("datetime", "") if time_tag else ""

                if job_id:
                    jobs.append(
                        Job(
                            job_id=job_id,
                            title=title,
                            company=company,
                            location=location,
                            description="",  # fetched later if needed
                            url=url,
                            date_posted=date_posted,
                        )
                    )
            except Exception as exc:
                logger.debug("Failed to parse a card: %s", exc)
                continue

        return jobs

    def fetch_job_description(self, job: Job) -> str:
        """Fetch full description for a single job from its detail page."""
        if not job.url:
            return ""
        try:
            resp = requests.get(job.url, headers=self.headers, timeout=self.timeout)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            desc_div = soup.find("div", class_="show-more-less-html__markup")
            if desc_div:
                return desc_div.get_text(separator="\n", strip=True)
        except requests.RequestException as exc:
            logger.warning("Could not fetch description for %s: %s", job.job_id, exc)
        return ""

    def parse_job_listing(self, job_listing):
        """Parse a single raw job listing (kept for interface compat)."""
        return job_listing

    def filter_jobs(self, job_listings: List[Job], filters: dict) -> List[Job]:
        """Apply filters (e.g. exclude companies) to a list of jobs."""
        excluded = {c.lower() for c in filters.get("excluded_companies", [])}
        filtered = []
        for job in job_listings:
            if job.company.lower() in excluded:
                logger.info("Excluding %s (%s) — company blacklisted", job.title, job.company)
                continue
            filtered.append(job)
        return filtered