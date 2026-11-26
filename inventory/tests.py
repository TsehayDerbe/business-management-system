from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.test import TestCase
from django.urls import reverse

from .models import (
    Location,
    Product,
    Region,
    Sale,
    StockLevel,
    StockMovement,
    StockTransfer,
    TransferItem,
    UserProfile,
    apply_stock_change,
)


def make_user(username, role, location=None):
    user = User.objects.create_user(username)
    UserProfile.objects.create(
        user=user,
        role=role,
        location=location,
        region=location.region if location else None,
    )
    return user


class BaseCase(TestCase):
    """Shared test data: one head office, two shops, two products, and users."""

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Oromia")
        cls.hq = Location.objects.create(
            name="Head Office Warehouse", kind=Location.HEAD_OFFICE, city="Addis Ababa"
        )
        cls.shop1 = Location.objects.create(
            name="Adama Shop 1", kind=Location.SHOP, region=cls.region, city="Adama"
        )
        cls.shop2 = Location.objects.create(
            name="Jimma Shop", kind=Location.SHOP, region=cls.region, city="Jimma"
        )
        cls.sim = Product.objects.create(
            name="Prepaid SIM Card",
            sku="SIM-001",
            category="SIM",
            price=50,
            low_stock_level=100,
        )
        cls.phone = Product.objects.create(
            name="Smartphone A",
            sku="DEV-001",
            category="DEVICE",
            price=8000,
            low_stock_level=5,
        )
        cls.admin = User.objects.create_superuser("hq_admin")
        cls.stock_user = make_user("stock1", UserProfile.STOCK)
        cls.ops_user = make_user("ops1", UserProfile.OPS)
        cls.mgr1 = make_user("mgr1", UserProfile.SHOP, cls.shop1)
        cls.mgr2 = make_user("mgr2", UserProfile.SHOP, cls.shop2)
        cls.no_profile = User.objects.create_user("nobody")

    def login(self, user):
        self.client.force_login(user)

    def put_stock(self, product, location, quantity):
        return apply_stock_change(
            product, location, quantity, StockMovement.RECEIPT, user=self.admin
        )

    def stock_of(self, product, location):
        level = StockLevel.objects.filter(product=product, location=location).first()
        return level.quantity if level else 0

    def make_transfer(self, items, dispatch=False, destination=None):
        transfer = StockTransfer.objects.create(
            from_location=self.hq,
            to_location=destination or self.shop1,
            created_by=self.stock_user,
        )
        for product, quantity in items:
            TransferItem.objects.create(
                transfer=transfer, product=product, quantity_sent=quantity
            )
        if dispatch:
            transfer.dispatch(self.stock_user)
        return transfer

    def set_received(self, transfer, quantities):
        """quantities maps product pk to the quantity counted at the shop."""
        for item in transfer.items.all():
            item.quantity_received = quantities[item.product_id]
            item.save()


