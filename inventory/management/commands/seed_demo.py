from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from inventory.models import (
    DailyClosing,
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


class Command(BaseCommand):
    help = "Create fictional demo data: shops, stock, transfers, sales, and closings."

    def add_arguments(self, parser):
        parser.add_argument(
            "--password",
            required=True,
            help="Password to set for every demo user.",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing stock, sales, transfers, and closings first.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        has_data = (
            Sale.objects.exists()
            or StockMovement.objects.exists()
            or StockTransfer.objects.exists()
            or DailyClosing.objects.exists()
        )
        if has_data and not options["reset"]:
            raise CommandError(
                "Data already exists. Run again with --reset to delete stock, "
                "sales, transfers, and closings first."
            )
        if options["reset"]:
            DailyClosing.objects.all().delete()
            TransferItem.objects.all().delete()
            StockTransfer.objects.all().delete()
            Sale.objects.all().delete()
            StockMovement.objects.all().delete()
            StockLevel.objects.all().delete()

        password = options["password"]
        admin = User.objects.filter(is_superuser=True).first()

        region, _ = Region.objects.get_or_create(name="Oromia")
        hq, _ = Location.objects.update_or_create(
            name="Head Office Warehouse",
            defaults={"kind": Location.HEAD_OFFICE, "region": None, "city": "Addis Ababa"},
        )
        shops = {}
        for name, city in [
            ("Adama Shop 1", "Adama"),
            ("Jimma Shop", "Jimma"),
            ("Bishoftu Shop", "Bishoftu"),
            ("Shashemene Shop", "Shashemene"),
        ]:
            shops[name], _ = Location.objects.update_or_create(
                name=name,
                defaults={"kind": Location.SHOP, "region": region, "city": city},
            )

        sim, _ = Product.objects.update_or_create(
            sku="SIM-001",
            defaults={
                "name": "Prepaid SIM Card",
                "category": "SIM",
                "price": Decimal("50"),
                "low_stock_level": 100,
            },
        )
        phone, _ = Product.objects.update_or_create(
            sku="DEV-001",
            defaults={
                "name": "Smartphone A",
                "category": "DEVICE",
                "price": Decimal("8000"),
                "low_stock_level": 5,
            },
        )

        def make_user(username, role, location=None):
            user, _ = User.objects.get_or_create(username=username)
            if user.is_superuser:
                raise CommandError(f"{username} is a superuser. Rename or remove it.")
            user.set_password(password)
            user.is_staff = False
            user.save()
            UserProfile.objects.update_or_create(
                user=user,
                defaults={
                    "role": role,
                    "location": location,
                    "region": location.region if location else None,
                },
            )
            return user

        stock_user = make_user("stock1", UserProfile.STOCK)
        make_user("ops1", UserProfile.OPS)
        managers = {
            "Adama Shop 1": make_user("adama_mgr", UserProfile.SHOP, shops["Adama Shop 1"]),
            "Jimma Shop": make_user("jimma_mgr", UserProfile.SHOP, shops["Jimma Shop"]),
            "Bishoftu Shop": make_user(
                "bishoftu_mgr", UserProfile.SHOP, shops["Bishoftu Shop"]
            ),
            "Shashemene Shop": make_user(
                "shashemene_mgr", UserProfile.SHOP, shops["Shashemene Shop"]
            ),
        }

        def transfer(destination, items, receiver=None, counted=None):
            record = StockTransfer.objects.create(
                from_location=hq, to_location=destination, created_by=stock_user
            )
            for product, quantity in items:
                TransferItem.objects.create(
                    transfer=record, product=product, quantity_sent=quantity
                )
            record.dispatch(stock_user)
            if receiver is not None:
                for item in record.items.all():
                    item.quantity_received = (counted or {}).get(
                        item.product_id, item.quantity_sent
                    )
                    item.save()
                record.receive(receiver)
            return record

        apply_stock_change(
            sim, hq, 5000, StockMovement.RECEIPT, user=admin,
            reference="DEMO-RECEIPT-1", note="Delivery from supplier",
        )
        apply_stock_change(
            phone, hq, 50, StockMovement.RECEIPT, user=admin,
            reference="DEMO-RECEIPT-2", note="Delivery from supplier",
        )

        starting_stock = {
            "Adama Shop 1": (200, 8),
            "Jimma Shop": (90, 6),
            "Bishoftu Shop": (250, 4),
            "Shashemene Shop": (180, 7),
        }
        for name, (sims, phones) in starting_stock.items():
            transfer(
                shops[name],
                [(sim, sims), (phone, phones)],
                receiver=managers[name],
            )

        # 300 SIMs sent to Adama, only 290 counted on arrival
        transfer(
            shops["Adama Shop 1"],
            [(sim, 300)],
            receiver=managers["Adama Shop 1"],
            counted={sim.pk: 290},
        )
        # 100 SIMs still in transit to Jimma
        transfer(shops["Jimma Shop"], [(sim, 100)])

        sales = [
            ("Adama Shop 1", sim, 2, Sale.CASH, "R-1001"),
            ("Adama Shop 1", phone, 1, Sale.CASH, "R-1002"),
            ("Jimma Shop", sim, 5, Sale.MOBILE, "R-2001"),
            ("Bishoftu Shop", sim, 10, Sale.CASH, "R-3001"),
            ("Shashemene Shop", phone, 1, Sale.BANK, "R-4001"),
        ]
        for shop, product, quantity, payment, receipt in sales:
            Sale.objects.create(
                product=product,
                location=shops[shop],
                quantity=quantity,
                payment_method=payment,
                receipt_number=receipt,
                sold_by=managers[shop],
            )

        today = timezone.localdate()
        DailyClosing.objects.create(
            location=shops["Adama Shop 1"],
            date=today,
            counted_cash=Decimal("8090"),
            note="Gave change to a supplier",
            closed_by=managers["Adama Shop 1"],
        )
        DailyClosing.objects.create(
            location=shops["Bishoftu Shop"],
            date=today,
            counted_cash=Decimal("500"),
            closed_by=managers["Bishoftu Shop"],
        )

        self.stdout.write(self.style.SUCCESS("Demo data created."))
        self.stdout.write(
            "Users: stock1, ops1, adama_mgr, jimma_mgr, bishoftu_mgr, "
            "shashemene_mgr (all with the password you passed)."
        )