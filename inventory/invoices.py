from io import BytesIO

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

BUSINESS_NAME = "Your Business Name"
BUSINESS_ADDRESS = "Addis Ababa, Ethiopia"


def build_invoice_pdf(sale):
    buffer = BytesIO()
    invoice_no = f"INV-{sale.pk:05d}"
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        title=f"Invoice {invoice_no}",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title2", parent=styles["Title"], alignment=0, fontSize=22)
    normal = styles["Normal"]
    right = ParagraphStyle("Right", parent=normal, alignment=2)

    sold_at = timezone.localtime(sale.sold_at)
    cashier = sale.sold_by.get_username() if sale.sold_by else "-"

    story = [
        Paragraph(BUSINESS_NAME, title_style),
        Paragraph(BUSINESS_ADDRESS, normal),
        Spacer(1, 10 * mm),
        Paragraph(f"<b>INVOICE {invoice_no}</b>", styles["Heading2"]),
        Paragraph(f"Date: {sold_at:%Y-%m-%d %H:%M}", normal),
        Paragraph(f"Served by: {cashier}", normal),
        Spacer(1, 8 * mm),
    ]

    unit_price = f"{sale.product.price:,.2f}"
    line_total = f"{sale.total_price:,.2f}"

    data = [
        ["Item", "SKU", "Unit price (ETB)", "Qty", "Total (ETB)"],
        [sale.product.name, sale.product.sku, unit_price, str(sale.quantity), line_total],
        ["", "", "", "TOTAL", line_total],
    ]

    table = Table(data, colWidths=[55 * mm, 30 * mm, 35 * mm, 15 * mm, 35 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a5f")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (3, 2), (-1, 2), "Helvetica-Bold"),
                ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
                ("LINEBELOW", (0, 0), (-1, 1), 0.5, colors.lightgrey),
                ("LINEABOVE", (3, 2), (-1, 2), 1, colors.black),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 15 * mm))
    story.append(Paragraph("Thank you for your business!", right))

    doc.build(story)
    pdf = buffer.getvalue()
    buffer.close()
    return pdf