class StockLogicTests(BaseCase):
    def test_sale_reduces_stock_and_logs_movement(self):
        self.put_stock(self.sim, self.shop1, 200)
        sale = Sale.objects.create(
            product=self.sim, location=self.shop1, quantity=10, sold_by=self.mgr1
        )
        self.assertEqual(self.stock_of(self.sim, self.shop1), 190)
        move = StockMovement.objects.get(kind=StockMovement.SALE)
        self.assertEqual(move.change, -10)
        self.assertEqual(move.balance_after, 190)
        self.assertEqual(move.reference, f"Sale #{sale.pk}")
        self.assertEqual(move.created_by, self.mgr1)

    def test_sale_total_is_price_times_quantity(self):
        self.put_stock(self.sim, self.shop1, 100)
        sale = Sale.objects.create(product=self.sim, location=self.shop1, quantity=4)
        self.assertEqual(sale.total_price, 200)

    def test_cannot_sell_more_than_stock(self):
        self.put_stock(self.sim, self.shop1, 5)
        with self.assertRaises(ValueError):
            Sale.objects.create(product=self.sim, location=self.shop1, quantity=6)
        self.assertEqual(Sale.objects.count(), 0)
        self.assertEqual(self.stock_of(self.sim, self.shop1), 5)
        self.assertFalse(
            StockMovement.objects.filter(kind=StockMovement.SALE).exists()
        )

    def test_can_sell_exactly_the_remaining_stock(self):
        self.put_stock(self.sim, self.shop1, 10)
        Sale.objects.create(product=self.sim, location=self.shop1, quantity=10)
        self.assertEqual(self.stock_of(self.sim, self.shop1), 0)

    def test_cannot_sell_where_there_is_no_stock_record(self):
        with self.assertRaises(ValueError):
            Sale.objects.create(product=self.sim, location=self.shop2, quantity=1)
        self.assertEqual(Sale.objects.count(), 0)
        self.assertFalse(
            StockLevel.objects.filter(product=self.sim, location=self.shop2).exists()
        )

    def test_stock_in_one_shop_cannot_be_sold_from_another(self):
        self.put_stock(self.sim, self.shop1, 100)
        with self.assertRaises(ValueError):
            Sale.objects.create(product=self.sim, location=self.shop2, quantity=1)
        self.assertEqual(self.stock_of(self.sim, self.shop1), 100)

    def test_form_level_check_blocks_oversell(self):
        self.put_stock(self.sim, self.shop1, 10)
        sale = Sale(product=self.sim, location=self.shop1, quantity=11)
        with self.assertRaises(ValidationError):
            sale.clean()

    def test_low_stock_flag(self):
        self.put_stock(self.sim, self.shop1, 101)
        level = StockLevel.objects.get(product=self.sim, location=self.shop1)
        self.assertFalse(level.is_low())
        Sale.objects.create(product=self.sim, location=self.shop1, quantity=1)
        level.refresh_from_db()
        self.assertTrue(level.is_low())

    def test_stock_always_equals_sum_of_movements(self):
        self.put_stock(self.sim, self.hq, 1000)
        transfer = self.make_transfer([(self.sim, 300)], dispatch=True)
        self.set_received(transfer, {self.sim.pk: 290})
        transfer.receive(self.stock_user)
        Sale.objects.create(
            product=self.sim, location=self.shop1, quantity=20, sold_by=self.mgr1
        )
        levels = StockLevel.objects.all()
        self.assertEqual(levels.count(), 2)
        for level in levels:
            moves = StockMovement.objects.filter(
                product=level.product, location=level.location
            )
            self.assertEqual(moves.aggregate(total=Sum("change"))["total"], level.quantity)
            self.assertEqual(moves.order_by("-id").first().balance_after, level.quantity)


