"""
Telegram Notifier — sends job matches with tailored resume PDFs
to a Telegram channel/chat so you can review and apply directly.
"""

import logging
import os
import re
import time
from typing import List, Optional

import requests

from src.models.job import Job
from src.utils.config import load_config

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Send job listings + tailored resumes to a Telegram channel."""

    TELEGRAM_API = "https://api.telegram.org/bot{token}"

    def __init__(self, config: Optional[dict] = None):
        self.config = config or load_config()
        tg_cfg = self.config.get("telegram", {})

        self.bot_token = tg_cfg.get("bot_token", "")
        self.chat_id = tg_cfg.get("chat_id", "")
        self.enabled = tg_cfg.get("enabled", False)
        self.delay = tg_cfg.get("delay_between_messages", 1)
        self.max_messages = tg_cfg.get("max_messages_per_run", 25)

        if self.enabled and not self.bot_token:
            logger.warning("Telegram enabled but bot_token is missing!")
            self.enabled = False
        if self.enabled and not self.chat_id:
            logger.warning("Telegram enabled but chat_id is missing!")
            self.enabled = False

    @property
    def api_url(self) -> str:
        return self.TELEGRAM_API.format(token=self.bot_token)

    # ── Public API ─────────────────────────────────────────────────

    def send_job_notification(
        self,
        job: Job,
        resume_pdf_path: Optional[str] = None,
        rank: int = 0,
    ) -> bool:
        """
        Send a single job notification to Telegram with:
          - Formatted job details
          - Apply link
          - Tailored resume PDF as attachment
        """
        if not self.enabled:
            logger.debug("Telegram disabled — skipping notification for %s", job.job_id)
            return False

        # Build the message
        geo_tag = "🌍 GEOSPATIAL" if job.is_geospatial else ""
        skills_text = ", ".join(job.matched_skills) if job.matched_skills else "—"

        message = (
            f"{'━' * 30}\n"
            f"🔔 <b>Job #{rank}</b> {geo_tag}\n"
            f"{'━' * 30}\n\n"
            f"💼 <b>{self._escape_html(job.title)}</b>\n"
            f"🏢 {self._escape_html(job.company)}\n"
            f"📍 {self._escape_html(job.location)}\n\n"
            f"📊 <b>Score:</b> {job.relevance_score:.1f}%\n"
            f"🎯 <b>Priority:</b> P{job.priority}\n"
            f"🛠 <b>Matched Skills:</b> {self._escape_html(skills_text)}\n\n"
        )

        if job.url:
            message += f"🔗 <a href=\"{job.url}\">Apply on LinkedIn</a>\n\n"

        if resume_pdf_path:
            message += "📎 <i>Tailored resume attached below</i>\n"
        else:
            message += "📝 <i>Use your master resume to apply</i>\n"

        # Send the text message
        text_sent = self._send_message(message)

        # Send the resume PDF if available
        pdf_sent = False
        if resume_pdf_path and os.path.exists(resume_pdf_path):
            caption = f"📎 Resume tailored for: {job.title} @ {job.company}"
            pdf_sent = self._send_document(resume_pdf_path, caption)

        return text_sent or pdf_sent

    def send_batch(
        self,
        jobs: List[Job],
        resume_pdf_paths: Optional[dict] = None,
    ) -> dict:
        """
        Send notifications for a batch of ranked jobs.
        resume_pdf_paths: dict mapping job_id → pdf file path
        """
        if not self.enabled:
            logger.info("Telegram notifications disabled — skipping batch")
            return {"sent": 0, "failed": 0, "total": len(jobs)}

        resume_pdf_paths = resume_pdf_paths or {}
        results = {"sent": 0, "failed": 0, "total": len(jobs)}

        # Send intro message
        self._send_message(
            f"🚀 <b>LinkedIn Job Agent — New Results</b>\n\n"
            f"Found <b>{len(jobs)}</b> matching jobs.\n"
            f"Sending top {min(len(jobs), self.max_messages)} matches…"
        )
        time.sleep(self.delay)

        for i, job in enumerate(jobs[: self.max_messages], 1):
            try:
                pdf_path = resume_pdf_paths.get(job.job_id)
                success = self.send_job_notification(job, pdf_path, rank=i)
                if success:
                    results["sent"] += 1
                else:
                    results["failed"] += 1
            except Exception as exc:
                logger.error("Failed to send Telegram notification for %s: %s", job.job_id, exc)
                results["failed"] += 1

            time.sleep(self.delay)

        # Send summary
        self._send_message(
            f"✅ <b>Batch complete</b>\n"
            f"Sent: {results['sent']} | Failed: {results['failed']}"
        )

        logger.info(
            "Telegram: sent %d, failed %d out of %d",
            results["sent"], results["failed"], results["total"],
        )
        return results

    def send_test_message(self) -> bool:
        """Send a test message to verify bot + chat_id work."""
        return self._send_message(
            "✅ <b>LinkedIn Resume Agent</b> — Telegram integration working!"
        )

    # ── Internal helpers ───────────────────────────────────────────

    def _send_message(self, text: str) -> bool:
        """Send a text message via Telegram Bot API."""
        url = f"{self.api_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }
        try:
            resp = requests.post(url, json=payload, timeout=15)
            if resp.status_code == 200:
                return True
            else:
                logger.error("Telegram sendMessage failed: %s %s", resp.status_code, resp.text)
                return False
        except requests.RequestException as exc:
            logger.error("Telegram request failed: %s", exc)
            return False

    def _send_document(self, file_path: str, caption: str = "") -> bool:
        """Send a document (PDF) via Telegram Bot API."""
        url = f"{self.api_url}/sendDocument"
        try:
            with open(file_path, "rb") as f:
                files = {"document": (os.path.basename(file_path), f)}
                data = {
                    "chat_id": self.chat_id,
                    "caption": caption[:1024],  # Telegram caption limit
                    "parse_mode": "HTML",
                }
                resp = requests.post(url, data=data, files=files, timeout=30)
                if resp.status_code == 200:
                    return True
                else:
                    logger.error("Telegram sendDocument failed: %s %s", resp.status_code, resp.text)
                    return False
        except Exception as exc:
            logger.error("Failed to send document %s: %s", file_path, exc)
            return False

    @staticmethod
    def _escape_html(text: str) -> str:
        """Escape HTML special chars for Telegram."""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
