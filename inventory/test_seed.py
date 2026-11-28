from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import Sum
from django.test import TestCase

from .models import (
    DailyClosing,
    Sale,
    StockLevel,
    StockMovement,
    StockTransfer,
    UserProfile,
)


class SeedDemoTests(TestCase):
    def seed(self, **extra):
        call_command("seed_demo", password="Demo-Pass-123!", verbosity=0, **extra)

    def test_demo_data_is_created_and_consistent(self):
        self.seed()
        self.assertEqual(Sale.objects.count(), 5)
        self.assertEqual(DailyClosing.objects.count(), 2)
        self.assertEqual(
            StockTransfer.objects.filter(status=StockTransfer.DISCREPANCY).count(), 1
        )
        self.assertEqual(
            StockTransfer.objects.filter(status=StockTransfer.DISPATCHED).count(), 1
        )
        adama = DailyClosing.objects.get(location__name="Adama Shop 1")
        self.assertEqual(adama.difference, Decimal("-10"))
        self.assertEqual(UserProfile.objects.filter(role=UserProfile.SHOP).count(), 4)

    def test_every_stock_level_equals_the_sum_of_its_movements(self):
        self.seed()
        for level in StockLevel.objects.all():
            moves = StockMovement.objects.filter(
                product=level.product, location=level.location
            )
            self.assertEqual(
                moves.aggregate(total=Sum("change"))["total"], level.quantity
            )

    def test_running_twice_needs_reset(self):
        self.seed()
        with self.assertRaises(CommandError):
            self.seed()
        self.seed(reset=True)
        self.assertEqual(Sale.objects.count(), 5)