class TransferModelTests(BaseCase):
    def test_reference_is_generated(self):
        transfer = self.make_transfer([(self.sim, 10)])
        self.assertEqual(transfer.reference, f"TR-{transfer.pk:05d}")

    def test_source_and_destination_must_differ(self):
        transfer = StockTransfer(from_location=self.hq, to_location=self.hq)
        with self.assertRaises(ValidationError):
            transfer.clean()

    def test_dispatch_moves_stock_out_of_the_source(self):
        self.put_stock(self.sim, self.hq, 1000)
        transfer = self.make_transfer([(self.sim, 200)], dispatch=True)
        self.assertEqual(transfer.status, StockTransfer.DISPATCHED)
        self.assertEqual(self.stock_of(self.sim, self.hq), 800)
        self.assertEqual(self.stock_of(self.sim, self.shop1), 0)
        move = StockMovement.objects.get(kind=StockMovement.TRANSFER_OUT)
        self.assertEqual(move.change, -200)
        self.assertEqual(move.reference, transfer.reference)

    def test_cannot_dispatch_an_empty_transfer(self):
        transfer = self.make_transfer([])
        with self.assertRaises(ValueError):
            transfer.dispatch(self.stock_user)

    def test_cannot_dispatch_more_than_the_source_holds(self):
        self.put_stock(self.sim, self.hq, 100)
        transfer = self.make_transfer([(self.sim, 101)])
        with self.assertRaises(ValueError):
            transfer.dispatch(self.stock_user)
        self.assertEqual(self.stock_of(self.sim, self.hq), 100)

    def test_failed_dispatch_changes_nothing(self):
        self.put_stock(self.sim, self.hq, 100)
        self.put_stock(self.phone, self.hq, 1)
        transfer = self.make_transfer([(self.sim, 50), (self.phone, 5)])
        with self.assertRaises(ValueError):
            transfer.dispatch(self.stock_user)
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, StockTransfer.DRAFT)
        self.assertEqual(self.stock_of(self.sim, self.hq), 100)
        self.assertEqual(self.stock_of(self.phone, self.hq), 1)
        self.assertFalse(
            StockMovement.objects.filter(kind=StockMovement.TRANSFER_OUT).exists()
        )

    def test_cannot_dispatch_twice(self):
        self.put_stock(self.sim, self.hq, 1000)
        transfer = self.make_transfer([(self.sim, 200)], dispatch=True)
        with self.assertRaises(ValueError):
            transfer.dispatch(self.stock_user)
        self.assertEqual(self.stock_of(self.sim, self.hq), 800)

    def test_cannot_receive_a_draft(self):
        transfer = self.make_transfer([(self.sim, 10)])
        with self.assertRaises(ValueError):
            transfer.receive(self.mgr1)

    def test_full_receipt(self):
        self.put_stock(self.sim, self.hq, 1000)
        transfer = self.make_transfer([(self.sim, 200)], dispatch=True)
        self.set_received(transfer, {self.sim.pk: 200})
        transfer.receive(self.mgr1)
        self.assertEqual(transfer.status, StockTransfer.RECEIVED)
        self.assertEqual(transfer.received_by, self.mgr1)
        self.assertEqual(self.stock_of(self.sim, self.shop1), 200)

    def test_partial_receipt_is_a_discrepancy(self):
        self.put_stock(self.sim, self.hq, 1000)
        transfer = self.make_transfer([(self.sim, 200)], dispatch=True)
        self.set_received(transfer, {self.sim.pk: 190})
        transfer.receive(self.mgr1)
        self.assertEqual(transfer.status, StockTransfer.DISCREPANCY)
        self.assertEqual(self.stock_of(self.sim, self.shop1), 190)
        self.assertEqual(self.stock_of(self.sim, self.hq), 800)
        self.assertEqual(transfer.items.get().difference, 10)
        move = StockMovement.objects.get(kind=StockMovement.TRANSFER_IN)
        self.assertEqual(move.change, 190)
        self.assertEqual(move.reference, transfer.reference)

    def test_nothing_received_is_a_discrepancy(self):
        self.put_stock(self.sim, self.hq, 1000)
        transfer = self.make_transfer([(self.sim, 200)], dispatch=True)
        self.set_received(transfer, {self.sim.pk: 0})
        transfer.receive(self.mgr1)
        self.assertEqual(transfer.status, StockTransfer.DISCREPANCY)
        self.assertEqual(self.stock_of(self.sim, self.shop1), 0)
        self.assertFalse(
            StockMovement.objects.filter(kind=StockMovement.TRANSFER_IN).exists()
        )

    def test_cannot_receive_more_than_was_sent(self):
        self.put_stock(self.sim, self.hq, 1000)
        transfer = self.make_transfer([(self.sim, 200)], dispatch=True)
        self.set_received(transfer, {self.sim.pk: 250})
        with self.assertRaises(ValueError):
            transfer.receive(self.mgr1)
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, StockTransfer.DISPATCHED)
        self.assertEqual(self.stock_of(self.sim, self.shop1), 0)

    def test_cannot_receive_without_counting(self):
        self.put_stock(self.sim, self.hq, 1000)
        transfer = self.make_transfer([(self.sim, 200)], dispatch=True)
        with self.assertRaises(ValueError):
            transfer.receive(self.mgr1)
        self.assertEqual(self.stock_of(self.sim, self.shop1), 0)

    def test_cannot_receive_twice(self):
        self.put_stock(self.sim, self.hq, 1000)
        transfer = self.make_transfer([(self.sim, 200)], dispatch=True)
        self.set_received(transfer, {self.sim.pk: 200})
        transfer.receive(self.mgr1)
        with self.assertRaises(ValueError):
            transfer.receive(self.mgr1)
        self.assertEqual(self.stock_of(self.sim, self.shop1), 200)


