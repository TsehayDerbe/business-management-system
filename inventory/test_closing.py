from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from .models import DailyClosing, Sale
from .tests import BaseCase


class DailyClosingTests(BaseCase):
    def setUp(self):
        self.put_stock(self.sim, self.shop1, 1000)

    def sell(self, quantity, payment="CASH", location=None):
        return Sale.objects.create(
            product=self.sim,
            location=location or self.shop1,
            quantity=quantity,
            payment_method=payment,
            sold_by=self.mgr1,
        )

    def close(self, counted, location=None, note=""):
        return DailyClosing.objects.create(
            location=location or self.shop1,
            date=timezone.localdate(),
            counted_cash=Decimal(counted),
            note=note,
            closed_by=self.mgr1,
        )

    def closing_data(self, counted, location=None, note="", day=None):
        return {
            "location": (location or self.shop1).pk,
            "date": (day or timezone.localdate()).isoformat(),
            "counted_cash": counted,
            "note": note,
        }

    def test_only_cash_sales_are_expected_in_the_till(self):
        self.sell(4)
        self.sell(2, payment="MOBILE")
        closing = self.close("200")
        self.assertEqual(closing.expected_cash, Decimal("200"))
        self.assertEqual(closing.difference, Decimal("0"))

    def test_shortage_and_surplus(self):
        self.sell(4)
        self.assertEqual(self.close("190").difference, Decimal("-10"))
        other = DailyClosing.objects.create(
            location=self.shop2,
            date=timezone.localdate(),
            counted_cash=Decimal("15"),
            closed_by=self.mgr2,
        )
        self.assertEqual(other.difference, Decimal("15"))

    def test_a_closed_day_cannot_be_changed(self):
        closing = self.close("0")
        closing.counted_cash = Decimal("5")
        with self.assertRaises(ValueError):
            closing.save()
        closing.refresh_from_db()
        self.assertEqual(closing.counted_cash, Decimal("0"))

    def test_no_sales_after_closing(self):
        self.close("0")
        with self.assertRaises(ValueError):
            self.sell(1)
        self.assertEqual(Sale.objects.count(), 0)
        self.assertEqual(self.stock_of(self.sim, self.shop1), 1000)

    def test_closing_one_shop_does_not_block_another(self):
        self.close("0")
        self.put_stock(self.sim, self.shop2, 10)
        self.sell(1, location=self.shop2)
        self.assertEqual(Sale.objects.count(), 1)

    def test_sale_form_shows_the_closed_message(self):
        self.close("0")
        self.login(self.mgr1)
        response = self.client.post(
            reverse("new_sale"),
            {
                "location": self.shop1.pk,
                "product": self.sim.pk,
                "quantity": 1,
                "payment_method": "CASH",
                "receipt_number": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already closed")
        self.assertEqual(Sale.objects.count(), 0)

    def test_manager_closes_their_own_shop(self):
        self.sell(4)
        self.login(self.mgr1)
        response = self.client.post(reverse("closing_create"), self.closing_data("200"))
        self.assertEqual(response.status_code, 302)
        closing = DailyClosing.objects.get()
        self.assertEqual(closing.closed_by, self.mgr1)
        self.assertEqual(closing.expected_cash, Decimal("200"))
        self.assertEqual(closing.difference, Decimal("0"))

    def test_a_mismatch_needs_a_note(self):
        self.sell(4)
        self.login(self.mgr1)
        response = self.client.post(reverse("closing_create"), self.closing_data("190"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "does not match")
        self.assertEqual(DailyClosing.objects.count(), 0)
        response = self.client.post(
            reverse("closing_create"),
            self.closing_data("190", note="Paid for a delivery"),
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(DailyClosing.objects.get().difference, Decimal("-10"))

    def test_the_form_does_not_reveal_the_expected_amount(self):
        self.sell(4)
        self.login(self.mgr1)
        response = self.client.get(reverse("closing_create"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "200.00")

    def test_cannot_close_the_same_day_twice(self):
        self.login(self.mgr1)
        first = self.client.post(reverse("closing_create"), self.closing_data("0"))
        self.assertEqual(first.status_code, 302)
        second = self.client.post(reverse("closing_create"), self.closing_data("0"))
        self.assertEqual(second.status_code, 200)
        self.assertEqual(DailyClosing.objects.count(), 1)

    def test_manager_cannot_close_another_shop(self):
        self.login(self.mgr1)
        response = self.client.post(
            reverse("closing_create"), self.closing_data("0", location=self.shop2)
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(DailyClosing.objects.count(), 0)

    def test_future_dates_are_rejected(self):
        self.login(self.mgr1)
        tomorrow = timezone.localdate() + timedelta(days=1)
        response = self.client.post(
            reverse("closing_create"), self.closing_data("0", day=tomorrow)
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(DailyClosing.objects.count(), 0)

    def test_negative_amounts_are_rejected(self):
        self.login(self.mgr1)
        response = self.client.post(reverse("closing_create"), self.closing_data("-5"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(DailyClosing.objects.count(), 0)

    def test_who_can_open_the_closing_form(self):
        for user, expected in [
            (self.admin, 200),
            (self.mgr1, 200),
            (self.stock_user, 403),
            (self.ops_user, 403),
        ]:
            with self.subTest(user=user.username):
                self.login(user)
                response = self.client.get(reverse("closing_create"))
                self.assertEqual(response.status_code, expected)

    def test_closing_list_is_scoped_by_role(self):
        self.close("0")
        DailyClosing.objects.create(
            location=self.shop2,
            date=timezone.localdate(),
            counted_cash=Decimal("0"),
            closed_by=self.mgr2,
        )
        self.login(self.mgr1)
        response = self.client.get(reverse("closing_list"))
        self.assertEqual(
            {c.location_id for c in response.context["closings"]}, {self.shop1.pk}
        )
        for user in [self.admin, self.stock_user, self.ops_user]:
            with self.subTest(user=user.username):
                self.login(user)
                response = self.client.get(reverse("closing_list"))
                self.assertEqual(
                    {c.location_id for c in response.context["closings"]},
                    {self.shop1.pk, self.shop2.pk},
                )

    def test_closing_list_names_the_shops_not_closed_yet(self):
        self.close("0")
        self.login(self.admin)
        response = self.client.get(reverse("closing_list"))
        self.assertEqual([s.pk for s in response.context["unclosed"]], [self.shop2.pk])

    def test_dashboard_counts_unclosed_shops_and_shortages(self):
        self.sell(4)
        self.login(self.admin)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.context["not_closed"], 2)
        self.assertEqual(response.context["cash_shortages"], 0)

        self.close("190", note="Paid for a delivery")
        for user, not_closed, shortages in [
            (self.admin, 1, 1),
            (self.mgr1, 0, 1),
            (self.mgr2, 1, 0),
        ]:
            with self.subTest(user=user.username):
                self.login(user)
                response = self.client.get(reverse("dashboard"))
                self.assertEqual(response.context["not_closed"], not_closed)
                self.assertEqual(response.context["cash_shortages"], shortages)