"""
MCP — Master Control Program
Orchestrates the full pipeline: scrape → analyze → optimize → apply.
"""

import logging
from typing import List, Optional

from src.analyzers.job_analyzer import JobAnalyzer
from src.models.job import Job
from src.notifiers.telegram_notifier import TelegramNotifier
from src.optimizers.resume_optimizer import ResumeOptimizer
from src.scrapers.job_scraper import JobScraper
from src.submitters.application_submitter import ApplicationSubmitter
from src.utils.config import load_config, get_job_search_criteria

logger = logging.getLogger(__name__)


class MCP:
    """Master Control Program — end-to-end job application pipeline."""

    def __init__(self, config: Optional[dict] = None):
        self.config = config or load_config()

        self.job_scraper = JobScraper(self.config)
        self.job_analyzer = JobAnalyzer(self.config)
        self.resume_optimizer = ResumeOptimizer(self.config)
        self.application_submitter = ApplicationSubmitter(self.config)
        self.telegram = TelegramNotifier(self.config)

    # ── High-level orchestration ───────────────────────────────────

    def search_and_apply(self, job_criteria: Optional[dict] = None,
                         max_jobs: Optional[int] = None) -> List[Job]:
        """
        Full pipeline:
          1. Scrape LinkedIn for jobs matching criteria
          2. Fetch descriptions for top candidates
          3. Filter out excluded companies (SatSure, SkyServe, etc.)
          4. Score & rank by relevance
          5. Optimize resume per job
          6. Log / submit applications (via Easy Apply if --apply)
        Returns the ranked list of jobs.
        """
        criteria = {**get_job_search_criteria(self.config), **(job_criteria or {})}
        # Determine how many jobs to process
        easy_cfg = self.config.get("application_submitter", {}).get("easy_apply", {})
        job_limit = max_jobs or easy_cfg.get("max_jobs", 25)

        # ── Step 0 — Web-wide agent search (Claude or CrewAI) ──
        crew_jobs = []
        company_intel = {}
        crew_enabled = self.config.get("crewai", {}).get("enabled", False)
        if crew_enabled:
            logger.info("=" * 60)
            logger.info("STEP 0: Running web-wide agent search …")
            logger.info("=" * 60)
            # Prefer Claude agents (ANTHROPIC_API_KEY); fall back to CrewAI
            import os
            if os.environ.get("ANTHROPIC_API_KEY"):
                try:
                    from src.agents.claude_agents import ClaudeJobSearchCrew
                    crew = ClaudeJobSearchCrew(self.config)
                    crew_jobs, company_intel = crew.run(job_criteria)
                    logger.info("Claude agents found %d jobs", len(crew_jobs))
                except Exception as exc:
                    logger.warning("Claude agents failed (%s) — trying CrewAI", exc)
            if not crew_jobs:
                try:
                    from src.agents.crew import JobSearchCrew
                    crew = JobSearchCrew(self.config)
                    crew_jobs, company_intel = crew.run(job_criteria)
                    logger.info("CrewAI found %d jobs from web search", len(crew_jobs))
                except ImportError as exc:
                    logger.warning("CrewAI not installed (%s) — skipping web search", exc)
                except Exception as exc:
                    logger.warning("CrewAI agents failed (%s) — continuing with LinkedIn", exc)

        # Step 1 — Scrape LinkedIn
        logger.info("=" * 60)
        logger.info("STEP 1: Scraping LinkedIn for jobs …")
        logger.info("=" * 60)
        raw_jobs = self.job_scraper.search_jobs(criteria)
        logger.info("Found %d raw job listings from LinkedIn", len(raw_jobs))

        # Merge CrewAI + LinkedIn results (de-duplicate by company+title)
        if crew_jobs:
            existing_keys = {
                f"{j.company.lower().strip()}:{j.title.lower().strip()}"
                for j in raw_jobs
            }
            merged_count = 0
            for cj in crew_jobs:
                key = f"{cj.company.lower().strip()}:{cj.title.lower().strip()}"
                if key not in existing_keys:
                    raw_jobs.append(cj)
                    existing_keys.add(key)
                    merged_count += 1
            logger.info(
                "Merged %d unique CrewAI jobs (total: %d)",
                merged_count, len(raw_jobs),
            )

        if not raw_jobs:
            logger.warning("No jobs found. Try broadening search criteria.")
            return []

        # Step 2 — Filter excluded companies
        logger.info("STEP 2: Filtering excluded companies …")
        filtered_jobs = self.job_scraper.filter_jobs(
            raw_jobs, {"excluded_companies": criteria.get("excluded_companies", [])}
        )
        logger.info("%d jobs after company exclusion filter", len(filtered_jobs))

        # Step 3 — Fetch descriptions for top N (to avoid rate limits)
        logger.info("STEP 3: Fetching job descriptions …")
        fetch_limit = min(len(filtered_jobs), 30)
        for i, job in enumerate(filtered_jobs[:fetch_limit]):
            if not job.description:
                job.description = self.job_scraper.fetch_job_description(job)
                logger.info("  [%d/%d] %s @ %s", i + 1, fetch_limit, job.title, job.company)

        # Step 4 — Score & rank
        logger.info("STEP 4: Scoring and ranking jobs …")
        ranked_jobs = self.job_analyzer.rank_jobs(filtered_jobs)

        # Step 5 — Print summary
        logger.info("=" * 60)
        logger.info("TOP MATCHING JOBS")
        logger.info("=" * 60)
        for i, job in enumerate(ranked_jobs[:25], 1):
            geo_tag = " 🌍" if job.is_geospatial else ""
            logger.info(
                "  %2d. [P%d | %.1f%%] %s @ %s (%s)%s",
                i, job.priority, job.relevance_score,
                job.title, job.company, job.location, geo_tag,
            )
            if job.matched_skills:
                logger.info("      Skills: %s", ", ".join(job.matched_skills))
            if job.url:
                logger.info("      URL: %s", job.url)

        # Step 6 — Load resume & generate tailored PDFs
        logger.info("STEP 5: Loading resume & generating tailored PDFs …")
        resume = self.resume_optimizer.load_resume()
        logger.info("Resume loaded: %s (%d skills detected)", resume.candidate_name, len(resume.skills))

        # Generate tailored resume PDFs for top jobs
        jobs_to_process = ranked_jobs[:job_limit]
        resume_pdfs = {}
        send_pdfs = self.config.get("telegram", {}).get("send_resume_pdf", True)
        for job in jobs_to_process:
            if job.description:  # only generate if we have a description
                try:
                    pdf_path = self.resume_optimizer.generate_tailored_pdf(job)
                    if pdf_path:
                        resume_pdfs[job.job_id] = pdf_path
                except Exception as exc:
                    logger.warning("Could not generate PDF for %s: %s", job.job_id, exc)

        logger.info("Generated %d tailored resume PDFs", len(resume_pdfs))

        # Step 7 — Send to Telegram
        if self.telegram.enabled:
            logger.info("STEP 6: Sending to Telegram …")
            tg_results = self.telegram.send_batch(
                jobs_to_process,
                resume_pdfs if send_pdfs else None,
            )
            logger.info(
                "Telegram: %d sent, %d failed",
                tg_results["sent"], tg_results["failed"],
            )
        else:
            logger.info("STEP 6: Telegram disabled — skipping notifications")

        # Step 8 — Apply / Log applications
        logger.info("STEP 7: Processing applications …")
        results = self.application_submitter.submit_batch(
            jobs_to_process, resume.content, resume_pdfs=resume_pdfs,
        )
        logger.info(
            "DONE — %d applications processed, %d skipped",
            results["processed"],
            results["skipped"],
        )

        return ranked_jobs

    # ── Convenience methods ────────────────────────────────────────

    def optimize_resume(self, job_description: str) -> str:
        """Optimize resume for a single job description."""
        keywords = self.job_analyzer.analyze_job_description(job_description)
        return self.resume_optimizer.optimize_resume(keywords)

    def apply_to_job(self, job_id: str, resume: str) -> None:
        """Submit application for a single job ID."""
        self.application_submitter.submit_application(job_id, resume)

    # Keep backward-compatible camelCase alias
    def searchAndApply(self, job_criteria: Optional[dict] = None) -> List[Job]:
        return self.search_and_apply(job_criteria)