class AccessControlTests(BaseCase):
    def assert_access(self, url_name, expectations, args=None):
        for user, expected in expectations:
            with self.subTest(page=url_name, user=user.username):
                self.client.force_login(user)
                response = self.client.get(reverse(url_name, args=args))
                self.assertEqual(response.status_code, expected)

    def test_anonymous_users_are_sent_to_login(self):
        for name in ["dashboard", "stock", "transfers", "new_sale", "reports"]:
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 302)
                self.assertIn("/login/", response.url)

    def test_user_without_a_profile_is_denied(self):
        self.login(self.no_profile)
        for name in ["dashboard", "stock", "transfers", "new_sale"]:
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 403)

    def test_pages_everyone_with_a_role_can_open(self):
        everyone = [
            (self.admin, 200),
            (self.stock_user, 200),
            (self.ops_user, 200),
            (self.mgr1, 200),
            (self.mgr2, 200),
        ]
        for name in ["dashboard", "stock", "transfers"]:
            self.assert_access(name, everyone)

    def test_head_office_only_pages(self):
        expectations = [
            (self.admin, 200),
            (self.stock_user, 200),
            (self.ops_user, 200),
            (self.mgr1, 403),
        ]
        for name in ["products", "reports", "reports_csv"]:
            self.assert_access(name, expectations)

    def test_only_admin_and_shop_managers_can_sell(self):
        self.assert_access(
            "new_sale",
            [
                (self.admin, 200),
                (self.mgr1, 200),
                (self.stock_user, 403),
                (self.ops_user, 403),
            ],
        )

    def test_only_admin_and_stock_controller_manage_stock(self):
        expectations = [
            (self.admin, 200),
            (self.stock_user, 200),
            (self.ops_user, 403),
            (self.mgr1, 403),
        ]
        self.assert_access("transfer_create", expectations)
        self.assert_access("product_create", expectations)
        self.assert_access("product_edit", expectations, args=[self.sim.pk])


