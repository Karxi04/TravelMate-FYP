# Codex Handoff: TravelMate Executive Report PDF Cover Page & Visual Charts

## 1. Overview & Context

This document provides a complete technical specification and implementation blueprint for enhancing the backend PDF report generation in `backend_api/services/report_service.py`.

In the current milestone, the frontend presentation of the **Tourism Operator Business Performance Report** (`/analytics`) and the **Administrator System Activity Report** (`/admin/reports`) has been enhanced with:
1. Pure SVG & CSS responsive charts (Donut charts, Horizontal Bar charts, Progress metric bars).
2. Ink Wash themed executive A4 cover page dossiers.
3. Clean `@media print` rules for browser-based PDF printing.

To maintain strict architectural safety and honor our non-negotiable requirement (**never modify backend financial calculations or export contracts directly in frontend turns**), this guide documents the exact changes needed if a backend ReportLab-rendered PDF cover page and visual chart suite is implemented by Codex.

---

## 2. Target File & Function Scope

- **File:** `backend_api/services/report_service.py`
- **Functions:**
  1. `export_operator_report(data, target, operator_profile=None)` (Line 217)
  2. `export_system_report_pdf(data, target, admin_profile=None)` (Line 465)

### Safe Imports
ReportLab provides built-in vector drawing and charting primitives that require zero additional C libraries or network dependencies:
```python
from reportlab.graphics.shapes import Drawing, Rect, String, Group, Circle
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.charts.barcharts import HorizontalBarChart
from reportlab.graphics.charts.legends import Legend
from reportlab.platypus import PageBreak, Spacer, Table, Paragraph
from reportlab.lib import colors
```

---

## 3. Executive Cover Page Flowable Blueprint

Both PDF generators use `SimpleDocTemplate(target, pagesize=A4, ...)` with a list of flowables (`story`).

To introduce an A4 Executive Cover Page without disrupting existing table pagination:
1. Append the Cover Page elements to `story` first.
2. Follow immediately with `story.append(PageBreak())`.
3. The existing report header and detailed tables begin on Page 2.

### Operator Report Cover Page Structure
```python
def _build_operator_cover_page(data, operator_profile, styles):
    story = []
    
    # 1. Top Decorative Brand Banner
    brand_table = Table([
        [Paragraph("<font size=16 color='#FFFFFF'><b>TravelMate</b></font><br/><font size=9 color='#94A3B8'>Penang Tourism Platform</font>", styles["Normal"]),
         Paragraph("<font size=9 color='#CBD5E1'><b>EXECUTIVE AUDIT DOSSIER</b></font>", styles["Normal"])]
    ], colWidths=[350, 160])
    brand_table.setStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#0F172A')),
        ('PADDING', (0,0), (-1,-1), 16),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (1,0), (1,0), 'RIGHT'),
    ])
    story.append(brand_table)
    story.append(Spacer(1, 40))
    
    # 2. Main Title & Subtitle
    story.append(Paragraph("<font color='#2B6CB0' size=10><b>OPERATOR INTELLIGENCE REPORT</b></font>", styles["Normal"]))
    story.append(Spacer(1, 8))
    story.append(Paragraph("<b>Tourism Operator Business Performance Report</b>", styles["Title"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph("Authoritative operational audit, catalog moderation intelligence, and commercial fulfillment metrics for Penang tourism packages.", styles["Normal"]))
    story.append(Spacer(1, 50))
    
    # 3. Metadata Matrix Table
    op_name = (operator_profile.get("businessName") if operator_profile else None) or "Verified Tourism Partner"
    gen_at = (data.get("generatedAt") or "Live Session")[:10]
    meta_data = [
        [Paragraph("<b>OPERATOR ENTITY</b>", styles["Normal"]), Paragraph("<b>REPORTING DATE</b>", styles["Normal"])],
        [Paragraph(op_name, styles["Normal"]), Paragraph(gen_at, styles["Normal"])],
        [Paragraph("<b>LEDGER AUTHORITY</b>", styles["Normal"]), Paragraph("<b>SETTLEMENT MODE</b>", styles["Normal"])],
        [Paragraph("Cloud Firestore • Bounded Ledger", styles["Normal"]), Paragraph("Stripe Test Mode Transactions", styles["Normal"])]
    ]
    meta_table = Table(meta_data, colWidths=[255, 255])
    meta_table.setStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8FAFC')),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#E2E8F0')),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
        ('PADDING', (0,0), (-1,-1), 12),
    ])
    story.append(meta_table)
    story.append(Spacer(1, 80))
    
    # 4. Confidentiality Notice & Page Break
    story.append(Paragraph("<font size=8 color='#64748B'><b>CONFIDENTIAL &amp; PROPRIETARY • TRAVELMATE FYP DEMONSTRATION</b><br/>"
                           "This document contains operational data extracted from TravelMate records. Catalog valuations reflect approved catalog rates and do not represent realized revenue.</font>", styles["Normal"]))
    story.append(PageBreak())
    return story
```

