"""
JobSearchCrew — orchestrates the CrewAI agents for web-wide job search
and company intelligence gathering.
"""

import logging
import os
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv

from src.agents.job_research_agent import JobResearchAgent
from src.agents.company_intel_agent import CompanyIntelAgent
from src.models.job import Job
from src.utils.config import load_config, get_job_search_criteria

logger = logging.getLogger(__name__)

# Load .env for API keys
load_dotenv()


class JobSearchCrew:
    """
    Orchestrates CrewAI agents to:
      1. Search Google for jobs (via SerperDevTool)
      2. Research companies for resume tailoring intelligence

    Returns a list of Job objects and a company intelligence dictionary.
    """

    def __init__(self, config: Optional[dict] = None):
        self.config = config or load_config()
        self.crew_cfg = self.config.get("crewai", {})
        self.search_cfg = get_job_search_criteria(self.config)

        self.job_researcher = JobResearchAgent(self.config)
        self.company_analyst = CompanyIntelAgent(self.config)

    def run(
        self,
        criteria_overrides: Optional[dict] = None,
    ) -> Tuple[List[Job], Dict[str, dict]]:
        """
        Execute the full CrewAI pipeline:
          1. Job Research Agent searches Google for relevant jobs
          2. Company Intel Agent researches the companies found
          3. Jobs are enriched with company intelligence

        Returns (jobs, company_intel).
        """
        from crewai import Crew, Process

        # Validate API keys
        if not os.environ.get("SERPER_API_KEY"):
            logger.error(
                "SERPER_API_KEY not set. Get one free at https://serper.dev"
            )
            return [], {}

        if not os.environ.get("OPENAI_API_KEY"):
            logger.error(
                "OPENAI_API_KEY not set. Required for CrewAI agent reasoning."
            )
            return [], {}

        # ── Step 1: Job Research ──────────────────────────────────
        logger.info("🤖 CrewAI: Starting Job Research Agent …")
        job_agent = self.job_researcher.create_agent()
        job_task = self.job_researcher.create_search_task(
            job_agent, criteria_overrides
        )

        job_crew = Crew(
            agents=[job_agent],
            tasks=[job_task],
            process=Process.sequential,
            verbose=self.crew_cfg.get("verbose", True),
        )

        job_result = job_crew.kickoff()
        raw_job_output = str(job_result)
        jobs = self.job_researcher.parse_results(raw_job_output)

        logger.info("🤖 CrewAI: Found %d jobs via web search", len(jobs))

        if not jobs:
            return [], {}

        # ── Step 2: Company Intelligence ──────────────────────────
        # Collect unique companies from discovered jobs + target list
        discovered_companies = list({job.company for job in jobs})
        target_companies = self.search_cfg.get("target_companies", [])

        # Prioritize discovered companies, then fill with targets
        companies_to_research = discovered_companies[:5]
        remaining_slots = max(
            0,
            self.crew_cfg.get("max_company_research", 5) - len(companies_to_research),
        )
        for tc in target_companies:
            if tc not in companies_to_research and remaining_slots > 0:
                companies_to_research.append(tc)
                remaining_slots -= 1

        logger.info(
            "🤖 CrewAI: Starting Company Intel Agent for %d companies …",
            len(companies_to_research),
        )

        intel_agent = self.company_analyst.create_agent()
        intel_task = self.company_analyst.create_research_task(
            intel_agent, companies_to_research
        )

        intel_crew = Crew(
            agents=[intel_agent],
            tasks=[intel_task],
            process=Process.sequential,
            verbose=self.crew_cfg.get("verbose", True),
        )

        intel_result = intel_crew.kickoff()
        raw_intel_output = str(intel_result)
        company_intel = self.company_analyst.parse_results(raw_intel_output)

        logger.info(
            "🤖 CrewAI: Gathered intelligence on %d companies",
            len(company_intel),
        )

        # ── Step 3: Enrich jobs with company intel ────────────────
        if company_intel:
            jobs = self.company_analyst.enrich_jobs_with_intel(jobs, company_intel)
            logger.info("🤖 CrewAI: Enriched jobs with company intelligence")

        return jobs, company_intel
