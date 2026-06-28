"""
LinkedIn Easy Apply — Playwright-based browser automation for
clicking Easy Apply and submitting applications on LinkedIn.
"""

import logging
import os
import random
import time
from pathlib import Path
from typing import Optional

from src.models.job import Job
from src.utils.config import load_config, get_candidate_info, get_application_submitter_settings

logger = logging.getLogger(__name__)

# Default browser profile location
DEFAULT_PROFILE_DIR = os.path.expanduser("~/.linkedin-agent-profile")


class LinkedInEasyApply:
    """Automate LinkedIn Easy Apply using Playwright."""

    def __init__(self, config: Optional[dict] = None):
        self.config = config or load_config()
        candidate = get_candidate_info(self.config)
        sub_cfg = get_application_submitter_settings(self.config)
        easy_cfg = sub_cfg.get("easy_apply", {})

        self.candidate_name = candidate.get("name", "")
        self.candidate_email = candidate.get("email", "")
        self.candidate_phone = candidate.get("phone", "")
        self.candidate_location = candidate.get("location", "")

        self.profile_dir = os.path.expanduser(
            easy_cfg.get("browser_profile_dir", DEFAULT_PROFILE_DIR)
        )
        self.delay_actions = easy_cfg.get("delay_between_actions", 3)
        self.delay_jobs = easy_cfg.get("delay_between_jobs", 5)
        self.screenshot_on_error = easy_cfg.get("screenshot_on_error", True)

        self._browser = None
        self._context = None
        self._page = None

    # ── Browser Lifecycle ─────────────────────────────────────────

    def start_browser(self) -> None:
        """Launch a persistent Chromium browser with saved profile."""
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()

        # Use a persistent context so login sessions are remembered
        os.makedirs(self.profile_dir, exist_ok=True)
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=self.profile_dir,
            headless=False,
            channel="chromium",
            viewport={"width": 1280, "height": 900},
            args=[
                "--disable-blink-features=AutomationControlled",
            ],
        )
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        logger.info("Browser launched with persistent profile: %s", self.profile_dir)

    def close_browser(self) -> None:
        """Close browser and cleanup."""
        try:
            if self._context:
                self._context.close()
            if hasattr(self, "_playwright") and self._playwright:
                self._playwright.stop()
        except Exception as exc:
            logger.debug("Browser close error (safe to ignore): %s", exc)
        self._browser = None
        self._context = None
        self._page = None
        logger.info("Browser closed")

    # ── Login ─────────────────────────────────────────────────────

    def ensure_logged_in(self) -> bool:
        """
        Check if user is logged in to LinkedIn.
        If not, navigate to login page and wait for manual login.
        Returns True if logged in successfully.
        """
        if not self._page:
            self.start_browser()

        page = self._page
        logger.info("Checking LinkedIn login status …")

        # Navigate to LinkedIn feed to check login state
        page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
        self._human_delay(2, 3)

        # Check if we're on the feed (logged in) or redirected to login
        if self._is_logged_in():
            logger.info("✅ Already logged in to LinkedIn")
            return True

        # Not logged in — navigate to login page
        logger.info("Not logged in. Opening LinkedIn login page …")
        logger.info("👉 Please log in manually (Google SSO supported). Waiting up to 120 seconds …")
        page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=30000)

        # Wait for user to complete login (check for feed or nav elements)
        try:
            # Wait up to 120 seconds for login to complete
            for i in range(60):
                time.sleep(2)
                if self._is_logged_in():
                    logger.info("✅ Login successful!")
                    return True
                if i % 10 == 0 and i > 0:
                    logger.info("Still waiting for login … (%d seconds elapsed)", i * 2)

            logger.error("❌ Login timeout — 120 seconds elapsed without successful login")
            return False

        except Exception as exc:
            logger.error("Login check failed: %s", exc)
            return False

    def _is_logged_in(self) -> bool:
        """Check if the current page indicates a logged-in LinkedIn session."""
        page = self._page
        try:
            url = page.url
            # If we're on the feed or any authenticated page
            if "/feed" in url or "/mynetwork" in url or "/messaging" in url:
                # Also verify there's a nav element (global nav)
                nav = page.query_selector("header.global-nav, nav.global-nav__nav, .global-nav__me")
                if nav:
                    return True
            # Check for LinkedIn authenticated elements
            me_button = page.query_selector('[data-control-name="nav.settings_signout"], .global-nav__me-photo, .feed-identity-module')
            if me_button:
                return True
        except Exception:
            pass
        return False

    # ── Easy Apply ────────────────────────────────────────────────

    def apply_to_job(self, job: Job, resume_pdf_path: Optional[str] = None) -> dict:
        """
        Attempt to Easy Apply to a single job.
        Returns a dict with:
          - status: 'applied' | 'already_applied' | 'no_easy_apply' | 'failed'
          - message: human-readable status message
        """
        page = self._page
        result = {"status": "failed", "message": ""}

        try:
            # Navigate to the job page
            logger.info("Navigating to job: %s @ %s", job.title, job.company)
            page.goto(job.url, wait_until="domcontentloaded", timeout=30000)
            self._human_delay(2, 4)

            # Check if we've been redirected to login
            if "/login" in page.url or "/authwall" in page.url:
                logger.warning("Redirected to login — session may have expired")
                if not self.ensure_logged_in():
                    result["message"] = "Login required but failed"
                    return result
                page.goto(job.url, wait_until="domcontentloaded", timeout=30000)
                self._human_delay(2, 4)

            # Check if already applied
            already_applied = page.query_selector(
                'span:has-text("Applied"), '
                'button:has-text("Applied"), '
                '.artdeco-inline-feedback:has-text("Applied")'
            )
            if already_applied:
                logger.info("Already applied to this job — skipping")
                result["status"] = "already_applied"
                result["message"] = "Already applied"
                return result

            # Find the Easy Apply button
            easy_apply_btn = self._find_easy_apply_button()
            if not easy_apply_btn:
                logger.info("No Easy Apply button found — this job uses external apply")
                result["status"] = "no_easy_apply"
                result["message"] = "No Easy Apply button available"
                return result

            # Click Easy Apply
            logger.info("Clicking Easy Apply …")
            easy_apply_btn.click()
            self._human_delay(2, 3)

            # Handle the Easy Apply modal
            applied = self._handle_easy_apply_modal(resume_pdf_path)

            if applied:
                result["status"] = "applied"
                result["message"] = "Successfully applied via Easy Apply"
                logger.info("✅ Successfully applied to: %s @ %s", job.title, job.company)
            else:
                result["status"] = "failed"
                result["message"] = "Easy Apply modal handling failed"
                logger.warning("❌ Failed to complete Easy Apply for: %s @ %s", job.title, job.company)

        except Exception as exc:
            logger.error("Error applying to %s: %s", job.job_id, exc)
            result["status"] = "failed"
            result["message"] = str(exc)

            if self.screenshot_on_error:
                self._save_error_screenshot(job.job_id)

        return result

    def _find_easy_apply_button(self):
        """Find the Easy Apply button on the job page."""
        page = self._page
        selectors = [
            'button.jobs-apply-button:has-text("Easy Apply")',
            'button:has-text("Easy Apply")',
            'button[aria-label*="Easy Apply"]',
            '.jobs-apply-button--top-card button',
            '.jobs-s-apply button:has-text("Easy Apply")',
        ]
        for sel in selectors:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    return btn
            except Exception:
                continue
        return None

    def _handle_easy_apply_modal(self, resume_pdf_path: Optional[str] = None) -> bool:
        """
        Handle the multi-step Easy Apply modal.
        Steps typically include:
          1. Contact info (pre-filled)
          2. Resume upload
          3. Additional questions
          4. Review & Submit
        Returns True if application was submitted successfully.
        """
        page = self._page
        max_steps = 10  # safety limit

        for step in range(max_steps):
            self._human_delay(1, 2)

            # Wait for modal to be present
            modal = page.query_selector(
                '.jobs-easy-apply-modal, '
                '.artdeco-modal--layer-default, '
                '[data-test-modal], '
                '.jobs-easy-apply-content'
            )
            if not modal:
                logger.debug("No modal found at step %d", step)
                # Check if we successfully submitted (modal disappeared after submit)
                if step > 0:
                    return self._check_application_success()
                return False

            # Try to upload resume if we have one and there's a file input
            if resume_pdf_path:
                self._try_upload_resume(resume_pdf_path)

            # Try to fill in contact information
            self._try_fill_contact_info()

            # Try to answer common form questions
            self._try_answer_questions()

            # Check for the submit button (final step)
            submit_btn = page.query_selector(
                'button[aria-label*="Submit application"], '
                'button:has-text("Submit application"), '
                'button[data-easy-apply-next-button]:has-text("Submit")'
            )
            if submit_btn and submit_btn.is_visible():
                logger.info("Found Submit button — submitting application …")
                submit_btn.click()
                self._human_delay(2, 4)
                return self._check_application_success()

            # Look for "Review" button (step before submit)
            review_btn = page.query_selector(
                'button[aria-label*="Review"], '
                'button:has-text("Review your application"), '
                'button:has-text("Review")'
            )
            if review_btn and review_btn.is_visible():
                logger.info("Clicking Review …")
                review_btn.click()
                self._human_delay(1, 2)
                continue

            # Look for "Next" button
            next_btn = page.query_selector(
                'button[aria-label="Continue to next step"], '
                'button:has-text("Next"), '
                'button[data-easy-apply-next-button]'
            )
            if next_btn and next_btn.is_visible():
                logger.info("Clicking Next (step %d) …", step + 1)
                next_btn.click()
                self._human_delay(1, 2)
                continue

            # No recognizable button found — might be stuck
            logger.warning("No Next/Submit/Review button found at step %d", step)

            # Try to dismiss any error messages or validation issues
            error_msgs = page.query_selector_all('.artdeco-inline-feedback--error')
            if error_msgs:
                logger.warning("Form has validation errors — cannot proceed")
                for err in error_msgs:
                    logger.warning("  Error: %s", err.text_content())
                return False

            break

        return False

    def _try_upload_resume(self, resume_pdf_path: str) -> None:
        """Try to upload the tailored resume PDF if a file input is available."""
        page = self._page
        if not os.path.exists(resume_pdf_path):
            logger.warning("Resume PDF not found: %s", resume_pdf_path)
            return

        try:
            # Look for file input elements (they're usually hidden)
            file_inputs = page.query_selector_all('input[type="file"]')
            for file_input in file_inputs:
                try:
                    file_input.set_input_files(resume_pdf_path)
                    logger.info("📎 Uploaded resume: %s", os.path.basename(resume_pdf_path))
                    self._human_delay(1, 2)
                    return
                except Exception:
                    continue

            # Alternative: look for "Upload resume" button and use it
            upload_btn = page.query_selector(
                'button:has-text("Upload resume"), '
                'label:has-text("Upload resume"), '
                '[aria-label*="upload" i]'
            )
            if upload_btn:
                # Clicking upload button should trigger a file dialog
                # Use Playwright's file chooser handler
                with page.expect_file_chooser(timeout=5000) as fc_info:
                    upload_btn.click()
                file_chooser = fc_info.value
                file_chooser.set_files(resume_pdf_path)
                logger.info("📎 Uploaded resume via button: %s", os.path.basename(resume_pdf_path))
                self._human_delay(1, 2)

        except Exception as exc:
            logger.debug("Resume upload attempt: %s (may not be needed on this step)", exc)

    def _try_fill_contact_info(self) -> None:
        """Try to fill in contact info fields if they're empty."""
        page = self._page
        field_mappings = [
            # (label patterns, value)
            (["email", "e-mail"], self.candidate_email),
            (["phone", "mobile", "telephone"], self.candidate_phone),
            (["city", "location"], self.candidate_location),
        ]

        for label_patterns, value in field_mappings:
            if not value:
                continue
            for pattern in label_patterns:
                try:
                    # Find input by label
                    inputs = page.query_selector_all(f'input')
                    for inp in inputs:
                        label_elem = None
                        input_id = inp.get_attribute("id")
                        if input_id:
                            label_elem = page.query_selector(f'label[for="{input_id}"]')

                        aria_label = inp.get_attribute("aria-label") or ""
                        placeholder = inp.get_attribute("placeholder") or ""
                        label_text = label_elem.text_content().lower() if label_elem else ""

                        if (pattern in label_text or
                                pattern in aria_label.lower() or
                                pattern in placeholder.lower()):
                            current_val = inp.input_value()
                            if not current_val or not current_val.strip():
                                inp.fill(value)
                                logger.info("Filled '%s' field", pattern)
                                break
                except Exception:
                    continue

    def _try_answer_questions(self) -> None:
        """
        Try to handle common Easy Apply additional questions.
        Uses safe defaults — skips questions it can't answer.
        """
        page = self._page

        try:
            # Handle radio buttons — look for "Yes" options for common questions
            # like "Are you authorized to work?" / "Will you require sponsorship?"
            fieldsets = page.query_selector_all('fieldset')
            for fieldset in fieldsets:
                legend = fieldset.query_selector('legend, span.fb-dash-form-element__label')
                if not legend:
                    continue

                legend_text = legend.text_content().lower()

                # Authorization to work — select "Yes"
                if any(kw in legend_text for kw in ["authorized", "authorised", "legally", "right to work"]):
                    self._select_radio(fieldset, "yes")

                # Sponsorship — select "No" (we don't need sponsorship usually)
                elif "sponsorship" in legend_text:
                    self._select_radio(fieldset, "no")

            # Handle select dropdowns for years of experience
            selects = page.query_selector_all('select')
            for select in selects:
                select_id = select.get_attribute("id") or ""
                label_elem = page.query_selector(f'label[for="{select_id}"]') if select_id else None
                label_text = label_elem.text_content().lower() if label_elem else ""

                if "experience" in label_text or "years" in label_text:
                    options = select.query_selector_all('option')
                    # Try to select a reasonable experience value
                    for opt in options:
                        val = opt.get_attribute("value") or ""
                        text = opt.text_content().strip()
                        if val and text and text != "Select an option":
                            # Pick a high value for senior roles
                            if any(n in text for n in ["5", "6", "7", "8", "9", "10"]):
                                select.select_option(value=val)
                                logger.info("Selected experience: %s", text)
                                break

            # Handle text inputs for numeric questions (e.g., "Years of experience with Python")
            text_inputs = page.query_selector_all('input[type="text"], input[type="number"]')
            for inp in text_inputs:
                input_id = inp.get_attribute("id") or ""
                label_elem = page.query_selector(f'label[for="{input_id}"]') if input_id else None
                label_text = label_elem.text_content().lower() if label_elem else ""
                aria_label = (inp.get_attribute("aria-label") or "").lower()

                full_label = label_text + " " + aria_label

                if "year" in full_label and "experience" in full_label:
                    current = inp.input_value()
                    if not current or not current.strip():
                        inp.fill("5")
                        logger.info("Filled years of experience: 5")

        except Exception as exc:
            logger.debug("Question answering: %s", exc)

    def _select_radio(self, fieldset, target_value: str) -> None:
        """Select a radio button by label text within a fieldset."""
        labels = fieldset.query_selector_all('label')
        for label in labels:
            label_text = label.text_content().strip().lower()
            if label_text == target_value.lower():
                label.click()
                logger.info("Selected radio: '%s'", target_value)
                return

    def _check_application_success(self) -> bool:
        """Check if the application was submitted successfully."""
        page = self._page
        self._human_delay(1, 2)

        try:
            # Look for success indicators
            success_indicators = [
                'h3:has-text("Your application was sent")',
                'h3:has-text("Application submitted")',
                ':text("Your application was sent")',
                ':text("application was submitted")',
                '.artdeco-modal:has-text("Application sent")',
                '.artdeco-modal:has-text("Your application was sent")',
            ]
            for selector in success_indicators:
                try:
                    el = page.query_selector(selector)
                    if el:
                        logger.info("✅ Detected success: %s", el.text_content().strip()[:50])
                        # Dismiss the success modal
                        dismiss_btn = page.query_selector(
                            'button[aria-label="Dismiss"], '
                            'button:has-text("Done"), '
                            'button:has-text("Close")'
                        )
                        if dismiss_btn:
                            dismiss_btn.click()
                            self._human_delay(1, 2)
                        return True
                except Exception:
                    continue

            # Check if modal disappeared (which often means success)
            modal = page.query_selector('.jobs-easy-apply-modal, .artdeco-modal')
            if not modal:
                # Modal gone — likely success
                return True

        except Exception as exc:
            logger.debug("Success check: %s", exc)

        return False

    def _save_error_screenshot(self, job_id: str) -> None:
        """Save a screenshot for debugging failed applications."""
        try:
            screenshot_dir = "output/screenshots"
            os.makedirs(screenshot_dir, exist_ok=True)
            path = os.path.join(screenshot_dir, f"error_{job_id}.png")
            self._page.screenshot(path=path)
            logger.info("Error screenshot saved: %s", path)
        except Exception as exc:
            logger.debug("Could not save screenshot: %s", exc)

    # ── Helpers ────────────────────────────────────────────────────

    def _human_delay(self, min_s: float = 1.0, max_s: float = 3.0) -> None:
        """Random delay to mimic human behavior."""
        delay = random.uniform(min_s, max_s)
        time.sleep(delay)

    # ── Context Manager ───────────────────────────────────────────

    def __enter__(self):
        self.start_browser()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close_browser()
        return False


def login_only(config: Optional[dict] = None) -> None:
    """Utility: open browser for LinkedIn login setup only."""
    ea = LinkedInEasyApply(config)
    ea.start_browser()
    logged_in = ea.ensure_logged_in()
    if logged_in:
        print("\n✅ Login successful! Session saved.")
        print(f"   Profile dir: {ea.profile_dir}")
        print("   You can close this browser now.\n")
        input("Press Enter to close the browser …")
    else:
        print("\n❌ Login failed or timed out.\n")
    ea.close_browser()
