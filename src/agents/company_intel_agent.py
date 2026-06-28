"""
Company Intelligence Agent — uses CrewAI + SerperDevTool to research
target companies (tech stack, culture, funding, geospatial relevance).
"""

import logging
import json
import re
from typing import Dict, List, Optional

from src.models.job import Job
from src.utils.config import load_config

logger = logging.getLogger(__name__)


class CompanyIntelAgent:
    """
    CrewAI agent that researches companies to gather intelligence:
    - Tech stack and engineering culture
    - Recent funding / growth signals
    - Geospatial relevance and products
    - Interview tips and what they look for

    This information helps tailor resumes and prioritize applications.
    """

    def __init__(self, config: Optional[dict] = None):
        self.config = config or load_config()
        self.crew_cfg = self.config.get("crewai", {})

    def create_agent(self):
        """Create and return the CrewAI Agent with SerperDevTool."""
        from crewai import Agent
        from crewai_tools import SerperDevTool

        search_tool = SerperDevTool(
            n_results=self.crew_cfg.get("max_search_results", 10),
        )

        return Agent(
            role="Company Intelligence Analyst",
            goal=(
                "Research companies to understand their tech stack, engineering "
                "culture, recent developments, and how they relate to geospatial "
                "technology. Provide actionable intelligence that helps tailor "
                "job applications and resumes."
            ),
            backstory=(
                "You are a seasoned tech industry analyst who specializes in "
                "researching companies for job seekers. You know how to find "
                "engineering blog posts, tech stack disclosures, Glassdoor reviews, "
                "and funding announcements. Your reports help candidates tailor "
                "their applications to each company's specific needs."
            ),
            tools=[search_tool],
            verbose=self.crew_cfg.get("verbose", True),
            allow_delegation=False,
            llm=self.crew_cfg.get("model", "gpt-4o-mini"),
        )

    def create_research_task(self, agent, companies: List[str]):
        """Create the company research Task for this agent."""
        from crewai import Task

        max_companies = self.crew_cfg.get("max_company_research", 5)
        companies_to_research = companies[:max_companies]

        return Task(
            description=f"""Research the following companies and provide intelligence reports:

**Companies:** {', '.join(companies_to_research)}

For EACH company, find:
1. **Tech Stack**: What programming languages, frameworks, cloud providers, and tools do they use?
2. **Engineering Culture**: How is their engineering team structured? Do they do code reviews, pair programming, agile?
3. **Geospatial Relevance**: Do they work with geospatial data, satellite imagery, GIS, mapping, or earth observation?
4. **Recent News**: Any recent funding rounds, acquisitions, product launches, or hiring pushes?
5. **Key Technologies**: What specific technologies should a candidate highlight in their resume?

Focus on information that would help a Senior Software Engineer / Tech Lead tailor their resume and cover letter.
""",
            expected_output="""A JSON object with company names as keys:
{
  "Company Name": {
    "tech_stack": ["Python", "AWS", "Kubernetes", ...],
    "engineering_culture": "Brief description...",
    "geospatial_relevance": "How they relate to geospatial tech...",
    "recent_news": "Any recent developments...",
    "resume_keywords": ["keyword1", "keyword2", ...],
    "priority_score": 8
  }
}
Return ONLY valid JSON.""",
            agent=agent,
        )

    def parse_results(self, raw_output: str) -> Dict[str, dict]:
        """Parse the CrewAI agent's company intelligence output."""
        # Try to extract JSON from the output
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_output, re.DOTALL)
        if json_match:
            raw_json = json_match.group(1)
        else:
            json_match = re.search(r"\{.*\}", raw_output, re.DOTALL)
            raw_json = json_match.group(0) if json_match else "{}"

        try:
            intel = json.loads(raw_json)
        except json.JSONDecodeError:
            logger.warning("Failed to parse company intel as JSON")
            return {}

        if not isinstance(intel, dict):
            logger.warning("Company intel is not a dict")
            return {}

        logger.info("Parsed intelligence for %d companies", len(intel))
        return intel

    def enrich_jobs_with_intel(
        self, jobs: List[Job], intel: Dict[str, dict]
    ) -> List[Job]:
        """
        Use company intelligence to boost job scores and add matched
        skills from company tech stacks.
        """
        for job in jobs:
            company_lower = job.company.lower().strip()
            for company_name, info in intel.items():
                if (company_lower in company_name.lower()
                        or company_name.lower() in company_lower):
                    # Add tech stack keywords to matched_skills
                    resume_kws = info.get("resume_keywords", [])
                    existing = set(s.lower() for s in job.matched_skills)
                    for kw in resume_kws:
                        if kw.lower() not in existing:
                            job.matched_skills.append(kw)
                            existing.add(kw.lower())

                    # Check geospatial relevance
                    geo_text = info.get("geospatial_relevance", "")
                    if geo_text and "none" not in geo_text.lower():
                        job.is_geospatial = True

                    # Boost score based on company priority
                    priority_score = info.get("priority_score", 5)
                    if priority_score >= 7:
                        job.relevance_score = min(
                            job.relevance_score + 10, 100
                        )

                    break  # matched this company

        return jobs
