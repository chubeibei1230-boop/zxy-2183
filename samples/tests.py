from django.test import TestCase
from django.utils import timezone

from .models import BurnTest, StatusChoices, WaxSample


class BurnTestStatusFlowTests(TestCase):
    def create_sample(self, status):
        return WaxSample.objects.create(
            sample_code=f'S-{status}',
            cup_type='杯型A',
            fragrance_code='F01',
            wick_spec='W01',
            test_batch=f'B-{status}',
            responsible_person='张三',
            status=status,
        )

    def test_in_progress_retest_keeps_pending_retest_status(self):
        sample = self.create_sample(StatusChoices.PENDING_RETEST)

        BurnTest.objects.create(
            wax_sample=sample,
            test_round=2,
            is_retest=True,
            ignite_time=timezone.now(),
        )

        sample.refresh_from_db()
        self.assertEqual(sample.status, StatusChoices.PENDING_RETEST)

    def test_in_progress_initial_test_still_becomes_in_test(self):
        sample = self.create_sample(StatusChoices.PENDING_TEST)

        BurnTest.objects.create(
            wax_sample=sample,
            test_round=1,
            is_retest=False,
            ignite_time=timezone.now(),
        )

        sample.refresh_from_db()
        self.assertEqual(sample.status, StatusChoices.IN_TEST)
