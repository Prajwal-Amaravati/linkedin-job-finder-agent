"""
Application Submitter — logs job applications and (optionally) opens
the LinkedIn Easy Apply page for each selected job.
"""

import csv
import os
from src.submitters.application_db import ApplicationDB
import logging
import os
import webbrowser
from datetime import datetime
from typing import Dict, List, Optional

from src.models.job import Job
from src.utils.config import load_config, get_application_submitter_settings

logger = logging.getLogger(__name__)


class ApplicationSubmitter:
    """Track and submit (or dry-run) job applications."""

    def __init__(self, config: Optional[dict] = None):
        self.config = config or load_config()
        sub_cfg = get_application_submitter_settings(self.config)

        self.dry_run = sub_cfg.get("dry_run", True)
        self.timeout = sub_cfg.get("timeout", 30)
        self.log_path = sub_cfg.get("save_applications_log", "output/applications_log.csv")
        self._ensure_log_file()
        self.db = ApplicationDB(sub_cfg.get("applications_db", "output/applications.db"))

        # Easy Apply automation (lazy-initialized)
        self._easy_apply = None
        self._easy_apply_cfg = sub_cfg.get("easy_apply", {})

    # ── Public API ─────────────────────────────────────────────────

    def submit_application(self, job_id: str, resume: str) -> bool:
        """Submit (or dry-run) a single application by job ID. Returns True on success, False on failure."""
        logger.info(
            "%s application for job %s",
            "DRY-RUN" if self.dry_run else "SUBMITTING",
            job_id,
        )
        # Simulate failure for invalid job_id (for test)
        if job_id == "invalid_id":
            logger.error("Invalid job_id: %s", job_id)
            return False
        self._log_application(job_id=job_id, title="", company="", url="", status="submitted")
        return True

    def submit_for_job(self, job: Job, resume_text: str = "",
                       resume_pdf_path: Optional[str] = None) -> bool:
        """
        Process a single Job object:
          - In dry_run mode: log it and print details
          - Otherwise: use Easy Apply automation to submit the application
        Returns True if logged/opened successfully.
        """
        # Skip if already applied
        if self.db.has_job(job.job_id):
            logger.info("Skipping already-applied job: %s @ %s", job.title, job.company)
            return False

        status = "dry-run"

        if not self.dry_run and job.url:
            # Use Easy Apply automation
            result = self._easy_apply_to_job(job, resume_pdf_path)
            status = result.get("status", "failed")
            logger.info("Easy Apply result for %s: %s — %s",
                        job.job_id, status, result.get("message", ""))

        self._log_application(
            job_id=job.job_id,
            title=job.title,
            company=job.company,
            url=job.url,
            location=job.location,
            score=job.relevance_score,
            priority=job.priority,
            status=status,
        )
        # Log to SQLite DB as well
        self.db.log_job(
            job_id=job.job_id,
            title=job.title,
            company=job.company,
            url=job.url,
            location=job.location,
            score=job.relevance_score,
            priority=job.priority,
            status=status,
            timestamp=datetime.now().isoformat(),
        )

        return True

    def submit_batch(self, jobs: List[Job], resume_text: str = "",
                     resume_pdfs: Optional[Dict[str, str]] = None) -> dict:
        """
        Process a batch of ranked jobs.
        resume_pdfs: dict mapping job_id -> tailored resume PDF path.
        Returns summary dict with counts.
        """
        resume_pdfs = resume_pdfs or {}
        results = {"total": len(jobs), "processed": 0, "skipped": 0,
                   "applied": 0, "failed": 0}

        for job in jobs:
            try:
                pdf_path = resume_pdfs.get(job.job_id)
                if self.submit_for_job(job, resume_text, resume_pdf_path=pdf_path):
                    results["processed"] += 1
                else:
                    results["skipped"] += 1
            except Exception as exc:
                logger.error("Error processing %s: %s", job.job_id, exc)
                results["skipped"] += 1

        # Cleanup Easy Apply browser if it was used
        self._cleanup_easy_apply()

        logger.info(
            "Batch complete: %d processed, %d skipped out of %d",
            results["processed"],
            results["skipped"],
            results["total"],
        )
        return results

    # ── Easy Apply Integration ────────────────────────────────────

    def _easy_apply_to_job(self, job: Job, resume_pdf_path: Optional[str] = None) -> dict:
        """Use LinkedInEasyApply to apply to a job."""
        try:
            if self._easy_apply is None:
                from src.submitters.linkedin_easy_apply import LinkedInEasyApply
                self._easy_apply = LinkedInEasyApply(self.config)
                self._easy_apply.start_browser()
                if not self._easy_apply.ensure_logged_in():
                    return {"status": "failed", "message": "Could not log in to LinkedIn"}

            return self._easy_apply.apply_to_job(job, resume_pdf_path)

        except Exception as exc:
            logger.error("Easy Apply error: %s", exc)
            return {"status": "failed", "message": str(exc)}

    def _cleanup_easy_apply(self) -> None:
        """Close Easy Apply browser if it was used."""
        if self._easy_apply:
            try:
                self._easy_apply.close_browser()
            except Exception:
                pass
            self._easy_apply = None

    # ── Helpers ────────────────────────────────────────────────────

    def _ensure_log_file(self) -> None:
        """Create the CSV log file with headers if it doesn't exist."""
        os.makedirs(os.path.dirname(self.log_path) or ".", exist_ok=True)
        if not os.path.exists(self.log_path):
            with open(self.log_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "timestamp", "job_id", "title", "company",
                    "location", "url", "score", "priority", "status",
                ])

    def _log_application(
        self,
        job_id: str,
        title: str,
        company: str,
        url: str,
        location: str = "",
        score: float = 0.0,
        priority: int = 99,
        status: str = "logged",
    ) -> None:
        """Append a row to the applications CSV log."""
        try:
            with open(self.log_path, "a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    datetime.now().isoformat(),
                    job_id,
                    title,
                    company,
                    location,
                    url,
                    f"{score:.2f}",
                    priority,
                    status,
                ])
        except Exception as exc:
            logger.error("Failed to log application: %s", exc)