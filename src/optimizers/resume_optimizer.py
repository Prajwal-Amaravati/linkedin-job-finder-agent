"""
Resume Optimizer — reads the candidate's PDF resume and generates a
tailored, professionally-formatted version for each job.
"""

import logging
import os
import re
from typing import List, Optional, Tuple

from src.models.job import Job
from src.models.resume import Resume
from src.utils.config import load_config, get_candidate_info, get_resume_optimizer_settings

logger = logging.getLogger(__name__)

# ── Comprehensive known-skills list ─────────────────────────────────
# Used for both extraction from resume text AND matching in job descriptions.
_KNOWN_SKILLS: List[str] = [
    # Languages
    "Python", "Java", "JavaScript", "TypeScript", "Go", "Rust", "C++", "C#",
    "Scala", "Ruby", "PHP", "Swift", "Kotlin", "R", "Shell Scripting", "Bash",
    "SQL", "GraphQL", "HTML", "CSS",
    # Frameworks & Libraries
    "FastAPI", "Flask", "Django", "Spring Boot", "React", "Next.js", "Node.js",
    "Express", "Vue.js", "Angular", "Svelte", "Rails", "ASP.NET",
    "Pandas", "NumPy", "SciPy", "scikit-learn", "TensorFlow", "PyTorch",
    "LangGraph", "LangChain", "OpenAI", "Hugging Face",
    # Cloud & Infrastructure
    "AWS", "Azure", "GCP", "Google Cloud", "Terraform", "Pulumi",
    "CloudFormation", "Ansible", "Chef", "Puppet",
    # Containers & Orchestration
    "Docker", "Kubernetes", "Helm", "Istio", "OpenShift",
    "ECS", "EKS", "Fargate", "Lambda",
    # Data & Databases
    "PostgreSQL", "PostGIS", "MySQL", "MongoDB", "Redis", "Elasticsearch",
    "Cassandra", "DynamoDB", "SQLite", "Oracle", "SQL Server",
    "Snowflake", "BigQuery", "Redshift", "ClickHouse",
    # Data Processing & Orchestration
    "Airflow", "Dask", "Spark", "Kafka", "RabbitMQ", "Celery", "Ray",
    "Flink", "Prefect", "Dagster", "dbt",
    # DevOps & Monitoring
    "CI/CD", "Jenkins", "GitHub Actions", "GitLab CI", "ArgoCD",
    "Prometheus", "Grafana", "Datadog", "New Relic", "ELK Stack",
    "Splunk", "PagerDuty", "Sentry",
    # Geospatial
    "geospatial", "GIS", "QGIS", "ArcGIS", "GDAL", "Rasterio",
    "GeoPandas", "Shapely", "Fiona", "PostGIS", "STAC",
    "openEO", "Sentinel-2", "Landsat", "remote sensing",
    "earth observation", "satellite imagery", "LiDAR", "point cloud",
    "spatial data", "coordinate reference systems", "map tiles",
    "vector tiles", "raster processing", "COG",
    # MLOps & AI
    "MLOps", "MLflow", "KServe", "SageMaker", "Kubeflow",
    "TFX", "Feature Store", "Model Registry", "A/B Testing",
    "machine learning", "deep learning", "NLP", "computer vision",
    "LLM", "RAG", "fine-tuning",
    # Architecture & Patterns
    "microservices", "distributed systems", "event-driven",
    "REST API", "gRPC", "WebSocket", "API Gateway",
    "message queue", "CQRS", "domain-driven design",
    "edge computing", "serverless",
    # Methodologies & Tools
    "Git", "Agile", "Scrum", "Kanban", "TDD", "BDD",
    "code review", "pair programming", "system design",
    "technical leadership", "mentoring",
    "Linux", "Nginx", "Apache",
]

# Lowercase lookup set for fast matching
_SKILLS_LOWER = {s.lower(): s for s in _KNOWN_SKILLS}


