import unittest
from src.submitters.application_submitter import ApplicationSubmitter

class TestApplicationSubmitter(unittest.TestCase):

    def setUp(self):
        self.submitter = ApplicationSubmitter()

    def test_submit_application_success(self):
        job_id = "12345"
        resume = "Sample resume content"
        result = self.submitter.submit_application(job_id, resume)
        self.assertTrue(result)  # Assuming submit_application returns True on success

    def test_submit_application_failure(self):
        job_id = "invalid_id"
        resume = "Sample resume content"
        result = self.submitter.submit_application(job_id, resume)
        self.assertFalse(result)  # Assuming submit_application returns False on failure

if __name__ == '__main__':
    unittest.main()