---

## 4. Vector Charts Flowable Blueprint (ReportLab Graphics)

### Donut / Pie Chart: Tourism Package Status Distribution
```python
def _build_package_status_pie(summary):
    d = Drawing(400, 160)
    pc = Pie()
    pc.x = 20
    pc.y = 10
    pc.width = 140
    pc.height = 140
    
    app = summary.get("approvedPackages", 0)
    pen = summary.get("pendingPackages", 0)
    rej = summary.get("rejectedPackages", 0)
    dra = summary.get("draftPackages", 0)
    
    if (app + pen + rej + dra) == 0:
        pc.data = [1]
        pc.labels = ['No Data']
        pc.slices.strokeColor = colors.HexColor("#CBD5E1")
    else:
        pc.data = [app, pen, rej, dra]
        pc.labels = [f"Approved ({app})", f"Review ({pen})", f"Needs Changes ({rej})", f"Draft ({dra})"]
        pc.slices[0].fillColor = colors.HexColor("#16A34A")  # Green
        pc.slices[1].fillColor = colors.HexColor("#D97706")  # Amber
        pc.slices[2].fillColor = colors.HexColor("#DC2626")  # Danger
        pc.slices[3].fillColor = colors.HexColor("#64748B")  # Slate
    
    d.add(pc)
    return d
```

### Horizontal Bar Chart: Operational Fulfilment Breakdown
```python
def _build_fulfillment_bar_chart(summary):
    d = Drawing(480, 130)
    chart = HorizontalBarChart()
    chart.x = 160
    chart.y = 15
    chart.height = 100
    chart.width = 300
    
    ful = summary.get("fulfilledBookings", 0)
    pen = summary.get("pendingFulfillmentBookings", 0)
    tot = summary.get("bookingRecords", 0)
    other = max(0, tot - ful - pen)
    
    chart.data = [[ful], [pen], [other]]
    chart.categoryAxis.categoryNames = ['Fulfilment Progress']
    chart.bars[0].fillColor = colors.HexColor("#2B6CB0")
    chart.bars[1].fillColor = colors.HexColor("#D97706")
    chart.bars[2].fillColor = colors.HexColor("#94A3B8")
    d.add(chart)
    return d
```

---

## 5. Non-Negotiable Contract Safeguards

When Codex implements these charts in `report_service.py`:
1. **Never mutate monetary calculations:**
   - Continue reading `summary.get('totalPaidRevenue', 0.0)`
   - Continue reading `summary.get('totalPackageValue', 0.0)`
   - Continue reading `summary.get('testPaidTotal', 0.0)`
2. **Never change CSV export contracts:**
   - Functions `export_operator_report_csv` and `export_system_report_csv` remain strictly text-based CSV.
   - Do NOT attempt to output binary images or SVG into CSV files.
3. **Run regression tests:**
   ```bash
   pytest -c pytest.ini backend_api/tests/test_fr12_operator_analytics.py backend_api/tests/test_fr13_commerce_reporting.py
   ```
