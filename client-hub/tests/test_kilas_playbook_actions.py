"""Independent test class: do not expose/import an inherited unittest fixture."""
import unittest
import test_kilas_jobs_store as phase4
import kilas_jobs_cases
import kilas_playbook_cases


class PlaybookActionsTests(kilas_playbook_cases.ActionCases, unittest.TestCase):
    def setUp(self):
        phase4.JobsTests.setUp(self)
        self.reset_web()
    seed = kilas_jobs_cases.Cases.seed


if __name__ == '__main__': unittest.main()
