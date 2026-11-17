import itertools
import unittest

from elda_qgis.core.publish import polling


class WaitsTest(unittest.TestCase):
    def test_waits_ramp_up_then_stay_at_fifteen(self):
        self.assertEqual(list(itertools.islice(polling.waits(), 9)), [2, 3, 5, 8, 12, 15, 15, 15, 15])

    def test_max_wait_is_thirty_minutes(self):
        self.assertEqual(polling.MAX_WAIT_SECONDS, 1800)
