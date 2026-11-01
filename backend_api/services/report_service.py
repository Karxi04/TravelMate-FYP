import io
from datetime import datetime, timezone
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
    HRFlowable
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
    operator_profile = {key: escape(str(value)) for key, value in (operator_profile or {}).items() if value is not None}

    company_name = operator_profile.get("companyName") or operator_profile.get("businessName") or "Tourism Operator"
    rep_name = operator_profile.get("name") or operator_profile.get("fullName") or "Operator Representative"
    reg_no = operator_profile.get("registrationNo") or "-"
    contact = operator_profile.get("businessContact") or operator_profile.get("phoneNo") or "-"
    email = operator_profile.get("email") or operator_profile.get("businessEmail") or "-"
    gen_date = datetime.now().strftime("%d %B %Y, %H:%M:%S UTC")

    # 1. Header Banner & Branding
    header_data = [
        [
            Paragraph("TRAVELMATE • TOURISM OPERATOR PORTAL", styles["Tag"]),
            Paragraph(f"REPORT REF: OP-ANALYTICS-{datetime.now().strftime('%Y%m%d')}", styles["TableCellMuted"])
        ],
        [
            Paragraph("Business Analytics & Performance Report", styles["BrandHeader"]),
            Paragraph("<b>Status:</b> Active Account", styles["TableCellBold"])
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
    card3 = _build_kpi_card(total_campaigns, "Active Campaigns", styles, "#EFF6FF", "#BFDBFE", "#1E40AF")
    card4 = _build_kpi_card(f"RM {total_value:,.2f}", "Total Portfolio Value", styles, "#F0FDFA", "#99F6E4", "#0F766E")

    cards_table = Table([[card1, card2, card3, card4]], colWidths=[127, 127, 127, 142])
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
    gen_date = datetime.now(timezone.utc).strftime("%d %B %Y, %H:%M:%S UTC")

    # 1. Header Banner & Branding
    header_data = [
        [
            Paragraph("TRAVELMATE • CENTRAL ADMINISTRATION", styles["Tag"]),
            Paragraph(f"AUDIT REF: SYS-REPORT-{datetime.now().strftime('%Y%m%d')}", styles["TableCellMuted"])
        ],
        [
            Paragraph("Administrator System Activity Report", styles["BrandHeader"]),
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
        story.append(Paragraph('Partial results: up to 500 records per source category; not the complete system history.',styles['SectionDesc']))
    if data.get('recordsLimited'):
        story.append(Paragraph('Detailed exports contain at most 200 matching records; summary counts cover the loaded source scope.',styles['SectionDesc']))

    # 3. Executive KPI Metric Cards
    u_total = counts.get("users", summary.get("users", {}).get("total", 0))
    p_total = counts.get("tourism_packages", summary.get("packages", {}).get("total", 0))
    c_total = counts.get("promotional_campaigns", summary.get("campaigns", {}).get("total", 0))
    f_total = counts.get("feedback", summary.get("feedback", {}).get("total", 0))

    card1 = _build_kpi_card(u_total, "Registered Users", styles, "#F8FAFC", "#CBD5E1", "#0F172A")
    card2 = _build_kpi_card(p_total, "Tourism Packages", styles, "#F0FDFA", "#99F6E4", "#0F766E")
    card3 = _build_kpi_card(c_total, "Promotions", styles, "#EFF6FF", "#BFDBFE", "#1E40AF")
    card4 = _build_kpi_card(f_total, "Traveller Feedback", styles, "#FEFCE8", "#FEF08A", "#854D0E")

    cards_table = Table([[card1, card2, card3, card4]], colWidths=[127, 127, 127, 142])
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
        [Paragraph("Visible Feedback", styles["TableCellBold"]), Paragraph(str(f_data.get("visible", 0)), styles["TableCellBold"]), Paragraph("Published traveller reviews", styles["TableCellBold"])],
        [Paragraph("Feedback Pending Moderation", styles["TableCellBold"]), Paragraph(str(f_data.get("pending", 0)), styles["TableCellBold"]), Paragraph("Queued for review", styles["TableCellMuted"])],
        [Paragraph("Removed Feedback", styles["TableCellBold"]), Paragraph(str(f_data.get("removed", 0)), styles["TableCellBold"]), Paragraph("Flagged & hidden from travellers", styles["TableCellMuted"])],
        [Paragraph("Hotel Bookings", styles["TableCellBold"]), Paragraph(str(counts.get("hotel_bookings", 0)), styles["TableCellBold"]), Paragraph("Recorded reservations", styles["TableCellMuted"])],
        [Paragraph("Payment Records", styles["TableCellBold"]), Paragraph(str(counts.get("payment_records", 0)), styles["TableCellBold"]), Paragraph("Platform payment/order records", styles["TableCellMuted"])],
    ]
    story.append(_style_table(extra_rows, colWidths=[180, 140, 203], header_bg="#334155"))

    doc.build(story, canvasmaker=NumberedCanvas)