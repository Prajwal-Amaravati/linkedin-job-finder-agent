"""
Job Analyzer — scores and ranks scraped job listings against the
candidate's profile and search criteria.
"""

import logging
import re
from typing import List, Dict, Optional, Set

from src.models.job import Job
from src.utils.config import load_config, get_job_search_criteria

logger = logging.getLogger(__name__)


class JobAnalyzer:
    """Analyze job descriptions and rank them by relevance."""

    STOP_WORDS: Set[str] = {
        "the", "is", "in", "and", "to", "a", "of", "for", "on", "with",
        "as", "by", "at", "an", "be", "this", "that", "it", "are", "or",
        "from", "which", "but", "not", "all", "any", "can", "we", "you",
        "your", "their", "they", "he", "she", "his", "her", "its", "my",
        "our", "me", "us", "them", "who", "what", "when", "where", "why",
        "how", "if", "then", "so", "more", "most", "some", "such", "no",
        "yes", "like", "just", "will", "would", "should", "could", "may",
        "must", "shall", "need", "also", "about", "into", "over", "after",
        "before", "between", "through", "during", "been", "being", "have",
        "has", "had", "do", "does", "did", "was", "were", "able", "work",
        "working", "experience", "looking", "role", "team", "join",
    }

    def __init__(self, config: Optional[dict] = None):
        self.config = config or load_config()
        search_cfg = get_job_search_criteria(self.config)

        self.domain_keywords = [
            kw.lower() for kw in search_cfg.get("domain_keywords", [])
        ]
        self.skill_keywords = [
            kw.lower() for kw in search_cfg.get("skill_keywords", [])
        ]
        self.excluded_companies = [
            c.lower() for c in search_cfg.get("excluded_companies", [])
        ]

    # ── Public API ─────────────────────────────────────────────────

    def analyze_job_description(self, job_description: str) -> List[str]:
        """Extract meaningful keywords from a job description."""
        words = re.findall(r"[A-Za-z#+]+", job_description)
        keywords = [
            w for w in words if w.lower() not in self.STOP_WORDS and len(w) > 2
        ]
        return keywords

    def score_job(self, job: Job) -> Job:
        """
        Score a job on 0-100 scale based on:
          - Skill keyword matches
          - Domain (geospatial) keyword matches
          - Title relevance
          - Company exclusion
        Mutates and returns the job.
        """
        if self._is_excluded(job):
            job.relevance_score = -1
            return job

        text = f"{job.title} {job.company} {job.description} {job.location}".lower()
        score = 0.0

        # ── Skill matches (up to 40 pts) ──
        matched_skills = []
        for skill in self.skill_keywords:
            if skill in text:
                matched_skills.append(skill)
        skill_ratio = len(matched_skills) / max(len(self.skill_keywords), 1)
        score += skill_ratio * 40
        job.matched_skills = matched_skills

        # ── Domain / geospatial matches (up to 35 pts) ──
        domain_hits = sum(1 for kw in self.domain_keywords if kw in text)
        domain_ratio = domain_hits / max(len(self.domain_keywords), 1)
        score += domain_ratio * 35
        job.is_geospatial = domain_hits >= 2

        # ── Title relevance (up to 15 pts) ──
        title_lower = job.title.lower()
        title_boost_terms = [
            "senior", "lead", "tech lead", "staff", "principal",
            "geospatial", "gis", "platform",
        ]
        title_hits = sum(1 for t in title_boost_terms if t in title_lower)
        score += min(title_hits * 5, 15)

        # ── Seniority bonus (up to 10 pts) ──
        seniority_terms = ["senior", "lead", "staff", "principal", "architect"]
        if any(term in title_lower for term in seniority_terms):
            score += 10

        job.relevance_score = min(round(score, 2), 100)
        return job

    def rank_jobs(self, jobs: List[Job]) -> List[Job]:
        """
        Score all jobs, remove excluded ones, sort by
        (priority ASC, relevance_score DESC).
        """
        scored = [self.score_job(job) for job in jobs]
        # Remove excluded
        valid = [j for j in scored if j.relevance_score >= 0]
        # Sort: lower priority number first, then higher score
        valid.sort(key=lambda j: (j.priority, -j.relevance_score))
        logger.info(
            "Ranked %d jobs (%d removed by exclusion)", len(valid), len(scored) - len(valid)
        )
        return valid

    def filter_by_company_exclusion(self, jobs: List[Job]) -> List[Job]:
        """Remove jobs from excluded companies."""
        return [j for j in jobs if not self._is_excluded(j)]

    # ── Helpers ────────────────────────────────────────────────────

    def _is_excluded(self, job: Job) -> bool:
        company_lower = job.company.lower().strip()
        for excl in self.excluded_companies:
            if excl in company_lower or company_lower in excl:
                return True
        return False