import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.optimizers.resume_optimizer import ResumeOptimizer
from src.models.job import Job


class TestResumeOptimizer(unittest.TestCase):

    def setUp(self):
        self.optimizer = ResumeOptimizer()
        # Force-load resume so tests can run
        self.optimizer.load_resume()

    def test_optimize_resume_with_known_skills(self):
        """Skills that exist in our known-skills list should appear in the output."""
        keywords = ["Python", "AWS", "Kubernetes"]
        optimized = self.optimizer.optimize_resume(keywords)
        self.assertIn("Python", optimized)
        self.assertIn("AWS", optimized)
        self.assertIn("Kubernetes", optimized)

    def test_optimize_resume_filters_unknown_keywords(self):
        """Random words that aren't real skills should NOT be injected into the resume."""
        keywords = ["xyzfoobar123", "notaskill"]
        optimized = self.optimizer.optimize_resume(keywords)
        self.assertNotIn("xyzfoobar123", optimized)
        self.assertNotIn("notaskill", optimized)

    def test_extract_skills_from_text(self):
        """Known skills should be extracted from text."""
        text = "Experience with Python, Docker, and AWS Lambda on Kubernetes clusters."
        skills = self.optimizer._extract_skills(text)
        self.assertIn("Python", skills)
        self.assertIn("Docker", skills)
        self.assertIn("AWS", skills)
        self.assertIn("Kubernetes", skills)

    def test_generate_tailored_pdf(self):
        """Generate a real PDF and verify it exists and has reasonable size."""
        job = Job(
            job_id="test1",
            title="Senior Engineer",
            company="TestCorp",
            location="Remote",
            description="Looking for Python, Docker, Kubernetes experience.",
            url="https://example.com",
            matched_skills=["python", "docker", "kubernetes"],
        )
        pdf_path = self.optimizer.generate_tailored_pdf(job)
        self.assertTrue(os.path.exists(pdf_path))
        self.assertGreater(os.path.getsize(pdf_path), 5000,
                           "PDF should be > 5KB for a real resume")
        # Clean up
        os.remove(pdf_path)

    def test_resolve_real_skills_deduplicates(self):
        """Resolved skills should be de-duplicated."""
        keywords = ["Python", "python", "PYTHON", "Docker", "docker"]
        skills = self.optimizer._resolve_real_skills(keywords)
        python_count = sum(1 for s in skills if s.lower() == "python")
        docker_count = sum(1 for s in skills if s.lower() == "docker")
        self.assertEqual(python_count, 1)
        self.assertEqual(docker_count, 1)


if __name__ == '__main__':
    unittest.main()