import unittest
from src.analyzers.job_analyzer import JobAnalyzer

class TestJobAnalyzer(unittest.TestCase):

    def setUp(self):
        self.job_analyzer = JobAnalyzer()

    def test_analyze_job_description(self):
        job_description = "Looking for a software engineer with experience in Python and machine learning."
        expected_keywords = ["software engineer", "Python", "machine learning"]
        actual_keywords = self.job_analyzer.analyze_job_description(job_description)
        self.assertEqual(actual_keywords, expected_keywords)

    def test_analyze_job_description_empty(self):
        job_description = ""
        expected_keywords = []
        actual_keywords = self.job_analyzer.analyze_job_description(job_description)
        self.assertEqual(actual_keywords, expected_keywords)

    def test_analyze_job_description_no_keywords(self):
        job_description = "This is a generic job description with no specific requirements."
        expected_keywords = []
        actual_keywords = self.job_analyzer.analyze_job_description(job_description)
        self.assertEqual(actual_keywords, expected_keywords)

if __name__ == '__main__':
    unittest.main()