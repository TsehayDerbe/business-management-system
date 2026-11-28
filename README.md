# Stock & Sales Control

A web application for a multi-shop distribution business. The head office dispatches stock to regional shops, shops confirm what arrived and record their sales, and every stock and cash movement is logged so missing stock and missing cash can be traced.

> All data shown in the screenshots is fictional.

## The problem

Distribution businesses that track stock in spreadsheets run into the same three problems: stock goes missing between the warehouse and the shops, sales reports arrive late, and transfers to the regions are slow to confirm. This project replaces scattered spreadsheets with one system that the head office can see live.

## Features

- **Locations:** head office warehouse, regions, cities, and shops
- **Stock per location:** every product is tracked separately at each location
- **Stock movement log:** every change (sale, transfer, adjustment) is recorded with who, when, and the balance afterwards. The log is read-only, and each stock level always equals the sum of its movements
- **Stock transfers:** draft, dispatch, and receipt. The shop enters what it actually counted, and any difference is flagged as a discrepancy and shows on the head office dashboard
- **Sales:** recorded per shop with payment method and the cash register's receipt number. Selling more than a shop holds is blocked
- **PDF invoices** for every sale
- **Daily cash closing:** the shop manager counts the till without seeing the expected amount, the system compares it with the day's cash sales, and a mismatch needs an explanation. A closed day is locked
- **Dashboards:** a head office view across all shops (sales, revenue, low stock, transfers in transit, discrepancies, shops that have not closed, cash shortages) and a shop view limited to one shop
- **Reports:** sales by date range, best-selling products, and CSV export for Excel
- **Role-based access** with four roles

## Roles

| Role | Sees | Can do |
|---|---|---|
| Head office admin | Everything | Everything |
| Stock controller | All shops | Manage products, create and dispatch transfers |
| Operations team | All shops (read only) | Monitor stock, transfers, sales, and closings |
| Sales manager | Their own shop only | Record sales, confirm received transfers, close the day |

## Business rules enforced by the system

- Stock can never go negative, and a shop can only sell what it holds
- A failed sale or transfer leaves no partial changes (database transactions)
- A transfer can be received only once, and received quantities can't exceed what was sent
- Only the destination shop can confirm a transfer
- A closed day can't be edited and accepts no new sales
- A shop manager can't view or change another shop's data, even by editing the URL

## Tech stack

- Python 3.13 and Django 6
- SQLite for development, PostgreSQL for deployment
- ReportLab for PDF invoices
- HTML and CSS templates
- Gunicorn and WhiteNoise for production

## Getting started

```bash
git clone https://github.com/TsehayDerbe/business-management-system.git
cd business-management-system
git checkout multi-branch
python -m venv venv
venv\Scripts\activate        # on Mac/Linux: source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open http://127.0.0.1:8000/ and log in.

### Setting up demo data

1. In the admin site (`/admin/`), add a region, a head office warehouse, and a few shops with cities.
2. Add products and set starting stock in **Stock levels**.
3. Create users, then add a **User profile** for each one to give them a role and, for sales managers, their shop.

## Running the tests

```bash
python manage.py test
```

The suite has 69 tests covering the stock logic, transfers and discrepancies, role-based access, scoped dashboards, invoices, reports, and cash closing.

## Screenshots

![Head office dashboard](screenshots/dashboard-head-office.png)
![Shop dashboard](screenshots/dashboard-shop.png)
![Transfer with a discrepancy](screenshots/transfer-discrepancy.png)
![Daily cash closing](screenshots/cash-closing.png)
![Stock movement log](screenshots/stock-movements.png)

## What I learned

- Modelling a business around locations and movements instead of a single stock number
- Keeping data consistent with database transactions and row locking
- Role-based access control with scoped querysets, so users only ever see their own data
- Designing controls against error and fraud, such as a blind cash count and locked days
- Writing tests for business rules and permissions, not only for pages

## Roadmap

- Operations module: tasks to shops and market visit logs
- Excel import for starting stock
- SIM batch tracking by serial number range
- Cash register integration, depending on the equipment and tax rules
- REST API and a Next.js frontend

## Author

**Tsehay Derbe** | Software Engineer | [LinkedIn](https://www.linkedin.com/in/tsehay-derbe-33b1a1246)