"""
Standalone script to tailor a resume PDF for a specific job.

Usage:
    python scripts/tailor_resume.py
"""

import os
import re
import sys

# Ensure project root is on the path so we can import the optimizer
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.optimizers.resume_optimizer import ResumeOptimizer
from src.models.job import Job


def tailor_for_skills(skills_csv: str, job_title: str = "Target Role",
                      company: str = "Target Company") -> str:
    """
    Generate a tailored resume PDF with the given skills highlighted.
    Returns the output file path.
    """
    optimizer = ResumeOptimizer()
    optimizer.load_resume()

    # Create a mock job with the provided info
    skills_list = [s.strip() for s in skills_csv.split(",") if s.strip()]

    job = Job(
        job_id="manual",
        title=job_title,
        company=company,
        location="",
        description=" ".join(skills_list),
        url="",
        matched_skills=skills_list,
    )

    pdf_path = optimizer.generate_tailored_pdf(job)
    return pdf_path


if __name__ == "__main__":
    # Example usage — customize these for your target job
    tailored_skills = "Python, AWS, Kubernetes, Docker, Geospatial, PostGIS, STAC, Airflow, Terraform, FastAPI, distributed systems"
    job_title = "Senior Geospatial Engineer"
    company = "Planet Labs"

    pdf_path = tailor_for_skills(tailored_skills, job_title, company)
    size = os.path.getsize(pdf_path)
    print(f"✅ Tailored resume generated: {pdf_path}")
    print(f"   Size: {size:,} bytes")