class ResumeOptimizer:
    """Load a resume, extract content, and produce tailored versions."""

    # Regex patterns for detecting resume section headers
    _SECTION_PATTERNS = [
        re.compile(r"^(SUMMARY|PROFESSIONAL SUMMARY|PROFILE|OBJECTIVE)", re.IGNORECASE),
        re.compile(r"^(SKILLS|TECHNICAL SKILLS|KEY SKILLS|CORE COMPETENCIES|TECHNOLOGIES)", re.IGNORECASE),
        re.compile(r"^(EXPERIENCE|WORK EXPERIENCE|PROFESSIONAL EXPERIENCE|EMPLOYMENT)", re.IGNORECASE),
        re.compile(r"^(EDUCATION|ACADEMIC|QUALIFICATIONS)", re.IGNORECASE),
        re.compile(r"^(PROJECTS|KEY PROJECTS|NOTABLE PROJECTS)", re.IGNORECASE),
        re.compile(r"^(CERTIFICATIONS?|LICENSES?|AWARDS?|ACHIEVEMENTS?)", re.IGNORECASE),
        re.compile(r"^(PUBLICATIONS?|PATENTS?|CONFERENCES?)", re.IGNORECASE),
        re.compile(r"^(VOLUNTEER|INTERESTS|HOBBIES|LANGUAGES|REFERENCES)", re.IGNORECASE),
    ]

    def __init__(self, config: Optional[dict] = None):
        self.config = config or load_config()
        candidate = get_candidate_info(self.config)
        opt_cfg = get_resume_optimizer_settings(self.config)

        self.resume_path = candidate.get("resume_path", "")
        self.candidate_name = candidate.get("name", "")
        self.candidate_email = candidate.get("email", "")
        self.candidate_phone = candidate.get("phone", "")
        self.candidate_location = candidate.get("location", "")
        self.max_keywords = opt_cfg.get("max_keywords", 15)
        self.output_dir = opt_cfg.get("output_dir", "output/resumes")

        self._resume_text: Optional[str] = None

    # ── Public API ─────────────────────────────────────────────────

    def load_resume(self) -> Resume:
        """Load and parse the candidate's PDF resume."""
        text = self._extract_pdf_text(self.resume_path)
        self._resume_text = text

        skills = self._extract_skills(text)

        return Resume(
            content=text,
            file_path=self.resume_path,
            candidate_name=self.candidate_name,
            candidate_email=self.candidate_email,
            skills=skills,
        )

    def optimize_resume(self, keywords: List[str]) -> str:
        """
        Produce a keyword-optimized resume with the skills section
        updated in-place to highlight matched keywords.
        """
        if self._resume_text is None:
            self.load_resume()

        # De-duplicate and pick top N real skills
        tailored_skills = self._resolve_real_skills(keywords)

        # Update the skills section in-place
        updated_text = self._update_skills_section(
            self._resume_text or "", tailored_skills
        )

        return updated_text

    def optimize_for_job(self, job: Job) -> str:
        """Optimize resume specifically for a Job object using real skill matching."""
        # Start with the already-matched skills from the analyzer
        job_skills: List[str] = list(job.matched_skills) if job.matched_skills else []

        # Also extract real skills from the job description text
        if job.description:
            desc_skills = self._extract_skills(job.description)
            job_skills.extend(desc_skills)

        return self.optimize_resume(job_skills)

    def generate_tailored_pdf(self, job: Job) -> str:
        """
        Generate a tailored, professionally-formatted resume PDF for a
        specific job. Uses reportlab for high-quality output.
        """
        os.makedirs(self.output_dir, exist_ok=True)

        # Sanitize filename
        safe_company = re.sub(r"[^\w\s-]", "", job.company).strip().replace(" ", "_")
        safe_title = re.sub(r"[^\w\s-]", "", job.title).strip().replace(" ", "_")
        filename = f"Resume_{self.candidate_name.replace(' ', '_')}_{safe_company}_{safe_title[:30]}.pdf"
        filepath = os.path.join(self.output_dir, filename)

        # Build tailored content
        tailored_text = self.optimize_for_job(job)

        # Parse into structured sections
        sections = self._parse_sections(tailored_text)

        # Generate with reportlab (primary) or FPDF (fallback)
        return self._generate_reportlab_pdf(filepath, sections, job)

    def get_resume_text(self) -> str:
        """Return raw resume text (loading if needed)."""
        if self._resume_text is None:
            self.load_resume()
        return self._resume_text or ""

    # ── Professional PDF Generation (reportlab) ───────────────────

    def _generate_reportlab_pdf(self, filepath: str,
                                 sections: List[Tuple[str, List[str]]],
                                 job: Job) -> str:
        """Generate a professionally formatted PDF using reportlab."""
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import inch, mm
            from reportlab.lib.colors import HexColor
            from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
            from reportlab.platypus import (
                SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table,
                TableStyle, KeepTogether,
            )

            # ── Page setup ────────────────────────────────────────
            doc = SimpleDocTemplate(
                filepath,
                pagesize=A4,
                leftMargin=0.6 * inch,
                rightMargin=0.6 * inch,
                topMargin=0.5 * inch,
                bottomMargin=0.5 * inch,
            )

            # ── Styles ────────────────────────────────────────────
            styles = getSampleStyleSheet()

            style_name = ParagraphStyle(
                "ResumeName",
                parent=styles["Title"],
                fontSize=18,
                leading=22,
                alignment=TA_CENTER,
                spaceAfter=2,
                textColor=HexColor("#1a1a2e"),
                fontName="Helvetica-Bold",
            )
            style_contact = ParagraphStyle(
                "ResumeContact",
                parent=styles["Normal"],
                fontSize=9,
                leading=12,
                alignment=TA_CENTER,
                spaceAfter=6,
                textColor=HexColor("#555555"),
                fontName="Helvetica",
            )
            style_section_header = ParagraphStyle(
                "SectionHeader",
                parent=styles["Heading2"],
                fontSize=11,
                leading=14,
                spaceBefore=10,
                spaceAfter=4,
                textColor=HexColor("#1a1a2e"),
                fontName="Helvetica-Bold",
                borderWidth=0,
                borderPadding=0,
            )
            style_body = ParagraphStyle(
                "ResumeBody",
                parent=styles["Normal"],
                fontSize=9.5,
                leading=12,
                alignment=TA_JUSTIFY,
                fontName="Helvetica",
                textColor=HexColor("#2d2d2d"),
            )
            style_bullet = ParagraphStyle(
                "ResumeBullet",
                parent=style_body,
                leftIndent=14,
                firstLineIndent=-10,
                spaceBefore=1,
                spaceAfter=1,
            )
            style_sub_header = ParagraphStyle(
                "SubHeader",
                parent=styles["Normal"],
                fontSize=10,
                leading=13,
                fontName="Helvetica-Bold",
                textColor=HexColor("#333333"),
                spaceBefore=4,
                spaceAfter=1,
            )

            # ── Build flowables ───────────────────────────────────
            story = []

            # Name
            story.append(Paragraph(self._rl_escape(self.candidate_name), style_name))

            # Contact line
            contact_parts = []
            if self.candidate_email:
                contact_parts.append(self.candidate_email)
            if self.candidate_phone:
                contact_parts.append(self.candidate_phone)
            if self.candidate_location:
                contact_parts.append(self.candidate_location)
            if contact_parts:
                story.append(Paragraph(
                    self._rl_escape("  |  ".join(contact_parts)),
                    style_contact,
                ))

            # Thin horizontal rule
            story.append(Spacer(1, 4))
            story.append(HRFlowable(
                width="100%", thickness=0.8,
                color=HexColor("#cccccc"), spaceAfter=6,
            ))

            # ── Sections ──────────────────────────────────────────
            for section_title, lines in sections:
                if not section_title and not lines:
                    continue

                # Section header
                if section_title:
                    header_text = section_title.upper()
                    story.append(Paragraph(self._rl_escape(header_text), style_section_header))
                    story.append(HRFlowable(
                        width="100%", thickness=0.4,
                        color=HexColor("#dddddd"), spaceAfter=4,
                    ))

                for line in lines:
                    stripped = line.strip()
                    if not stripped:
                        story.append(Spacer(1, 3))
                        continue

                    # Detect bullet points (Unicode and ASCII)
                    is_bullet = bool(re.match(r'^[\u25cf\u2022\u25aa\u25ba\-\*]\s', stripped))
                    if is_bullet:
                        bullet_text = re.sub(r'^[\u25cf\u2022\u25aa\u25ba\-\*]\s*', '', stripped).strip()
                        story.append(Paragraph(
                            "\u2022  " + self._rl_escape(bullet_text),
                            style_bullet,
                        ))
                    # Detect sub-headers (company/role lines)
                    elif self._looks_like_role_line(stripped):
                        story.append(Paragraph(
                            self._rl_escape(stripped),
                            style_sub_header,
                        ))
                    else:
                        story.append(Paragraph(
                            self._rl_escape(stripped),
                            style_body,
                        ))

            # Build PDF
            doc.build(story)
            logger.info("Generated professional PDF: %s", filepath)
            return filepath

        except ImportError as exc:
            logger.warning("reportlab not available (%s), falling back to FPDF", exc)
            return self._generate_fpdf_fallback(filepath, sections, job)

    def _generate_fpdf_fallback(self, filepath: str,
                                 sections: List[Tuple[str, List[str]]],
                                 job: Job) -> str:
        """Fallback PDF generator using FPDF with basic formatting."""
        try:
            from fpdf import FPDF

            pdf = FPDF()
            pdf.add_page()
            pdf.set_auto_page_break(auto=True, margin=15)

            # Title
            pdf.set_font("Helvetica", "B", 16)
            pdf.cell(0, 10, self._to_latin1(self.candidate_name), ln=1, align="C")

            # Contact
            pdf.set_font("Helvetica", "", 9)
            contact_parts = [p for p in [self.candidate_email, self.candidate_phone, self.candidate_location] if p]
            if contact_parts:
                pdf.cell(0, 6, self._to_latin1("  |  ".join(contact_parts)), ln=1, align="C")
            pdf.ln(4)

            # Separator
            pdf.set_draw_color(180, 180, 180)
            pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
            pdf.ln(4)

            # Sections
            for section_title, lines in sections:
                if section_title:
                    pdf.set_font("Helvetica", "B", 11)
                    pdf.cell(0, 7, self._to_latin1(section_title.upper()), ln=1)
                    pdf.set_draw_color(200, 200, 200)
                    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
                    pdf.ln(2)

                pdf.set_font("Helvetica", "", 9)
                for line in lines:
                    stripped = line.strip()
                    if not stripped:
                        pdf.ln(2)
                        continue

                    is_bullet = bool(re.match(r'^[\u25cf\u2022\u25aa\u25ba\-\*]\s', stripped))
                    if is_bullet:
                        bullet_text = re.sub(r'^[\u25cf\u2022\u25aa\u25ba\-\*]\s*', '', stripped).strip()
                        pdf.cell(5)
                        pdf.multi_cell(0, 5, self._to_latin1("*  " + bullet_text))
                    elif self._looks_like_role_line(stripped):
                        pdf.set_font("Helvetica", "B", 10)
                        pdf.multi_cell(0, 5, self._to_latin1(stripped))
                        pdf.set_font("Helvetica", "", 9)
                    else:
                        pdf.multi_cell(0, 5, self._to_latin1(stripped))

                pdf.ln(2)

            pdf.output(filepath)
            logger.info("Generated FPDF fallback PDF: %s", filepath)
            return filepath

        except ImportError:
            # Absolute last resort: save as text
            txt_path = filepath.replace(".pdf", ".txt")
            with open(txt_path, "w") as f:
                for title, lines in sections:
                    if title:
                        f.write(f"\n{'=' * 40}\n{title.upper()}\n{'=' * 40}\n")
                    f.write("\n".join(lines) + "\n")
            logger.warning("No PDF library available -- saved as text: %s", txt_path)
            return txt_path

    # ── Skills Section Update ─────────────────────────────────────

    def _resolve_real_skills(self, keywords: List[str]) -> List[str]:
        """
        Given a list of keywords (from job description or matched_skills),
        resolve them to canonical skill names from our known-skills list.
        De-duplicate and limit to max_keywords.
        """
        seen = set()
        resolved = []

        for kw in keywords:
            kw_lower = kw.lower().strip()
            # Direct match in our known skills
            if kw_lower in _SKILLS_LOWER and kw_lower not in seen:
                seen.add(kw_lower)
                resolved.append(_SKILLS_LOWER[kw_lower])

        # Also add any skills from the resume that weren't already included
        if self._resume_text:
            resume_skills = self._extract_skills(self._resume_text)
            for skill in resume_skills:
                if skill.lower() not in seen:
                    seen.add(skill.lower())
                    resolved.append(skill)

        return resolved[:self.max_keywords]

    def _update_skills_section(self, text: str, skills: List[str]) -> str:
        """
        Find the Skills section in the resume text and replace it
        with the tailored skills list. If no Skills section is found,
        insert one after the first section header.
        """
        if not skills:
            return text

        skills_line = ", ".join(skills)

        # Try to find and replace the Skills section
        skills_pattern = re.compile(
            r"((?:TECHNICAL\s+)?SKILLS|KEY\s+SKILLS|CORE\s+COMPETENCIES|TECHNOLOGIES)"
            r"[:\s]*\n"
            r"(.*?)"
            r"(?=\n(?:EXPERIENCE|WORK\s+EXPERIENCE|PROFESSIONAL\s+EXPERIENCE|EDUCATION|"
            r"PROJECTS|CERTIFICATIONS?|SUMMARY|PROFILE|PUBLICATIONS?|$))",
            re.IGNORECASE | re.DOTALL,
        )

        match = skills_pattern.search(text)
        if match:
            section_header = match.group(1)
            replacement = f"{section_header}\n{skills_line}\n"
            return text[:match.start()] + replacement + text[match.end():]

        # Fallback: no skills section found -- insert after first section
        lines = text.split("\n")
        insert_idx = 0
        for i, line in enumerate(lines):
            if any(p.match(line.strip()) for p in self._SECTION_PATTERNS):
                insert_idx = i
                break

        if insert_idx > 0:
            lines.insert(insert_idx, f"\nSKILLS\n{skills_line}\n")

        return "\n".join(lines)

    # ── Section Parsing ───────────────────────────────────────────

    def _parse_sections(self, text: str) -> List[Tuple[str, List[str]]]:
        """
        Parse resume text into structured sections.
        Returns a list of (section_title, [lines]) tuples.
        """
        sections: List[Tuple[str, List[str]]] = []
        current_title = ""
        current_lines: List[str] = []
        found_first_header = False

        for line in text.split("\n"):
            stripped = line.strip()

            # Check if this line is a section header
            is_header = False
            for pattern in self._SECTION_PATTERNS:
                if pattern.match(stripped):
                    is_header = True
                    break

            # Also detect ALL-CAPS lines as headers (common in resumes)
            if not is_header and stripped and len(stripped) > 3:
                words = stripped.split()
                if (len(words) <= 5 and
                        stripped == stripped.upper() and
                        any(c.isalpha() for c in stripped)):
                    is_header = True

            if is_header:
                found_first_header = True
                # Save previous section
                if current_title or current_lines:
                    sections.append((current_title, current_lines))
                current_title = stripped.title()
                current_lines = []
            elif found_first_header:
                # Only include lines after we've seen the first header
                # (skips preamble contact info which is rendered from config)
                current_lines.append(line)

        # Don't forget the last section
        if current_title or current_lines:
            sections.append((current_title, current_lines))

        return sections

    # ── Helpers ────────────────────────────────────────────────────

    def _extract_pdf_text(self, path: str) -> str:
        """Extract text from a PDF file and reconstruct proper lines."""
        try:
            from PyPDF2 import PdfReader

            reader = PdfReader(path)
            pages = [page.extract_text() or "" for page in reader.pages]
            raw_text = "\n".join(pages)
            # Reconstruct proper lines from fragmented PDF extraction
            text = self._reconstruct_lines(raw_text)
            logger.info("Extracted %d characters from %s", len(text), path)
            return text.strip()
        except Exception as exc:
            logger.error("Failed to extract PDF text from %s: %s", path, exc)
            return ""

    @staticmethod
    def _reconstruct_lines(raw: str) -> str:
        """
        PyPDF2 often extracts each word on its own line, e.g.:
            'Prajwal\\n \\nS\\n \\nBangalore,\\n \\nIndia'
        This method detects logical line boundaries (bullets, numbered
        items, section headers) and joins fragments back into readable lines.
        """
        # Bullet characters used in resumes
        BULLET_CHARS = '\u25cf\u2022\u25aa\u25ba'

        # Known ALL-CAPS section header words
        HEADER_WORDS = {
            'WORK', 'EXPERIENCE', 'EDUCATION', 'SKILLS', 'PROJECTS',
            'SUMMARY', 'PROFILE', 'OBJECTIVE', 'CERTIFICATIONS',
            'ACHIEVEMENTS', 'AWARDS', 'PUBLICATIONS', 'VOLUNTEER',
            'INTERESTS', 'REFERENCES', 'LANGUAGES', 'TECHNICAL',
            'PROFESSIONAL', 'EMPLOYMENT', 'QUALIFICATIONS', 'KEY',
            'CORE', 'COMPETENCIES', 'TECHNOLOGIES', 'NOTABLE',
        }

        # Split into individual fragments
        fragments = raw.split("\n")

        # Patterns that indicate a NEW logical line
        # Match: bullet+space, OR standalone bullet char, OR numbered items
        bullet_re = re.compile(r'^\s*[' + re.escape(BULLET_CHARS) + r']\s*$|^\s*[' + re.escape(BULLET_CHARS) + r']\s')
        numbered_re = re.compile(r'^\s*\d{1,2}\.\s')

        lines: List[str] = []
        current_words: List[str] = []

        for frag in fragments:
            stripped = frag.strip()

            # Skip empty / whitespace-only fragments
            if not stripped:
                continue

            # Check if this fragment starts a new logical line:
            # 1. Bullet char (standalone or with text)
            # 2. Numbered item (1. 2. etc.)
            # 3. Standalone ALL-CAPS header word (WORK, EXPERIENCE, etc.)
            is_bullet = bullet_re.match(stripped)
            is_numbered = numbered_re.match(stripped)
            is_header_word = (stripped.upper() == stripped and
                              stripped in HEADER_WORDS)

            starts_new = is_bullet or is_numbered or is_header_word

            if starts_new:
                # Flush the current accumulated line
                if current_words:
                    lines.append(" ".join(current_words))
                    current_words = []
                current_words.append(stripped)
            else:
                current_words.append(stripped)

        # Flush last line
        if current_words:
            lines.append(" ".join(current_words))

        # ── Post-processing ───────────────────────────────────────

        # Step 1: SPLIT lines where an ALL-CAPS header got merged with content.
        #   e.g. "EXPERIENCE SatSure Analytics..." becomes:
        #         "EXPERIENCE"
        #         "SatSure Analytics..."
        #   And "SKILLS &" stays as-is (no non-header content after)
        #   And "INTERESTS Systems Engineering..." becomes:
        #         "INTERESTS"
        #         "Systems Engineering..."
        caps_header_re = re.compile(
            r"^((?:WORK\s+)?EXPERIENCE|EDUCATION|PROJECTS?|"
            r"(?:TECHNICAL\s+)?SKILLS(?:\s+&\s+\w+)?|"
            r"CERTIFICATIONS?|AWARDS?|ACHIEVEMENTS?|"
            r"SUMMARY|PROFESSIONAL\s+SUMMARY|PROFILE|PUBLICATIONS?|"
            r"VOLUNTEER|INTERESTS|REFERENCES|LANGUAGES)"
            r"\s+(.+)$",
            re.IGNORECASE,
        )

        split_lines: List[str] = []
        for line in lines:
            stripped = line.strip()
            m = caps_header_re.match(stripped)
            if m:
                header_part = m.group(1).strip()
                rest_part = m.group(2).strip()
                if header_part == header_part.upper():
                    split_lines.append(header_part)
                    if rest_part:
                        split_lines.append(rest_part)
                else:
                    split_lines.append(line)
            else:
                split_lines.append(line)

        # Step 2: MERGE consecutive standalone ALL-CAPS header lines.
        #   WORK         ──┐
        #   EXPERIENCE   ──┘──→ WORK EXPERIENCE
        #   SKILLS       ──┐
        #   &            ──┤──→ SKILLS & INTERESTS
        #   INTERESTS    ──┘
        expanded: List[str] = []
        i = 0
        while i < len(split_lines):
            line = split_lines[i].strip()
            if line in HEADER_WORDS or (line == '&' and expanded):
                header_parts = [line]
                j = i + 1
                while j < len(split_lines):
                    next_line = split_lines[j].strip()
                    if next_line in HEADER_WORDS or next_line == '&':
                        header_parts.append(next_line)
                        j += 1
                    else:
                        break
                expanded.append(" ".join(header_parts))
                i = j
            else:
                expanded.append(split_lines[i])
                i += 1

        # 2. Fix spacing artifacts within words from PDF glyph extraction
        result = "\n".join(expanded)
        result = re.sub(r" {2,}", " ", result)

        # Fix split email patterns: "s.pr ajwal.amar a v ati@gmail.com"
        # Remove spaces within email-like strings
        def fix_email_spacing(match):
            email = match.group(0)
            return re.sub(r"(?<=\w) (?=\w)", "", email)

        result = re.sub(r"[\w.][\w. ]*@[\w. ]+\.[\w.]+", fix_email_spacing, result)

        return result

    def _extract_skills(self, text: str) -> List[str]:
        """Extract skill keywords from text using the comprehensive known-skills list."""
        text_lower = text.lower()
        found = []
        seen = set()
        for skill_lower, skill_canonical in _SKILLS_LOWER.items():
            if skill_lower in text_lower and skill_lower not in seen:
                seen.add(skill_lower)
                found.append(skill_canonical)
        return found

    @staticmethod
    def _looks_like_role_line(line: str) -> bool:
        """
        Heuristic: detect lines that look like role/company headers.
        e.g. "Senior Engineer -- Planet Labs, San Francisco, CA (2021-2024)"
        """
        # Contains a date range pattern like (2021-2024) or Jan 2021 - Present
        if re.search(r"\b(19|20)\d{2}\b.*\b(19|20)\d{2}\b", line):
            return True
        if re.search(r"\b(19|20)\d{2}\b.*\b(present|current)\b", line, re.IGNORECASE):
            return True
        # Contains an em/en dash separating company name
        if re.search(r"\s[\-\u2013\u2014]\s", line) and len(line) < 120:
            return True
        return False

    @staticmethod
    def _rl_escape(text: str) -> str:
        """Escape text for reportlab Paragraph (XML-like)."""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    @staticmethod
    def _to_latin1(s: str) -> str:
        """Convert text to latin-1 safe string for FPDF."""
        if not isinstance(s, str):
            s = str(s)
        return (
            s.replace("\u2013", "-")
             .replace("\u2014", "-")
             .replace("\u2018", "'")
             .replace("\u2019", "'")
             .replace("\u201c", '"')
             .replace("\u201d", '"')
             .replace("\u2022", "*")
             .encode("latin-1", errors="replace").decode("latin-1")
        )