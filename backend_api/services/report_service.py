import io
from datetime import datetime, timezone
from collections import Counter
from xml.sax.saxutils import escape

from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing, Rect, Circle
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    KeepTogether,
    HRFlowable,
    PageBreak,
)
from reportlab.pdfgen import canvas


class NumberedCanvas(canvas.Canvas):
    """
    Two-pass canvas to dynamically compute and draw total page numbers and running footer.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_number(num_pages)
            super().showPage()
        super().save()

    def draw_page_number(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748B"))
        
        # Draw bottom separator rule
        self.setStrokeColor(colors.HexColor("#E2E8F0"))
        self.setLineWidth(0.75)
        self.line(36, 36, A4[0] - 36, 36)
        
        # Left footer branding & confidentiality notice
        self.drawString(36, 22, "TravelMate Platform Management System • Confidential & Proprietary")
        
        # Right footer page number
        page_text = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(A4[0] - 36, 22, page_text)
        self.restoreState()


def _get_styles():
    base = getSampleStyleSheet()
    
    styles = {
        "BrandHeader": ParagraphStyle(
            "BrandHeader",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=colors.HexColor("#0F172A")
        ),
        "BrandSubheader": ParagraphStyle(
            "BrandSubheader",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#64748B")
        ),
        "Tag": ParagraphStyle(
            "Tag",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7,
            leading=9,
            textColor=colors.HexColor("#0D9488")
        ),
        "SectionTitle": ParagraphStyle(
            "SectionTitle",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=16,
            textColor=colors.HexColor("#1E293B")
        ),
        "SectionDesc": ParagraphStyle(
            "SectionDesc",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=12,
            textColor=colors.HexColor("#64748B")
        ),
        "CardValue": ParagraphStyle(
            "CardValue",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=20,
            alignment=1,
            textColor=colors.HexColor("#0F172A")
        ),
        "CardLabel": ParagraphStyle(
            "CardLabel",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7.5,
            leading=10,
            alignment=1,
            textColor=colors.HexColor("#64748B")
        ),
        "TableHeader": ParagraphStyle(
            "TableHeader",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#FFFFFF")
        ),
        "TableCell": ParagraphStyle(
            "TableCell",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#1E293B")
        ),
        "TableCellBold": ParagraphStyle(
            "TableCellBold",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#0F172A")
        ),
        "TableCellMuted": ParagraphStyle(
            "TableCellMuted",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=7.5,
            leading=10,
            textColor=colors.HexColor("#64748B")
        ),
        "MetaLabel": ParagraphStyle(
            "MetaLabel",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#475569")
        ),
        "MetaValue": ParagraphStyle(
            "MetaValue",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#0F172A")
        ),
    }
    styles["SectionTitle"].keepWithNext = True
    return styles


def _build_kpi_card(value_text, label_text, styles, bg_color="#F8FAFC", border_color="#E2E8F0", text_color="#0F172A"):
    val_style = ParagraphStyle("V", parent=styles["CardValue"], textColor=colors.HexColor(text_color))
    content = [
        [Paragraph(str(value_text), val_style)],
        [Spacer(1, 2)],
        [Paragraph(label_text.upper(), styles["CardLabel"])]
    ]
    t = Table(content, colWidths=[120])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(bg_color)),
        ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor(border_color)),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def _style_table(data, col_widths=None, colWidths=None, header_bg="#1E293B"):
    widths = col_widths or colWidths
    widths = [width * 511 / sum(widths) for width in widths] if widths else None
    t = Table(data, colWidths=widths, repeatRows=1)
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(header_bg)),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
    ]
    
    for r in range(1, len(data)):
        bg = "#FFFFFF" if r % 2 == 1 else "#F8FAFC"
        style_cmds.append(("BACKGROUND", (0, r), (-1, r), colors.HexColor(bg)))
        
    t.setStyle(TableStyle(style_cmds))
    return t


_INK = colors.HexColor("#143F3B")
_ACCENT = colors.HexColor("#25857A")
_CHART_COLORS = [_ACCENT, colors.HexColor("#A88345"), colors.HexColor("#5E7C9B"),
                 colors.HexColor("#B66A5A"), colors.HexColor("#778579")]


def _generated_at(data):
    raw = data.get('generatedAt')
    try:
        value = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
        if value.tzinfo is None:
            raise ValueError()
        return value.astimezone(timezone.utc).strftime("%d %B %Y, %H:%M:%S UTC")
    except (ValueError, TypeError):
        return datetime.now(timezone.utc).strftime("%d %B %Y, %H:%M:%S UTC")


def _period(data):
    criteria = data.get('criteria') or {}
    if criteria.get('startDate') or criteria.get('endDate'):
        return f"{criteria.get('startDate') or 'All prior dates'} to {criteria.get('endDate') or 'Latest available date'}"
    return "All available dates in the loaded report"


def _cover(title, entity, data, generated_at, styles, classification):
    cover_title = ParagraphStyle('CoverTitle', parent=styles['BrandHeader'],
                                 fontSize=30, leading=37, textColor=_INK)
    brand = Table([[Paragraph('<font color="#FFFFFF" size="18"><b>TravelMate</b></font>',
                              styles['BrandHeader'])]], colWidths=[511])
    brand.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), _INK),
        ('LEFTPADDING', (0, 0), (-1, -1), 22),
        ('TOPPADDING', (0, 0), (-1, -1), 20),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 20),
    ]))
    metadata = [[Paragraph(escape(label), styles['MetaLabel']),
                 Paragraph(escape(str(value)), styles['MetaValue'])]
                for label, value in [
                    ('Prepared for', entity), ('Generated', generated_at),
                    ('Reporting period', _period(data)), ('Classification', classification)]]
    table = Table(metadata, colWidths=[116, 395])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F2F5F1')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 14),
        ('RIGHTPADDING', (0, 0), (-1, -1), 14),
        ('TOPPADDING', (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
    ]))
    return [
        brand, Spacer(1, 60),
        Paragraph('OPERATIONS &amp; PERFORMANCE', styles['Tag']),
        Spacer(1, 12), Paragraph(escape(title), cover_title), Spacer(1, 30),
        HRFlowable(width='100%', thickness=2, color=_ACCENT),
        Spacer(1, 30), table, Spacer(1, 28),
        Paragraph('Prepared from the existing TravelMate report scope. '
                  'Source limits and selected filters apply throughout this document.',
                  styles['SectionDesc']),
        Paragraph('Recorded test-mode payments are simulated amounts. They do not establish '
                  'real financial income or a confirmed supplier reservation.',
                  styles['SectionDesc']),
        PageBreak(),
        Paragraph('Executive summary', styles['SectionTitle']), Spacer(1, 12),
    ]


def _financial_summary(summary, styles, operator=False):
    metrics = [
        ('Recorded paid MYR total - all recorded modes', summary.get('totalPaidRevenue', 0)),
        ('Included recorded test-mode paid MYR', summary.get('testPaidTotal', 0)),
    ]
    rows = [[Paragraph('Payment measure', styles['TableHeader']),
             Paragraph('Count / amount', styles['TableHeader'])]]
    for label, value in metrics:
        rows.append([Paragraph(label, styles['TableCell']),
                     Paragraph(escape(f"MYR {value:,.2f}"), styles['TableCellBold'])])
    count_fields = ([('bookingRecords', 'Booking records'), ('paidBookings', 'Paid booking records'),
                     ('testModeOrders', 'Recorded test-mode orders')] if operator else
                    [('total', 'Payment records'), ('paid', 'Paid payment records'),
                     ('testMode', 'Recorded test-mode payment records')])
    for key, label in count_fields:
        rows.append([Paragraph(label, styles['TableCell']),
                     Paragraph(escape(str(summary.get(key, 0))), styles['TableCellBold'])])
    notes = ('The test-mode portion is included in the recorded paid total; do not add the two. '
             'Recorded paid totals do not establish live settlement or real financial income. '
             'Hotel and package supplier confirmations are separate from payment.')
    if operator:
        notes += ' Portfolio value is the listed package catalogue value, separate from booking payments.'
    return [
        Spacer(1, 12), Paragraph('Payment context', styles['SectionTitle']),
        _style_table(rows, colWidths=[365, 146], header_bg='#143F3B'),
        Spacer(1, 6), Paragraph(notes, styles['SectionDesc']),
        Paragraph(f"Paid records without a usable amount: {summary.get('unpricedPaidOrders', 0)}.",
                  styles['SectionDesc']),
    ]


def _distribution(summary, fields, total):
    rows = [(label, summary.get(key, 0)) for key, label in fields]
    other = summary.get(total, 0) - sum(count for _, count in rows)
    if other > 0:
        rows.append(('Other / unclassified', other))
    return rows


def _report_charts(data, operator=False):
    summary = data.get('summary') or {}
    package_fields = [('approved', 'Approved'), ('pending', 'Pending review'),
                      ('rejected', 'Rejected'), ('draft', 'Draft')]
    if operator:
        summary = summary or data
        packages = _distribution(summary, [
            ('approvedPackages', 'Approved'), ('pendingPackages', 'Pending review'),
            ('rejectedPackages', 'Rejected'), ('draftPackages', 'Draft')], 'totalPackages')
        bookings = Counter(str(row.get('packageTitle') or 'Unspecified package')
                           for row in data.get('bookings') or [])
        fulfillment = _distribution(summary, [
            ('fulfilledBookings', 'Fulfilled / trip ready'),
            ('pendingFulfillmentBookings', 'Pending arrangements')], 'bookingRecords')
        return [
            ('Package status distribution', packages, 'donut',
             'Package approval categories from the loaded report summary.'),
            ('Bookings by package', sorted(bookings.items(), key=lambda row: (-row[1], row[0])), 'bar',
             'Counts of loaded booking records grouped by the purchased package title. Includes unpaid records.'),
            ('Fulfilment and arrangements', fulfillment, 'bar',
             'Recorded booking fulfilment categories. Trip readiness does not establish a supplier reservation.'),
        ]
    return [
        ('User role distribution', _distribution(summary.get('users') or {}, [
            ('travellers', 'Travellers'), ('operators', 'Tourism operators'),
            ('administrators', 'Administrators')], 'total'), 'donut',
         'Account roles in the filtered report scope.'),
        ('Package moderation', _distribution(summary.get('packages') or {}, package_fields, 'total'), 'bar',
         'Approval categories in the loaded package summary.'),
        ('Campaign status', [(label, (summary.get('campaigns') or {}).get(key, 0))
                             for key, label in [('approved', 'Approved'), ('pending', 'Pending review'),
                                                ('rejected', 'Rejected'), ('active', 'Active')]], 'bar',
         'Active campaigns are a subset of approved campaigns. These categories overlap.'),
        ('Feedback moderation', [(label, (summary.get('feedback') or {}).get(key, 0))
                                 for key, label in [('visible', 'Visible'), ('pending', 'Pending review'),
                                                    ('removed', 'Removed')]], 'bar',
         'Existing visibility and moderation counts. Categories may overlap; they are not a percentage distribution.'),
    ]


def _chart_content(rows, kind, styles):
    if not rows or not any(value for _, value in rows):
        return Paragraph('No category counts available in this report scope.', styles['SectionDesc'])
    if kind == 'donut':
        drawing = Drawing(180, 176)
        pie = Pie()
        pie.x, pie.y, pie.width, pie.height = 12, 8, 156, 156
        positive = [(label, value) for label, value in rows if value > 0]
        pie.data = [value for _, value in positive]
        pie.labels = []
        for index, _ in enumerate(positive):
            pie.slices[index].fillColor = _CHART_COLORS[index % len(_CHART_COLORS)]
            pie.slices[index].strokeColor = colors.white
        drawing.add(pie)
        drawing.add(Circle(90, 86, 43, fillColor=colors.white, strokeColor=colors.white))
        legend = []
        for label, value in rows:
            index = next((i for i, (key, _) in enumerate(positive) if key == label), None)
            marker = Drawing(12, 12)
            marker.add(Rect(0, 1, 9, 9, fillColor=_CHART_COLORS[index % len(_CHART_COLORS)]
                            if index is not None else colors.HexColor('#D6DFDA'), strokeColor=None))
            legend.append([marker, Paragraph(escape(label), styles['TableCell']),
                           Paragraph(str(value), styles['TableCellBold'])])
        table = Table([[drawing, Table(legend, colWidths=[18, 235, 50])]],
                      colWidths=[192, 319])
        table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                                   ('LEFTPADDING', (0, 0), (-1, -1), 0),
                                   ('RIGHTPADDING', (0, 0), (-1, -1), 0)]))
        return table
    maximum = max(value for _, value in rows)
    table_rows = []
    for label, value in rows:
        bar = Drawing(232, 14)
        bar.add(Rect(0, 2, 232, 10, fillColor=colors.HexColor('#E7EDE8'), strokeColor=None))
        if value:
            bar.add(Rect(0, 2, 232 * value / maximum, 10, fillColor=_ACCENT, strokeColor=None))
        table_rows.append([Paragraph(escape(str(label)), styles['TableCell']), bar,
                           Paragraph(str(value), styles['TableCellBold'])])
    table = Table(table_rows, colWidths=[215, 246, 50])
    table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                               ('TOPPADDING', (0, 0), (-1, -1), 6),
                               ('BOTTOMPADDING', (0, 0), (-1, -1), 6)]))
    return table


def _visual_analytics(data, styles, operator=False):
    story = [PageBreak(), Paragraph('Visual analytics', styles['SectionTitle']), Spacer(1, 14)]
    for title, rows, kind, description in _report_charts(data, operator):
        # The table can paginate for many package names; never lock a whole chart to one page.
        story.extend([Paragraph(title, styles['SectionTitle']),
                      Paragraph(description, styles['SectionDesc']), Spacer(1, 6),
                      _chart_content(rows, kind, styles), Spacer(1, 22)])
    story.extend([PageBreak(), Paragraph('Detailed report', styles['SectionTitle']), Spacer(1, 12)])
    return story


# ======================================================
# TOURISM OPERATOR BUSINESS ANALYTICS REPORT
# ======================================================

def export_operator_report(data, target, operator_profile=None):
    """
    Generates an executive PDF report for a Tourism Operator.
    data: report dictionary from generate_business_analytics
    target: file path or BytesIO buffer
    """
    from xml.sax.saxutils import escape
    from math import isfinite
    doc = SimpleDocTemplate(
        target,
        pagesize=A4,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=48
    )
    styles = _get_styles()
    story = []
    
    summary = data.get("summary", {}) if isinstance(data, dict) else {}
    if not summary and isinstance(data, dict) and "totalPackages" in data:
        summary = data

    packages = data.get("packages", []) if isinstance(data, dict) else []
    campaigns = data.get("campaigns", []) if isinstance(data, dict) else []
    raw_profile = operator_profile or {}
    operator_profile = {key: escape(str(value)) for key, value in raw_profile.items() if value is not None}

    company_name = operator_profile.get("companyName") or operator_profile.get("businessName") or "Tourism Operator"
    rep_name = operator_profile.get("name") or operator_profile.get("fullName") or "Operator Representative"
    reg_no = operator_profile.get("registrationNo") or "-"
    contact = operator_profile.get("businessContact") or operator_profile.get("phoneNo") or "-"
    email = operator_profile.get("email") or operator_profile.get("businessEmail") or "-"
    gen_date = _generated_at(data)
    story.extend(_cover("Tourism Operator Business Performance Report",
                        raw_profile.get("companyName") or raw_profile.get("businessName") or "Tourism Operator",
                        data, gen_date, styles, "Confidential - Operator business report"))

    # 1. Header Banner & Branding
    header_data = [
        [
            Paragraph("TRAVELMATE • TOURISM OPERATOR PORTAL", styles["Tag"]),
            Paragraph(f"REPORT REF: OP-ANALYTICS-{datetime.now().strftime('%Y%m%d')}", styles["TableCellMuted"])
        ],
        [
            Paragraph("Business Analytics & Performance Report", styles["BrandHeader"]),
            Paragraph("<b>Scope:</b> Operator report", styles["TableCellBold"])
        ],
        [
            Paragraph("Comprehensive overview of tourism packages, promotional campaigns, and business activity.", styles["BrandSubheader"]),
            Paragraph(f"<b>Date:</b> {gen_date}", styles["TableCellMuted"])
        ]
    ]
    header_table = Table(header_data, colWidths=[360, 163])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#0D9488"), spaceBefore=2, spaceAfter=12))

    # 2. Operator Profile Metadata Box
    meta_data = [
        [
            Paragraph("Company Name:", styles["MetaLabel"]),
            Paragraph(company_name, styles["MetaValue"]),
            Paragraph("Registration No:", styles["MetaLabel"]),
            Paragraph(reg_no, styles["MetaValue"]),
        ],
        [
            Paragraph("Representative:", styles["MetaLabel"]),
            Paragraph(rep_name, styles["MetaValue"]),
            Paragraph("Business Email:", styles["MetaLabel"]),
            Paragraph(email, styles["MetaValue"]),
        ],
        [
            Paragraph("Business Contact:", styles["MetaLabel"]),
            Paragraph(contact, styles["MetaValue"]),
            Paragraph("Generated At:", styles["MetaLabel"]),
            Paragraph(gen_date, styles["MetaValue"]),
        ]
    ]
    meta_table = Table(meta_data, colWidths=[100, 160, 100, 163])
    meta_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
        ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#E2E8F0")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#F1F5F9")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 14))
    if data.get('dataLimited'):
        story.append(Paragraph('Totals cover up to 500 loaded records per category, not the complete business history.', styles['SectionDesc']))

    # 3. Executive KPI Metric Cards
    total_packages = summary.get("totalPackages", len(packages))
    approved_packages = summary.get("approvedPackages", 0)
    total_campaigns = summary.get("totalCampaigns", len(campaigns))
    total_value = summary.get("totalPackageValue", 0.0)

    card1 = _build_kpi_card(total_packages, "Total Packages", styles, "#F8FAFC", "#CBD5E1")
    card2 = _build_kpi_card(approved_packages, "Approved Packages", styles, "#F0FDF4", "#BBF7D0", "#166534")
    card3 = _build_kpi_card(total_campaigns, "Total Campaigns", styles, "#EFF6FF", "#BFDBFE", "#1E40AF")
    card4 = _build_kpi_card(f"RM {total_value:,.2f}", "Total Portfolio Value", styles, "#F0FDFA", "#99F6E4", "#0F766E")

    cards_table = Table([[card1, card2, card3, card4]], colWidths=[127.75] * 4)
    cards_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(cards_table)
    story.append(Spacer(1, 16))

    story.extend(_financial_summary(summary, styles, operator=True))
    story.extend(_visual_analytics(data, styles, operator=True))

    # 4. Section 1: Tourism Package Portfolio
    story.append(Paragraph("1. Tourism Packages Portfolio", styles["SectionTitle"]))
    story.append(Paragraph("Listing of all tourism packages registered under this operator account.", styles["SectionDesc"]))
    story.append(Spacer(1, 6))

    pkg_table_rows = [
        [
            Paragraph("Package Title", styles["TableHeader"]),
            Paragraph("Destination", styles["TableHeader"]),
            Paragraph("Price", styles["TableHeader"]),
            Paragraph("Duration", styles["TableHeader"]),
            Paragraph("Max Guests", styles["TableHeader"]),
            Paragraph("Status", styles["TableHeader"]),
        ]
    ]

    if packages:
        for p in packages:
            title = escape(str(p.get("packageTitle") or "Untitled Package"))
            dest = escape(str(p.get("destinationName") or "-"))
            try:
                price = float(p.get('adultPrice', p.get('price')))
                price_label = f"{escape(str(p.get('currency') or 'MYR'))} {price:,.2f}" if isfinite(price) and price >= 0 else 'Unavailable'
            except (TypeError, ValueError):
                price_label = 'Unavailable'
            duration = escape(f"{p.get('durationDays', 1)} Day(s)")
            max_travellers = escape(str(p.get("maxTravellers", 1)))
            status = escape(str(p.get("approvalStatus", "draft")).upper())

            pkg_table_rows.append([
                Paragraph(title, styles["TableCellBold"]),
                Paragraph(dest, styles["TableCell"]),
                Paragraph(price_label, styles["TableCellBold"]),
                Paragraph(duration, styles["TableCell"]),
                Paragraph(max_travellers, styles["TableCell"]),
                Paragraph(status, styles["TableCellBold"]),
            ])
    else:
        pkg_table_rows.append([
            Paragraph("No tourism packages found.", styles["TableCellMuted"]),
            Paragraph("-", styles["TableCellMuted"]),
            Paragraph("-", styles["TableCellMuted"]),
            Paragraph("-", styles["TableCellMuted"]),
            Paragraph("-", styles["TableCellMuted"]),
            Paragraph("-", styles["TableCellMuted"]),
        ])

    pkg_table = _style_table(pkg_table_rows, colWidths=[160, 95, 75, 65, 60, 68], header_bg="#0F172A")
    story.append(pkg_table)
    story.append(Spacer(1, 16))

    # 5. Section 2: Promotional Campaigns
    story.append(Paragraph("2. Promotional Campaigns", styles["SectionTitle"]))
    story.append(Paragraph("Active and scheduled promotional campaigns for approved tourism packages.", styles["SectionDesc"]))
    story.append(Spacer(1, 6))

    camp_table_rows = [
        [
            Paragraph("Campaign Title", styles["TableHeader"]),
            Paragraph("Promo Code", styles["TableHeader"]),
            Paragraph("Discount", styles["TableHeader"]),
            Paragraph("Validity Period", styles["TableHeader"]),
            Paragraph("Review Status", styles["TableHeader"]),
        ]
    ]

    if campaigns:
        for c in campaigns:
            c_title = escape(str(c.get("campaignTitle") or "Promotion"))
            promo = escape(str(c.get("promoCode") or "-"))
            dtype = c.get("discountType", "percentage")
            dval = float(c.get("discountValue") or 0)
            disc_str = f"{dval:g}%" if dtype == "percentage" else f"RM {dval:,.2f}"
            valid_period = escape(f"{c.get('startDate', '-')} to {c.get('endDate', '-')}")
            r_status = escape(str(c.get("reviewStatus", "draft")).upper())

            camp_table_rows.append([
                Paragraph(c_title, styles["TableCellBold"]),
                Paragraph(promo, styles["TableCellBold"]),
                Paragraph(disc_str, styles["TableCell"]),
                Paragraph(valid_period, styles["TableCell"]),
                Paragraph(r_status, styles["TableCellBold"]),
            ])
    else:
        camp_table_rows.append([
            Paragraph("No promotional campaigns recorded.", styles["TableCellMuted"]),
            Paragraph("-", styles["TableCellMuted"]),
            Paragraph("-", styles["TableCellMuted"]),
            Paragraph("-", styles["TableCellMuted"]),
            Paragraph("-", styles["TableCellMuted"]),
        ])

    camp_table = _style_table(camp_table_rows, colWidths=[180, 85, 75, 115, 68], header_bg="#1E293B")
    story.append(camp_table)
    story.append(Spacer(1, 16))

    # 6. Section 3: Performance Breakdown Summary
    story.append(Paragraph("3. Approval & Performance Summary", styles["SectionTitle"]))
    story.append(Paragraph("Breakdown of package lifecycle statuses and commercial portfolio metrics.", styles["SectionDesc"]))
    story.append(Spacer(1, 6))

    approved_cnt = summary.get("approvedPackages", 0)
    pending_cnt = summary.get("pendingPackages", 0)
    rejected_cnt = summary.get("rejectedPackages", 0)
    draft_cnt = summary.get("draftPackages", 0)
    booking_cnt = summary.get("bookingRecords", 0)

    perf_rows = [
        [Paragraph("Metric Category", styles["TableHeader"]), Paragraph("Count / Value", styles["TableHeader"]), Paragraph("Percentage / Notes", styles["TableHeader"])],
        [Paragraph("Approved Packages", styles["TableCellBold"]), Paragraph(str(approved_cnt), styles["TableCellBold"]), Paragraph(f"{(approved_cnt / total_packages * 100) if total_packages else 0:.1f}% of total", styles["TableCell"])],
        [Paragraph("Pending Review", styles["TableCell"]), Paragraph(str(pending_cnt), styles["TableCell"]), Paragraph("Awaiting admin review", styles["TableCellMuted"])],
        [Paragraph("Draft Packages", styles["TableCell"]), Paragraph(str(draft_cnt), styles["TableCell"]), Paragraph("In-progress operator drafts", styles["TableCellMuted"])],
        [Paragraph("Rejected Packages", styles["TableCell"]), Paragraph(str(rejected_cnt), styles["TableCell"]), Paragraph("Requires revision", styles["TableCellMuted"])],
        [Paragraph("Booking Activity Records", styles["TableCell"]), Paragraph(str(booking_cnt), styles["TableCell"]), Paragraph("Traveller booking requests", styles["TableCellMuted"])],
        [Paragraph("Combined Package Value", styles["TableCellBold"]), Paragraph(f"RM {total_value:,.2f}", styles["TableCellBold"]), Paragraph("Gross listed portfolio value", styles["TableCellBold"])],
    ]
    perf_table = _style_table(perf_rows, colWidths=[180, 140, 203], header_bg="#334155")
    story.append(perf_table)

    doc.build(story, canvasmaker=NumberedCanvas)


# ======================================================
# ADMIN SYSTEM ACTIVITY REPORT
# ======================================================

def _selected_admin_report(data, styles):
    """Category details reuse the same read-only cells as Excel and the portal."""
    from admin_report_records import display_table, display_value
    from services.admin_report_csv import METRIC_LABELS, _label
    kind = data['criteria']['reportType']
    metrics = (data.get('summary') or {}).get(kind) or {}
    records = data.get('records') or []
    matching = (data.get('counts') or {}).get('filtered_records', len(records))
    values = [('Matching records in loaded scope', matching), ('Detailed records available', len(records))]
    feedback_labels = {'genuine': 'Genuine Feedback', 'evaluation': 'Evaluation Feedback'} if kind == 'feedback' else {}
    values.extend((feedback_labels.get(key, METRIC_LABELS.get(key, _label(key))), value) for key, value in metrics.items())
    story = [Paragraph(f'{escape(kind.title())} report summary', styles['SectionTitle']),
             _style_table([[Paragraph('Metric', styles['TableHeader']), Paragraph('Value', styles['TableHeader'])]] +
                          [[Paragraph(escape(label), styles['TableCellBold']),
                            Paragraph(escape(display_value(value, 'number')), styles['TableCell'])]
                           for label, value in values], colWidths=[370, 153])]
    if kind in {'payments', 'bookings'}:
        story.append(Paragraph('Recorded Stripe test-mode payments are not live income. '
                               'Payment or a selected quote does not independently confirm a supplier reservation.',
                               styles['SectionDesc']))
    # Preserve the existing chart calculations, selecting only the corresponding category.
    chart_titles = {'users': 'User role distribution', 'packages': 'Package moderation',
                    'campaigns': 'Campaign status', 'feedback': 'Feedback moderation'}
    for title, rows, chart_kind, description in _report_charts(data, False):
        if title == chart_titles.get(kind):
            story.extend([Spacer(1, 18), Paragraph(title, styles['SectionTitle']),
                          Paragraph(description, styles['SectionDesc']), _chart_content(rows, chart_kind, styles)])
    story.extend([PageBreak(), Paragraph(f'{escape(kind.title())} records', styles['SectionTitle'])])
    # PDF is a bounded readable companion; Excel retains all available feedback detail.
    visible = records[:200]
    story.append(Paragraph(f'Showing {len(visible)} of {len(records)} available detail records '
                           f'({matching} matching in loaded scope). PDF detail limit: 200. '
                           'Use Excel for the complete available detail scope. Missing values are not zero.',
                           styles['SectionDesc']))
    if not visible:
        story.append(Paragraph('No matching records found for the selected criteria.', styles['SectionDesc']))
    headings, rows = display_table(kind, visible)
    for index, row in enumerate(rows, 1):
        story.extend([Spacer(1, 12), Paragraph(f'Record {index}', styles['TableCellBold'])])
        table = _style_table([[Paragraph('Field', styles['TableHeader']), Paragraph('Value', styles['TableHeader'])]] +
                             [[Paragraph(escape(label), styles['TableCellBold']),
                               Paragraph(escape(value), styles['TableCell'])] for label, value in zip(headings, row)],
                             colWidths=[150, 373])
        table.splitInRow = 1
        story.append(table)
    return story


def export_system_report_pdf(data, target, admin_profile=None):
    """
    Generates an executive PDF report for TravelMate Central Administration.
    data: report dictionary from /api/fr13/reports/summary or _summary()
    target: file path or BytesIO buffer
    """
    from xml.sax.saxutils import escape
    doc = SimpleDocTemplate(
        target,
        pagesize=A4,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=48
    )
    styles = _get_styles()
    story = []

    counts = data.get("counts", {}) if isinstance(data, dict) else {}
    summary = data.get("summary", {}) if isinstance(data, dict) else {}
    admin_profile = admin_profile or {}

    admin_name = escape(str(admin_profile.get("name") or "TravelMate Administrator"))
    admin_email = escape(str(admin_profile.get("email") or "-"))
    gen_date = _generated_at(data)
    from services.admin_report_csv import REPORT_TITLES
    report_kind = (data.get('criteria') or {}).get('reportType', 'system_summary')
    report_title = ('Administrator System Activity Report' if report_kind == 'system_summary'
                    else REPORT_TITLES[report_kind].replace('TravelMate ', ''))
    story.extend(_cover(report_title, "TravelMate Central Administration",
                        data, gen_date, styles, "Confidential - Internal system activity"))

    # 1. Header Banner & Branding
    header_data = [
        [
            Paragraph("TRAVELMATE • CENTRAL ADMINISTRATION", styles["Tag"]),
            Paragraph(f"AUDIT REF: SYS-REPORT-{datetime.now().strftime('%Y%m%d')}", styles["TableCellMuted"])
        ],
        [
            Paragraph(escape(report_title), styles["BrandHeader"]),
            Paragraph("<b>Classification:</b> Confidential", styles["TableCellBold"])
        ],
        [
            Paragraph("Platform performance audit, user account status, content moderation, and operational activity.", styles["BrandSubheader"]),
            Paragraph(f"<b>Date:</b> {gen_date}", styles["TableCellMuted"])
        ]
    ]
    header_table = Table(header_data, colWidths=[360, 163])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#2563EB"), spaceBefore=2, spaceAfter=12))

    # 2. Administration Metadata Box
    meta_data = [
        [
            Paragraph("Audited By:", styles["MetaLabel"]),
            Paragraph(admin_name, styles["MetaValue"]),
            Paragraph("Administrator Email:", styles["MetaLabel"]),
            Paragraph(admin_email, styles["MetaValue"]),
        ],
        [
            Paragraph("System Environment:", styles["MetaLabel"]),
            Paragraph("Configured TravelMate data source", styles["MetaValue"]),
            Paragraph("Generation Timestamp:", styles["MetaLabel"]),
            Paragraph(gen_date, styles["MetaValue"]),
        ]
    ]
    meta_table = Table(meta_data, colWidths=[120, 160, 120, 123])
    meta_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
        ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#E2E8F0")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#F1F5F9")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 14))

    criteria=data.get('criteria') or {}
    scope=f"Scope: {criteria.get('reportType','system_summary')}; {criteria.get('startDate') or 'all dates'} to {criteria.get('endDate') or 'all dates'}; filter: {criteria.get('filter') or 'none'}."
    story.append(Paragraph(escape(scope),styles['SectionDesc']))
    if data.get('dataLimited'):
        story.append(Paragraph('Partial results: a source is unavailable or exceeds its loading bound; not the complete system history.',styles['SectionDesc']))
    if data.get('recordsLimited'):
        story.append(Paragraph('Non-feedback details contain at most 200 matching records; feedback uses its separately disclosed scope.',styles['SectionDesc']))
    if data.get('feedbackSources'):
        from services.admin_report_csv import feedback_scope_text
        story.append(Paragraph(escape(feedback_scope_text(data)), styles['SectionDesc']))

    if report_kind != 'system_summary':
        story.extend(_selected_admin_report(data, styles))
        doc.build(story, canvasmaker=NumberedCanvas)
        return

    # 3. Executive KPI Metric Cards
    u_total = counts.get("users", summary.get("users", {}).get("total", 0))
    p_total = counts.get("tourism_packages", summary.get("packages", {}).get("total", 0))
    c_total = counts.get("promotional_campaigns", summary.get("campaigns", {}).get("total", 0))
    f_total = counts.get("feedback", summary.get("feedback", {}).get("total", 0))

    card1 = _build_kpi_card(u_total, "Registered Users", styles, "#F8FAFC", "#CBD5E1", "#0F172A")
    card2 = _build_kpi_card(p_total, "Tourism Packages", styles, "#F0FDFA", "#99F6E4", "#0F766E")
    card3 = _build_kpi_card(c_total, "Promotions", styles, "#EFF6FF", "#BFDBFE", "#1E40AF")
    card4 = _build_kpi_card(f_total, "Traveller Feedback", styles, "#FEFCE8", "#FEF08A", "#854D0E")

    cards_table = Table([[card1, card2, card3, card4]], colWidths=[127.75] * 4)
    cards_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(cards_table)
    story.append(Spacer(1, 16))

    story.extend(_financial_summary(summary.get("payments") or {}, styles))
    story.extend(_visual_analytics(data, styles))

    # 4. Section 1: User Accounts Distribution
    u_data = summary.get("users", {})
    story.append(Paragraph("1. User Accounts & Access Distribution", styles["SectionTitle"]))
    story.append(Paragraph("Summary of registered accounts across Travellers, Tourism Operators, and System Administrators.", styles["SectionDesc"]))
    story.append(Spacer(1, 6))

    user_rows = [
        [Paragraph("Account Category / Role", styles["TableHeader"]), Paragraph("Total Accounts", styles["TableHeader"]), Paragraph("Status / Proportion", styles["TableHeader"])],
        [Paragraph("Traveller Accounts", styles["TableCellBold"]), Paragraph(str(u_data.get("travellers", 0)), styles["TableCellBold"]), Paragraph("End-user mobile travellers", styles["TableCellMuted"])],
        [Paragraph("Tourism Operators", styles["TableCellBold"]), Paragraph(str(u_data.get("operators", 0)), styles["TableCellBold"]), Paragraph("Registered business accounts", styles["TableCellMuted"])],
        [Paragraph("System Administrators", styles["TableCellBold"]), Paragraph(str(u_data.get("administrators", 0)), styles["TableCellBold"]), Paragraph("Central administrative control", styles["TableCellMuted"])],
        [Paragraph("Active Accounts", styles["TableCellBold"]), Paragraph(str(u_data.get("active", 0)), styles["TableCellBold"]), Paragraph("Permitted system access", styles["TableCellBold"])],
        [Paragraph("Deactivated Accounts", styles["TableCellBold"]), Paragraph(str(u_data.get("deactivated", 0)), styles["TableCellBold"]), Paragraph("Suspended accounts", styles["TableCellMuted"])],
    ]
    story.append(_style_table(user_rows, colWidths=[180, 140, 203], header_bg="#0F172A"))
    story.append(Spacer(1, 16))

    # 5. Section 2: Tourism Packages Approval & Moderation
    p_data = summary.get("packages", {})
    story.append(Paragraph("2. Tourism Packages Status & Moderation", styles["SectionTitle"]))
    story.append(Paragraph("Review status of submitted tourism operator packages across destinations.", styles["SectionDesc"]))
    story.append(Spacer(1, 6))

    pkg_rows = [
        [Paragraph("Approval Status", styles["TableHeader"]), Paragraph("Package Count", styles["TableHeader"]), Paragraph("Moderation Notes", styles["TableHeader"])],
        [Paragraph("Approved Packages", styles["TableCellBold"]), Paragraph(str(p_data.get("approved", 0)), styles["TableCellBold"]), Paragraph("Publication also requires availability", styles["TableCellBold"])],
        [Paragraph("Pending Review", styles["TableCellBold"]), Paragraph(str(p_data.get("pending", 0)), styles["TableCellBold"]), Paragraph("Awaiting administrator review", styles["TableCellMuted"])],
        [Paragraph("Rejected Packages", styles["TableCellBold"]), Paragraph(str(p_data.get("rejected", 0)), styles["TableCellBold"]), Paragraph("Returned with review comments", styles["TableCellMuted"])],
        [Paragraph("Draft Packages", styles["TableCellBold"]), Paragraph(str(p_data.get("draft", 0)), styles["TableCellBold"]), Paragraph("Saved by operators (not submitted)", styles["TableCellMuted"])],
    ]
    story.append(_style_table(pkg_rows, colWidths=[180, 140, 203], header_bg="#1E293B"))
    story.append(Spacer(1, 16))

    # 6. Section 3: Promotional Campaigns & Feedback
    c_data = summary.get("campaigns", {})
    f_data = summary.get("feedback", {})
    story.append(Paragraph("3. Promotional Content & Traveller Feedback", styles["SectionTitle"]))
    story.append(Paragraph("Oversight of promotional marketing campaigns and destination review moderation.", styles["SectionDesc"]))
    story.append(Spacer(1, 6))

    extra_rows = [
        [Paragraph("Category", styles["TableHeader"]), Paragraph("Count", styles["TableHeader"]), Paragraph("Moderation & Operations Status", styles["TableHeader"])],
        [Paragraph("Approved Campaigns", styles["TableCellBold"]), Paragraph(str(c_data.get("approved", 0)), styles["TableCellBold"]), Paragraph("Activity depends on dates and package eligibility", styles["TableCellMuted"])],
        [Paragraph("Pending Campaigns", styles["TableCellBold"]), Paragraph(str(c_data.get("pending", 0)), styles["TableCellBold"]), Paragraph("Awaiting campaign approval", styles["TableCellMuted"])],
        [Paragraph("Total Feedback", styles["TableCellBold"]), Paragraph(str(f_data.get("total", 0)), styles["TableCellBold"]), Paragraph("Loaded authorized genuine and evaluation sources", styles["TableCellMuted"])],
        [Paragraph("Genuine Feedback", styles["TableCellBold"]), Paragraph(str(f_data.get("genuine", 0)), styles["TableCellBold"]), Paragraph("Genuine Traveller feedback", styles["TableCellMuted"])],
        [Paragraph("Evaluation Feedback", styles["TableCellBold"]), Paragraph(str(f_data.get("evaluation", 0)), styles["TableCellBold"]), Paragraph("Synthetic FYP evaluation; not customer testimonials", styles["TableCellMuted"])],
        [Paragraph("Reviewed Feedback", styles["TableCellBold"]), Paragraph(str(f_data.get("reviewed", 0)), styles["TableCellBold"]), Paragraph("May overlap visible or hidden categories", styles["TableCellMuted"])],
        [Paragraph("Hidden or Removed Feedback", styles["TableCellBold"]), Paragraph(str(f_data.get("hiddenOrRemoved", 0)), styles["TableCellBold"]), Paragraph("Effective hidden, removed or rejected state", styles["TableCellMuted"])],
        [Paragraph("Visible Feedback", styles["TableCellBold"]), Paragraph(str(f_data.get("visible", 0)), styles["TableCellBold"]), Paragraph("Published within each source's visibility scope", styles["TableCellBold"])],
        [Paragraph("Feedback Pending Moderation", styles["TableCellBold"]), Paragraph(str(f_data.get("pending", 0)), styles["TableCellBold"]), Paragraph("Queued for review", styles["TableCellMuted"])],
        [Paragraph("Removed Feedback", styles["TableCellBold"]), Paragraph(str(f_data.get("removed", 0)), styles["TableCellBold"]), Paragraph("Flagged & hidden from travellers", styles["TableCellMuted"])],
        [Paragraph("Hotel Bookings", styles["TableCellBold"]), Paragraph(str(counts.get("hotel_bookings", 0)), styles["TableCellBold"]), Paragraph("Recorded hotel bookings; supplier status is separate", styles["TableCellMuted"])],
        [Paragraph("Payment Records", styles["TableCellBold"]), Paragraph(str(counts.get("payment_records", 0)), styles["TableCellBold"]), Paragraph("Platform payment/order records", styles["TableCellMuted"])],
    ]
    story.append(_style_table(extra_rows, colWidths=[180, 140, 203], header_bg="#334155"))

    doc.build(story, canvasmaker=NumberedCanvas)