class SalesViewTests(BaseCase):
    def sale_data(self, location, quantity, receipt=""):
        return {
            "location": location.pk,
            "product": self.sim.pk,
            "quantity": quantity,
            "payment_method": "CASH",
            "receipt_number": receipt,
        }

    def test_dashboards_are_scoped_by_role(self):
        self.put_stock(self.sim, self.shop1, 100)
        self.put_stock(self.sim, self.shop2, 100)
        Sale.objects.create(
            product=self.sim, location=self.shop1, quantity=5, sold_by=self.mgr1
        )
        Sale.objects.create(
            product=self.sim, location=self.shop2, quantity=3, sold_by=self.mgr2
        )

        self.login(self.mgr1)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.context["scope"], "Adama Shop 1")
        self.assertEqual(response.context["totals"]["count"], 1)
        self.assertEqual(response.context["totals"]["revenue"], 250)
        shops = {sale.location_id for sale in response.context["recent_sales"]}
        self.assertEqual(shops, {self.shop1.pk})
        self.assertEqual(len(response.context["shop_rows"]), 0)

        self.login(self.admin)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.context["scope"], "All shops (head office view)")
        self.assertEqual(response.context["totals"]["count"], 2)
        rows = {row.name: row.sales_count for row in response.context["shop_rows"]}
        self.assertEqual(rows, {"Adama Shop 1": 1, "Jimma Shop": 1})

    def test_stock_page_is_scoped_by_role(self):
        self.put_stock(self.sim, self.shop1, 100)
        self.put_stock(self.sim, self.shop2, 100)
        self.login(self.mgr1)
        response = self.client.get(reverse("stock"))
        self.assertEqual(
            {level.location_id for level in response.context["levels"]},
            {self.shop1.pk},
        )
        self.login(self.admin)
        response = self.client.get(reverse("stock"))
        self.assertEqual(
            {level.location_id for level in response.context["levels"]},
            {self.shop1.pk, self.shop2.pk},
        )

    def test_shop_manager_can_record_a_sale(self):
        self.put_stock(self.sim, self.shop1, 100)
        self.login(self.mgr1)
        response = self.client.post(
            reverse("new_sale"), self.sale_data(self.shop1, 5, receipt="R-0001")
        )
        self.assertEqual(response.status_code, 302)
        sale = Sale.objects.get()
        self.assertEqual(sale.sold_by, self.mgr1)
        self.assertEqual(sale.receipt_number, "R-0001")
        self.assertEqual(self.stock_of(self.sim, self.shop1), 95)

    def test_shop_manager_cannot_sell_from_another_shop(self):
        self.put_stock(self.sim, self.shop1, 100)
        self.put_stock(self.sim, self.shop2, 100)
        self.login(self.mgr1)
        response = self.client.post(reverse("new_sale"), self.sale_data(self.shop2, 5))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Sale.objects.count(), 0)
        self.assertEqual(self.stock_of(self.sim, self.shop2), 100)

    def test_oversell_is_rejected_with_a_message(self):
        self.put_stock(self.sim, self.shop1, 5)
        self.login(self.mgr1)
        response = self.client.post(reverse("new_sale"), self.sale_data(self.shop1, 6))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Only 5 units")
        self.assertEqual(Sale.objects.count(), 0)
        self.assertEqual(self.stock_of(self.sim, self.shop1), 5)

    def test_zero_quantity_is_rejected(self):
        self.put_stock(self.sim, self.shop1, 5)
        self.login(self.mgr1)
        response = self.client.post(reverse("new_sale"), self.sale_data(self.shop1, 0))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Sale.objects.count(), 0)

    def test_invoice_access(self):
        self.put_stock(self.sim, self.shop1, 100)
        self.put_stock(self.sim, self.shop2, 100)
        own = Sale.objects.create(
            product=self.sim, location=self.shop1, quantity=1, sold_by=self.mgr1
        )
        other = Sale.objects.create(
            product=self.sim, location=self.shop2, quantity=1, sold_by=self.mgr2
        )
        self.login(self.mgr1)
        response = self.client.get(reverse("sale_invoice", args=[own.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        response = self.client.get(reverse("sale_invoice", args=[other.pk]))
        self.assertEqual(response.status_code, 403)
        self.login(self.admin)
        response = self.client.get(reverse("sale_invoice", args=[other.pk]))
        self.assertEqual(response.status_code, 200)


class TransferViewTests(BaseCase):
    def form_data(self, source, destination, product=None, quantity=""):
        return {
            "from_location": source.pk,
            "to_location": destination.pk,
            "note": "",
            "items-TOTAL_FORMS": "1",
            "items-INITIAL_FORMS": "0",
            "items-MIN_NUM_FORMS": "0",
            "items-MAX_NUM_FORMS": "1000",
            "items-0-product": product.pk if product else "",
            "items-0-quantity_sent": quantity,
        }

    def post_action(self, transfer, action, follow=False, **extra):
        data = {"action": action}
        data.update(extra)
        return self.client.post(
            reverse("transfer_detail", args=[transfer.pk]), data, follow=follow
        )

    def test_stock_controller_creates_a_draft(self):
        self.put_stock(self.sim, self.hq, 1000)
        self.login(self.stock_user)
        response = self.client.post(
            reverse("transfer_create"),
            self.form_data(self.hq, self.shop1, self.sim, "200"),
        )
        self.assertEqual(response.status_code, 302)
        transfer = StockTransfer.objects.get()
        self.assertEqual(transfer.status, StockTransfer.DRAFT)
        self.assertEqual(transfer.created_by, self.stock_user)
        self.assertEqual(transfer.items.get().quantity_sent, 200)
        self.assertEqual(self.stock_of(self.sim, self.hq), 1000)

    def test_transfer_without_items_is_rejected(self):
        self.login(self.stock_user)
        response = self.client.post(
            reverse("transfer_create"), self.form_data(self.hq, self.shop1)
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Add at least one item")
        self.assertEqual(StockTransfer.objects.count(), 0)

    def test_transfer_to_the_same_location_is_rejected(self):
        self.login(self.stock_user)
        response = self.client.post(
            reverse("transfer_create"),
            self.form_data(self.hq, self.hq, self.sim, "10"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(StockTransfer.objects.count(), 0)

    def test_stock_controller_dispatches(self):
        self.put_stock(self.sim, self.hq, 1000)
        transfer = self.make_transfer([(self.sim, 200)])
        self.login(self.stock_user)
        response = self.post_action(transfer, "dispatch")
        self.assertEqual(response.status_code, 302)
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, StockTransfer.DISPATCHED)
        self.assertEqual(self.stock_of(self.sim, self.hq), 800)

    def test_shop_manager_cannot_see_or_dispatch_a_draft(self):
        self.put_stock(self.sim, self.hq, 1000)
        transfer = self.make_transfer([(self.sim, 200)])
        self.login(self.mgr1)
        url = reverse("transfer_detail", args=[transfer.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.post_action(transfer, "dispatch").status_code, 403)
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, StockTransfer.DRAFT)
        self.assertEqual(self.stock_of(self.sim, self.hq), 1000)

    def test_shop_manager_confirms_receipt_with_a_discrepancy(self):
        self.put_stock(self.sim, self.hq, 1000)
        transfer = self.make_transfer([(self.sim, 200)], dispatch=True)
        item = transfer.items.get()
        self.login(self.mgr1)
        response = self.client.get(reverse("transfer_detail", args=[transfer.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Confirm receipt")
        response = self.post_action(transfer, "receive", **{f"received_{item.pk}": "190"})
        self.assertEqual(response.status_code, 302)
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, StockTransfer.DISCREPANCY)
        self.assertEqual(transfer.received_by, self.mgr1)
        self.assertEqual(self.stock_of(self.sim, self.shop1), 190)

    def test_shop_manager_confirms_a_clean_receipt(self):
        self.put_stock(self.sim, self.hq, 1000)
        transfer = self.make_transfer([(self.sim, 200)], dispatch=True)
        item = transfer.items.get()
        self.login(self.mgr1)
        self.post_action(transfer, "receive", **{f"received_{item.pk}": "200"})
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, StockTransfer.RECEIVED)
        self.assertEqual(self.stock_of(self.sim, self.shop1), 200)

    def test_receiving_more_than_sent_changes_nothing(self):
        self.put_stock(self.sim, self.hq, 1000)
        transfer = self.make_transfer([(self.sim, 200)], dispatch=True)
        item = transfer.items.get()
        self.login(self.mgr1)
        response = self.post_action(
            transfer, "receive", follow=True, **{f"received_{item.pk}": "250"}
        )
        self.assertContains(response, "received more than was sent")
        transfer.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(transfer.status, StockTransfer.DISPATCHED)
        self.assertIsNone(item.quantity_received)
        self.assertEqual(self.stock_of(self.sim, self.shop1), 0)

    def test_receiving_without_counting_is_rejected(self):
        self.put_stock(self.sim, self.hq, 1000)
        transfer = self.make_transfer([(self.sim, 200)], dispatch=True)
        self.login(self.mgr1)
        response = self.post_action(transfer, "receive", follow=True)
        self.assertContains(response, "Enter the received quantity")
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, StockTransfer.DISPATCHED)
        self.assertEqual(self.stock_of(self.sim, self.shop1), 0)

    def test_double_submit_does_not_add_stock_twice(self):
        self.put_stock(self.sim, self.hq, 1000)
        transfer = self.make_transfer([(self.sim, 200)], dispatch=True)
        item = transfer.items.get()
        self.login(self.mgr1)
        self.post_action(transfer, "receive", **{f"received_{item.pk}": "200"})
        self.post_action(transfer, "receive", **{f"received_{item.pk}": "200"})
        self.assertEqual(self.stock_of(self.sim, self.shop1), 200)

    def test_only_the_destination_shop_can_receive(self):
        self.put_stock(self.sim, self.hq, 1000)
        transfer = self.make_transfer([(self.sim, 200)], dispatch=True)
        item = transfer.items.get()
        url = reverse("transfer_detail", args=[transfer.pk])

        self.login(self.mgr2)
        self.assertEqual(self.client.get(url).status_code, 403)
        response = self.post_action(transfer, "receive", **{f"received_{item.pk}": "200"})
        self.assertEqual(response.status_code, 403)

        self.login(self.stock_user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Confirm receipt")
        response = self.post_action(transfer, "receive", **{f"received_{item.pk}": "200"})
        self.assertEqual(response.status_code, 403)

        transfer.refresh_from_db()
        self.assertEqual(transfer.status, StockTransfer.DISPATCHED)
        self.assertEqual(self.stock_of(self.sim, self.shop1), 0)

    def test_transfer_list_visibility(self):
        self.put_stock(self.sim, self.hq, 1000)
        draft = self.make_transfer([(self.sim, 10)])
        sent = self.make_transfer([(self.sim, 20)], dispatch=True)

        self.login(self.mgr1)
        response = self.client.get(reverse("transfers"))
        self.assertEqual(list(response.context["transfers"]), [sent])

        self.login(self.mgr2)
        response = self.client.get(reverse("transfers"))
        self.assertEqual(list(response.context["transfers"]), [])

        self.login(self.stock_user)
        response = self.client.get(reverse("transfers"))
        self.assertEqual(set(response.context["transfers"]), {draft, sent})

    def test_dashboard_counts_transfers_and_discrepancies(self):
        self.put_stock(self.sim, self.hq, 1000)
        self.make_transfer([(self.sim, 100)], dispatch=True)
        second = self.make_transfer([(self.sim, 100)], dispatch=True)
        self.set_received(second, {self.sim.pk: 90})
        second.receive(self.stock_user)

        for user, in_transit, discrepancies in [
            (self.admin, 1, 1),
            (self.mgr1, 1, 1),
            (self.mgr2, 0, 0),
        ]:
            with self.subTest(user=user.username):
                self.login(user)
                response = self.client.get(reverse("dashboard"))
                self.assertEqual(response.context["in_transit"], in_transit)
                self.assertEqual(response.context["discrepancies"], discrepancies)


class ReportTests(BaseCase):
    def test_csv_export_includes_shop_and_receipt(self):
        self.put_stock(self.sim, self.shop1, 100)
        Sale.objects.create(
            product=self.sim,
            location=self.shop1,
            quantity=2,
            receipt_number="R-0042",
            sold_by=self.mgr1,
        )
        self.login(self.admin)
        response = self.client.get(reverse("reports_csv"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("text/csv"))
        text = response.content.decode("utf-8")
        for expected in ["Receipt no.", "Adama Shop 1", "Prepaid SIM Card", "R-0042"]:
            self.assertIn(expected, text)

    def test_date_filter(self):
        self.put_stock(self.sim, self.shop1, 100)
        Sale.objects.create(product=self.sim, location=self.shop1, quantity=2)
        self.login(self.admin)
        response = self.client.get(
            reverse("reports"), {"start": "2000-01-01", "end": "2000-01-02"}
        )
        self.assertEqual(response.context["totals"]["count"], 0)
        response = self.client.get(reverse("reports"))
        self.assertEqual(response.context["totals"]["count"], 1)

    def test_bad_and_reversed_dates_are_handled(self):
        self.login(self.admin)
        response = self.client.get(reverse("reports"), {"start": "garbage"})
        self.assertEqual(response.status_code, 200)
        response = self.client.get(
            reverse("reports"), {"start": "2030-01-02", "end": "2030-01-01"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertLess(response.context["start"], response.context["end"])