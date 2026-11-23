# Business Management System

A web application for small businesses to manage products, record sales, track stock, print invoices, and review sales reports. Built with Python and Django.

## Features

- **Inventory tracking:** products with SKU, price, stock level, and low-stock alerts
- **Sales:** recording a sale automatically reduces stock, and overselling is blocked
- **Dashboard:** today's sales, revenue, product count, and low-stock items at a glance
- **PDF invoices:** a printable invoice for every sale
- **Reports:** sales by date range, best-selling products, and CSV export for Excel
- **Roles and permissions:** Managers can add and edit products and see reports; cashiers can record sales and see only their own
- **Authentication:** login and logout, with all pages protected
- **Automated tests:** 17 tests covering stock logic, permissions, and invoices

## Tech stack

- Python 3.13, Django 6
- SQLite (development)
- ReportLab (PDF generation)
- HTML and CSS templates

## Getting started

```bash
git clone https://github.com/TsehayDerbe/business-management-system.git
cd business-management-system
python -m venv venv
venv\Scripts\activate        # on Mac/Linux: source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open http://127.0.0.1:8000/ and log in.

### Setting up roles

1. In the admin site (`/admin`), create a group named exactly `Manager`.
2. Add users to the `Manager` group to give them product and report access.
3. Users without the group are cashiers.

## Running the tests

```bash
python manage.py test
```

## Screenshots

_Add screenshots of the dashboard, products page, reports page, and a PDF invoice here._

## What I learned

- Keeping stock and sales consistent by updating stock inside the sale logic
- Role-based access control with Django groups and custom decorators
- Generating PDFs and CSV exports on the server
- Writing tests for business rules and permissions

## Roadmap

- REST API with Django REST Framework
- PostgreSQL and Docker setup
- Online deployment
- Multi-item invoices

## Author
**Tsehay Derbe** | Software Engineer | [LinkedIn](https://www.linkedin.com/in/tsehay-derbe-33b1a1246)