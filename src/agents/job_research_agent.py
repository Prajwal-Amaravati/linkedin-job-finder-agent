"""
Job Research Agent — uses CrewAI + SerperDevTool to discover jobs
across the web (Google Search), beyond just LinkedIn.
"""

import logging
import os
from typing import List, Optional

from src.models.job import Job
from src.utils.config import load_config, get_job_search_criteria

logger = logging.getLogger(__name__)


class JobResearchAgent:
    """
    CrewAI agent that uses SerperDevTool (Google Search API) to find
    job postings across the entire web — company career pages, Indeed,
    Glassdoor, LinkedIn, AngelList, etc.
    """

    def __init__(self, config: Optional[dict] = None):
        self.config = config or load_config()
        self.crew_cfg = self.config.get("crewai", {})
        self.search_cfg = get_job_search_criteria(self.config)

    def create_agent(self):
        """Create and return the CrewAI Agent with SerperDevTool."""
        from crewai import Agent
        from crewai_tools import SerperDevTool

        search_tool = SerperDevTool(
            n_results=self.crew_cfg.get("max_search_results", 10),
        )

        return Agent(
            role="Senior Job Research Specialist",
            goal=(
                "Find the most relevant senior software engineering and tech lead "
                "job openings at geospatial and technology companies worldwide. "
                "Focus on roles that match the candidate's skills in Python, "
                "FastAPI, PostgreSQL/PostGIS, AWS, Kubernetes, and distributed systems."
            ),
            backstory=(
                "You are an expert job market researcher with deep knowledge of "
                "the geospatial technology industry. You know all the major players "
                "— Planet Labs, Maxar, Esri, Mapbox, and dozens more. You excel at "
                "finding hidden job opportunities that don't appear on LinkedIn, "
                "including direct company career page postings and niche job boards."
            ),
            tools=[search_tool],
            verbose=self.crew_cfg.get("verbose", True),
            allow_delegation=False,
            llm=self.crew_cfg.get("model", "gpt-4o-mini"),
        )

    def create_search_task(self, agent, criteria_overrides: Optional[dict] = None):
        """Create the job search Task for this agent."""
        from crewai import Task

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

        return Task(
            description=f"""Search Google for current job openings matching these criteria:

**Target Roles:** {', '.join(roles[:5])}
**Locations:** {', '.join(location_names)}
**Industry Focus:** {', '.join(domain_keywords[:8])}
**Key Skills:** {', '.join(skill_keywords[:10])}
**Target Companies (search these specifically):** {', '.join(target_companies[:10])}
**EXCLUDE these companies:** {', '.join(excluded)}

Search strategies to use:
1. Search for each target role + "geospatial" or "GIS" or "earth observation"
2. Search target company career pages directly (e.g., "Planet Labs careers software engineer")
3. Search for "senior software engineer" at specific geospatial companies
4. Search job boards: site:greenhouse.io, site:lever.co, site:careers-page.com

For each job found, extract:
- Job title
- Company name
- Location
- URL to the job posting
- Brief description (2-3 sentences)

Return ONLY jobs posted in the last 2 weeks. Exclude any jobs from: {', '.join(excluded)}
""",
            expected_output="""A JSON list of job objects with these fields:
[
  {
    "title": "Senior Software Engineer",
    "company": "Planet Labs",
    "location": "San Francisco, CA (Remote)",
    "url": "https://...",
    "description": "Brief 2-3 sentence description..."
  }
]
Return at least 5 and at most 20 results. Return ONLY valid JSON.""",
            agent=agent,
        )

    def parse_results(self, raw_output: str) -> List[Job]:
        """Parse the CrewAI agent's output into Job model objects."""
        import json
        import re
        import hashlib

        jobs: List[Job] = []

        # Try to extract JSON from the output
        # The agent may wrap JSON in markdown code blocks
        json_match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", raw_output, re.DOTALL)
        if json_match:
            raw_json = json_match.group(1)
        else:
            # Try to find a bare JSON array
            json_match = re.search(r"\[.*\]", raw_output, re.DOTALL)
            raw_json = json_match.group(0) if json_match else "[]"

        try:
            items = json.loads(raw_json)
        except json.JSONDecodeError:
            logger.warning("Failed to parse agent output as JSON, attempting line-by-line")
            return jobs

        for item in items:
            if not isinstance(item, dict):
                continue

            title = item.get("title", "Unknown")
            company = item.get("company", "Unknown")
            url = item.get("url", "")

            # Generate a stable job_id from URL or company+title
            id_source = url or f"{company}:{title}"
            job_id = f"crew_{hashlib.md5(id_source.encode()).hexdigest()[:12]}"

            jobs.append(Job(
                job_id=job_id,
                title=title,
                company=company,
                location=item.get("location", "Unknown"),
                description=item.get("description", ""),
                url=url,
                date_posted="",
                priority=1,  # CrewAI-discovered jobs get high priority
            ))

        logger.info("Parsed %d jobs from CrewAI agent output", len(jobs))
        return jobs
