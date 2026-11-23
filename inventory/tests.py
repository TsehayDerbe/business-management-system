from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from .models import Product, Sale


class StockLogicTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            name="Laptop", sku="LAP-001", price=35000, quantity=10, low_stock_level=3
        )

    def test_sale_reduces_stock(self):
        Sale.objects.create(product=self.product, quantity=2)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 8)

    def test_sale_total_is_price_times_quantity(self):
        sale = Sale.objects.create(product=self.product, quantity=2)
        sale.refresh_from_db()
        self.assertEqual(sale.total_price, 70000)

    def test_cannot_sell_more_than_stock(self):
        with self.assertRaises(ValueError):
            Sale.objects.create(product=self.product, quantity=11)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 10)
        self.assertEqual(Sale.objects.count(), 0)

    def test_form_validation_blocks_oversell(self):
        sale = Sale(product=self.product, quantity=11)
        with self.assertRaises(ValidationError):
            sale.clean()

    def test_can_sell_exact_remaining_stock(self):
        Sale.objects.create(product=self.product, quantity=10)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 0)

    def test_multiple_sales_accumulate(self):
        Sale.objects.create(product=self.product, quantity=3)
        Sale.objects.create(product=self.product, quantity=3)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 4)

    def test_low_stock_flag(self):
        self.product.quantity = 3
        self.assertTrue(self.product.is_low_stock())
        self.product.quantity = 4
        self.assertFalse(self.product.is_low_stock())


class PermissionAndViewTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            name="Mouse", sku="MOU-001", price=500, quantity=50, low_stock_level=10
        )
        manager_group = Group.objects.create(name="Manager")
        self.manager = User.objects.create_user("manager1", password="Pass12345!")
        self.manager.groups.add(manager_group)
        self.cashier = User.objects.create_user("cashier1", password="Pass12345!")
        self.other = User.objects.create_user("cashier2", password="Pass12345!")
        self.other_sale = Sale.objects.create(
            product=self.product, quantity=1, sold_by=self.other
        )
        self.own_sale = Sale.objects.create(
            product=self.product, quantity=1, sold_by=self.cashier
        )

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_cashier_cannot_open_reports(self):
        self.client.login(username="cashier1", password="Pass12345!")
        response = self.client.get(reverse("reports"))
        self.assertEqual(response.status_code, 403)

    def test_manager_can_open_reports(self):
        self.client.login(username="manager1", password="Pass12345!")
        response = self.client.get(reverse("reports"))
        self.assertEqual(response.status_code, 200)

    def test_cashier_cannot_add_product(self):
        self.client.login(username="cashier1", password="Pass12345!")
        response = self.client.get(reverse("product_create"))
        self.assertEqual(response.status_code, 403)

    def test_manager_can_add_product(self):
        self.client.login(username="manager1", password="Pass12345!")
        response = self.client.post(
            reverse("product_create"),
            {
                "name": "Keyboard",
                "sku": "KEY-001",
                "price": "1200",
                "quantity": "20",
                "low_stock_level": "5",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Product.objects.filter(sku="KEY-001").exists())

    def test_cashier_can_open_own_invoice(self):
        self.client.login(username="cashier1", password="Pass12345!")
        response = self.client.get(reverse("sale_invoice", args=[self.own_sale.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_cashier_cannot_open_someone_elses_invoice(self):
        self.client.login(username="cashier1", password="Pass12345!")
        response = self.client.get(reverse("sale_invoice", args=[self.other_sale.pk]))
        self.assertEqual(response.status_code, 403)

    def test_manager_can_open_any_invoice(self):
        self.client.login(username="manager1", password="Pass12345!")
        response = self.client.get(reverse("sale_invoice", args=[self.other_sale.pk]))
        self.assertEqual(response.status_code, 200)

    def test_new_sale_through_form_reduces_stock(self):
        self.client.login(username="cashier1", password="Pass12345!")
        response = self.client.post(
            reverse("new_sale"), {"product": self.product.pk, "quantity": 5}
        )
        self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 50 - 2 - 5)
        last_sale = Sale.objects.order_by("-pk").first()
        self.assertEqual(last_sale.sold_by, self.cashier)

    def test_new_sale_form_rejects_oversell(self):
        self.client.login(username="cashier1", password="Pass12345!")
        sales_before = Sale.objects.count()
        response = self.client.post(
            reverse("new_sale"), {"product": self.product.pk, "quantity": 999}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Sale.objects.count(), sales_before)
        self.product.refresh_from_db()
        self.assertEqual(self.product.quantity, 48)