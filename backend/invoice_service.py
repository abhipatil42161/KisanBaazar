"""PDF invoice generator using reportlab. Returns raw bytes — caller wraps in a
StreamingResponse. Format: simple branded invoice with seller/buyer/line items/total.
GST upgrade is a small addition once GSTIN is provided."""
from __future__ import annotations
from io import BytesIO
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
)

BRAND_GREEN = colors.HexColor("#16a34a")


def _fmt_money(rupees: float) -> str:
    return f"INR {rupees:,.2f}"


def generate_invoice_pdf(order: dict, payment: dict | None = None) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title=f"Invoice {order.get('order_id', '')}",
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], textColor=BRAND_GREEN, spaceAfter=4)
    muted = ParagraphStyle("muted", parent=styles["Normal"], textColor=colors.grey, fontSize=9)
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=10, leading=14)

    elements = []
    elements.append(Paragraph("KisanBaazar", h1))
    elements.append(Paragraph("Agriculture Marketplace · India", muted))
    elements.append(Spacer(1, 10))

    # Invoice meta
    issued = (payment or {}).get("created_at") or order.get("paid_at") or order.get("created_at") or ""
    try:
        issued_disp = datetime.fromisoformat(issued.replace("Z", "+00:00")).strftime("%d %b %Y, %H:%M UTC")
    except Exception:
        issued_disp = issued
    meta_data = [
        ["Invoice #", order.get("order_id", "")],
        ["Issued", issued_disp],
        ["Status", (order.get("payment_status") or "").upper()],
    ]
    if order.get("razorpay_payment_id"):
        meta_data.append(["Razorpay Payment ID", order["razorpay_payment_id"]])
    if order.get("razorpay_order_id"):
        meta_data.append(["Razorpay Order ID", order["razorpay_order_id"]])
    meta_tbl = Table(meta_data, colWidths=[42 * mm, 130 * mm])
    meta_tbl.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.grey),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    elements.append(meta_tbl)
    elements.append(Spacer(1, 10))

    # Bill to
    elements.append(Paragraph("<b>Bill To</b>", body))
    elements.append(Paragraph(order.get("buyer_name") or "", body))
    elements.append(Paragraph(order.get("delivery_address") or "", muted))
    elements.append(Spacer(1, 12))

    # Items
    headers = [["#", "Item", "Qty", "Unit price", "Line total"]]
    rows = []
    for idx, it in enumerate(order.get("items", []), 1):
        qty = float(it.get("qty") or 0)
        price = float(it.get("price") or 0)
        rows.append([
            str(idx),
            it.get("title", "")[:48],
            f"{qty:g}",
            _fmt_money(price),
            _fmt_money(qty * price),
        ])
    items_tbl = Table(
        headers + rows,
        colWidths=[10 * mm, 90 * mm, 18 * mm, 27 * mm, 27 * mm],
        repeatRows=1,
    )
    items_tbl.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 10),
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_GREEN),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.darkgrey),
    ]))
    elements.append(items_tbl)
    elements.append(Spacer(1, 8))

    # Totals
    subtotal = float(order.get("total") or 0)
    charge_total = float(order.get("charge_total") or round(subtotal * 1.01))
    fee = max(0.0, charge_total - subtotal)
    totals_tbl = Table(
        [
            ["Subtotal", _fmt_money(subtotal)],
            ["Platform fee (1%)", _fmt_money(fee)],
            ["Total paid", _fmt_money(charge_total)],
        ],
        colWidths=[40 * mm, 35 * mm],
        hAlign="RIGHT",
    )
    totals_tbl.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -2), "Helvetica", 10),
        ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 11),
        ("TEXTCOLOR", (0, -1), (-1, -1), BRAND_GREEN),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEABOVE", (0, -1), (-1, -1), 0.5, colors.darkgrey),
        ("TOPPADDING", (0, -1), (-1, -1), 5),
    ]))
    elements.append(totals_tbl)
    elements.append(Spacer(1, 20))

    elements.append(Paragraph(
        "Thank you for buying directly from Indian farmers via KisanBaazar.<br/>"
        "Need help? Email hello@kisanbaazar.in. This is a computer-generated invoice.",
        muted,
    ))

    doc.build(elements)
    pdf = buf.getvalue()
    buf.close()
    return pdf
