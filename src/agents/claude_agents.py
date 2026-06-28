"""
Claude-powered agents for job search and company intelligence.
Uses the Anthropic API directly — drop-in replacement for the
CrewAI + OpenAI agents in job_research_agent.py / company_intel_agent.py.

Requires: ANTHROPIC_API_KEY environment variable.
"""

import hashlib
import json
import logging
import os
import re
from typing import Dict, List, Optional, Tuple

import anthropic

from src.models.job import Job
from src.utils.config import load_config, get_job_search_criteria

logger = logging.getLogger(__name__)

_MODEL = "claude-opus-4-6"


class ClaudeJobResearchAgent:
    """
    Uses Claude with the web_search server-side tool to discover job
    postings across the entire web (company career pages, job boards, etc.).
    """

    def __init__(self, config: Optional[dict] = None):
        self.config = config or load_config()
        self.search_cfg = get_job_search_criteria(self.config)
        self.client = anthropic.Anthropic()

    def search(self, criteria_overrides: Optional[dict] = None) -> List[Job]:
        """Search for jobs and return a list of Job objects."""
        criteria = {**self.search_cfg, **(criteria_overrides or {})}

        roles = criteria.get("target_roles", ["Senior Software Engineer"])
        locations = criteria.get("locations", [{"name": "Remote", "priority": 1}])
        domain_keywords = criteria.get("domain_keywords", ["geospatial"])
        skill_keywords = criteria.get("skill_keywords", ["Python"])
        excluded = criteria.get("excluded_companies", [])
        target_companies = criteria.get("target_companies", [])

        location_names = [
            loc if isinstance(loc, str) else loc["name"] for loc in locations[:5]
        ]

        prompt = f"""Search for current job openings matching these criteria:

**Target Roles:** {', '.join(roles[:5])}
**Locations:** {', '.join(location_names)}
**Industry Focus:** {', '.join(domain_keywords[:8])}
**Key Skills:** {', '.join(skill_keywords[:10])}
**Target Companies (search these specifically):** {', '.join(target_companies[:10])}
**EXCLUDE these companies:** {', '.join(excluded)}

Search strategies:
1. Search each role + "geospatial" or "GIS" or "earth observation"
2. Search target company career pages directly (e.g. "Planet Labs careers software engineer")
3. Search job boards: site:greenhouse.io OR site:lever.co

For each job found, extract:
- Job title, company name, location, URL to posting, brief 2-3 sentence description

Only return jobs posted in the last 2 weeks. Exclude: {', '.join(excluded)}

Return ONLY a JSON array — no markdown, no explanation:
[{{"title": "...", "company": "...", "location": "...", "url": "...", "description": "..."}}]
At least 5 and at most 20 results."""

        logger.info("Claude: Searching for jobs …")
        try:
            with self.client.messages.stream(
                model=_MODEL,
                max_tokens=4096,
                thinking={"type": "adaptive"},
                tools=[{"type": "web_search_20260209", "name": "web_search"}],
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                response = stream.get_final_message()
        except anthropic.APIError as exc:
            logger.error("Claude API error during job search: %s", exc)
            return []

        raw_output = next(
            (b.text for b in response.content if b.type == "text"), ""
        )
        return self._parse_results(raw_output)

    def _parse_results(self, raw_output: str) -> List[Job]:
        json_match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", raw_output, re.DOTALL)
        if json_match:
            raw_json = json_match.group(1)
        else:
            json_match = re.search(r"\[.*\]", raw_output, re.DOTALL)
            raw_json = json_match.group(0) if json_match else "[]"

        try:
            items = json.loads(raw_json)
        except json.JSONDecodeError:
            logger.warning("Failed to parse Claude job search output as JSON")
            return []

        jobs: List[Job] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = item.get("title", "Unknown")
            company = item.get("company", "Unknown")
            url = item.get("url", "")
            id_source = url or f"{company}:{title}"
            job_id = f"claude_{hashlib.md5(id_source.encode()).hexdigest()[:12]}"
            jobs.append(Job(
                job_id=job_id,
                title=title,
                company=company,
                location=item.get("location", "Unknown"),
                description=item.get("description", ""),
                url=url,
                date_posted="",
                priority=1,
            ))

        logger.info("Claude: Parsed %d jobs from web search", len(jobs))
        return jobs


class ClaudeCompanyIntelAgent:
    """
    Uses Claude with the web_search server-side tool to research companies:
    tech stack, engineering culture, geospatial relevance, recent news.
    """

    def __init__(self, config: Optional[dict] = None):
        self.config = config or load_config()
        self.crew_cfg = self.config.get("crewai", {})
        self.client = anthropic.Anthropic()

    def research(self, companies: List[str]) -> Dict[str, dict]:
        """Research a list of companies and return an intelligence dict."""
        max_companies = self.crew_cfg.get("max_company_research", 5)
        companies_to_research = companies[:max_companies]

        prompt = f"""Research these companies for a Senior Software Engineer applicant:

**Companies:** {', '.join(companies_to_research)}

For EACH company find:
1. **Tech stack** — languages, frameworks, cloud providers, tools
2. **Engineering culture** — team structure, practices, values
3. **Geospatial relevance** — satellite imagery, GIS, mapping, earth observation?
4. **Recent news** — funding, acquisitions, product launches, hiring pushes
5. **Resume keywords** — specific tech or terms to highlight

Return ONLY a JSON object — no markdown, no explanation:
{{
  "Company Name": {{
    "tech_stack": ["Python", "AWS", ...],
    "engineering_culture": "...",
    "geospatial_relevance": "...",
    "recent_news": "...",
    "resume_keywords": ["keyword1", ...],
    "priority_score": 8
  }}
}}"""

        logger.info("Claude: Researching %d companies …", len(companies_to_research))
        try:
            with self.client.messages.stream(
                model=_MODEL,
                max_tokens=4096,
                thinking={"type": "adaptive"},
                tools=[{"type": "web_search_20260209", "name": "web_search"}],
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                response = stream.get_final_message()
        except anthropic.APIError as exc:
            logger.error("Claude API error during company research: %s", exc)
            return {}

        raw_output = next(
            (b.text for b in response.content if b.type == "text"), ""
        )
        return self._parse_results(raw_output)

    def _parse_results(self, raw_output: str) -> Dict[str, dict]:
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_output, re.DOTALL)
        if json_match:
            raw_json = json_match.group(1)
        else:
            json_match = re.search(r"\{.*\}", raw_output, re.DOTALL)
            raw_json = json_match.group(0) if json_match else "{}"

        try:
            intel = json.loads(raw_json)
        except json.JSONDecodeError:
            logger.warning("Failed to parse Claude company intel as JSON")
            return {}

        if not isinstance(intel, dict):
            return {}

        logger.info("Claude: Parsed intel for %d companies", len(intel))
        return intel

    def enrich_jobs_with_intel(
        self, jobs: List[Job], intel: Dict[str, dict]
    ) -> List[Job]:
        """Enrich jobs with company intelligence (mirrors CompanyIntelAgent logic)."""
        for job in jobs:
            company_lower = job.company.lower().strip()
            for company_name, info in intel.items():
                if (company_lower in company_name.lower()
                        or company_name.lower() in company_lower):
                    resume_kws = info.get("resume_keywords", [])
                    existing = {s.lower() for s in job.matched_skills}
                    for kw in resume_kws:
                        if kw.lower() not in existing:
                            job.matched_skills.append(kw)
                            existing.add(kw.lower())

                    geo_text = info.get("geospatial_relevance", "")
                    if geo_text and "none" not in geo_text.lower():
                        job.is_geospatial = True

                    priority_score = info.get("priority_score", 5)
                    if priority_score >= 7:
                        job.relevance_score = min(job.relevance_score + 10, 100)

                    break

        return jobs


class ClaudeJobSearchCrew:
    """
    Orchestrates ClaudeJobResearchAgent + ClaudeCompanyIntelAgent.
    Drop-in replacement for JobSearchCrew — same run() signature and return type.

    Differences vs CrewAI version:
      - Uses ANTHROPIC_API_KEY instead of OPENAI_API_KEY + SERPER_API_KEY
      - Claude calls web_search natively (no SerperDevTool)
      - Adaptive thinking enabled on both steps
    """

    def __init__(self, config: Optional[dict] = None):
        self.config = config or load_config()
        self.crew_cfg = self.config.get("crewai", {})
        self.search_cfg = get_job_search_criteria(self.config)
        self.job_researcher = ClaudeJobResearchAgent(self.config)
        self.company_analyst = ClaudeCompanyIntelAgent(self.config)

    def run(
        self,
        criteria_overrides: Optional[dict] = None,
    ) -> Tuple[List[Job], Dict[str, dict]]:
        """
        Full pipeline:
          1. Job Research  — Claude searches the web for matching jobs
          2. Company Intel — Claude researches discovered + target companies
          3. Enrich        — jobs get matched_skills and score boosts from intel

        Returns (jobs, company_intel).
        """
        if not os.environ.get("ANTHROPIC_API_KEY"):
            logger.error("ANTHROPIC_API_KEY not set — skipping Claude agents")
            return [], {}

        # Step 1: Job Research
        logger.info("=" * 50)
        logger.info("Claude Agent: Job Research")
        logger.info("=" * 50)
        jobs = self.job_researcher.search(criteria_overrides)
        logger.info("Claude Agent: Found %d jobs", len(jobs))

        if not jobs:
            return [], {}

        # Step 2: Company Intelligence
        discovered_companies = list({job.company for job in jobs})
        target_companies = self.search_cfg.get("target_companies", [])

        companies_to_research = discovered_companies[:5]
        remaining = max(
            0,
            self.crew_cfg.get("max_company_research", 5) - len(companies_to_research),
        )
        for tc in target_companies:
            if tc not in companies_to_research and remaining > 0:
                companies_to_research.append(tc)
                remaining -= 1

        logger.info("=" * 50)
        logger.info("Claude Agent: Company Intelligence (%d companies)", len(companies_to_research))
        logger.info("=" * 50)
        company_intel = self.company_analyst.research(companies_to_research)
        logger.info("Claude Agent: Intel gathered for %d companies", len(company_intel))

        # Step 3: Enrich
        if company_intel:
            jobs = self.company_analyst.enrich_jobs_with_intel(jobs, company_intel)

        return jobs, company_intel
