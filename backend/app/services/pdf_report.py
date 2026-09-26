"""Monthly attendance report as a one-to-three page PDF (for the owner /
principal / medical superintendent, and to attach to a monthly review).

Built from the same timesheet as payroll, so the numbers always agree.
"""
from __future__ import annotations

import io
from collections import defaultdict
from datetime import date, datetime
from zoneinfo import ZoneInfo

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.client_profile import get_profile
from app.services.timesheet import build_timesheet, person_totals

LOCAL_TZ = ZoneInfo("Asia/Kolkata")
INK = colors.HexColor("#111827")
MUTED = colors.HexColor("#6B7280")
LINE = colors.HexColor("#E5E7EB")
BRAND = {"business": "#4F46E5", "school": "#EA580C", "hospital": "#0D9488"}


def _pct(a: float, b: float) -> float:
    return round(100 * a / b, 1) if b else 0.0


def _table(rows: list[list[object]], widths: list[float], align_right_from: int = 1) -> Table:
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 8.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
        ("TEXTCOLOR", (0, 1), (-1, -1), INK),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, LINE),
        ("LINEBELOW", (0, 1), (-1, -1), 0.3, LINE),
        ("ALIGN", (align_right_from, 0), (-1, -1), "RIGHT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


async def monthly_pdf(db: AsyncSession, month_start: date, month_end: date) -> bytes:
    profile = await get_profile(db)
    brand = colors.HexColor(BRAND.get(str(profile.get("org_type")), BRAND["business"]))
    person_word = str(profile.get("person_label_plural", "Employees"))
    dept_word = str(profile.get("department_label", "Department"))
    ts = await build_timesheet(db, month_start, month_end)
    totals = {p.id: person_totals(ts, p.id) for p in ts.people}

    working = sum(t["working_days"] for t in totals.values())
    paid = sum(t["present"] + 0.5 * t["half_days"] for t in totals.values())
    late = sum(int(t["late_days"]) for t in totals.values())
    ot = round(sum(t["ot_hours"] for t in totals.values()), 1)
    absent = sum(int(t["absent"]) for t in totals.values())

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Title"], fontSize=18, leading=22, alignment=0, textColor=INK, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=11, textColor=INK, spaceBefore=10, spaceAfter=4)
    small = ParagraphStyle("s", parent=styles["Normal"], fontSize=8, textColor=MUTED, leading=10)

    story: list[object] = [
        Paragraph(f"{profile.get('org_name')}", h1),
        Paragraph(
            f"Attendance report · {month_start.strftime('%B %Y')} · generated "
            f"{datetime.now(LOCAL_TZ).strftime('%d %b %Y %H:%M')}",
            small,
        ),
        Spacer(1, 6 * mm),
    ]

    # KPI tiles
    tiles = [
        ("Attendance", f"{_pct(paid, working)}%"),
        (person_word, str(len(ts.people))),
        ("Man-days present", f"{paid:g}"),
        ("Absent days", str(absent)),
        ("Late arrivals", str(late)),
        ("Overtime hours", f"{ot:g}"),
    ]
    kpi = Table([[t[1] for t in tiles], [t[0] for t in tiles]], colWidths=[30 * mm] * 6)
    kpi.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 15),
        ("TEXTCOLOR", (0, 0), (-1, 0), INK),
        ("TEXTCOLOR", (0, 0), (0, 0), brand),
        ("FONT", (0, 1), (-1, 1), "Helvetica", 7.5),
        ("TEXTCOLOR", (0, 1), (-1, 1), MUTED),
        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
        ("TOPPADDING", (0, 0), (-1, 0), 7),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 7),
    ]))
    story += [kpi, Spacer(1, 4 * mm)]

    # Daily present chart (working days only)
    days = [d for d in ts.days if any(ts.records[(p.id, d)].status in ("P", "HD", "A") for p in ts.people)]
    if days:
        present = [
            sum(1 for p in ts.people if ts.records[(p.id, d)].status in ("P", "HD", "WOP")) for d in days
        ]
        roster = [sum(1 for p in ts.people if ts.records[(p.id, d)].status != "-") for d in days]
        drawing = Drawing(180 * mm, 55 * mm)
        drawing.add(String(0, 52 * mm, f"{person_word} present per working day", fontName="Helvetica-Bold", fontSize=9, fillColor=INK))
        chart = VerticalBarChart()
        chart.x, chart.y, chart.width, chart.height = 8 * mm, 8 * mm, 170 * mm, 38 * mm
        chart.data = [present]
        chart.valueAxis.valueMin = 0
        chart.valueAxis.valueMax = max(roster + [1])
        chart.valueAxis.labels.fontSize = 6.5
        chart.valueAxis.strokeColor = LINE
        chart.valueAxis.gridStrokeColor = LINE
        chart.valueAxis.visibleGrid = True
        chart.categoryAxis.categoryNames = [d.strftime("%d") for d in days]
        chart.categoryAxis.labels.fontSize = 6.5
        chart.categoryAxis.strokeColor = LINE
        chart.bars[0].fillColor = brand
        chart.bars[0].strokeColor = None
        chart.barSpacing = 1
        drawing.add(chart)
        story += [drawing]

    # Departments
    by_dept: dict[str, list[str]] = defaultdict(list)
    for p in ts.people:
        by_dept[p.department or "Unassigned"].append(p.id)
    dept_rows: list[list[object]] = [[dept_word, "People", "Attendance", "Absent days", "Late days", "OT hours"]]
    for name, ids in sorted(by_dept.items(), key=lambda kv: _pct(
        sum(totals[i]["present"] + 0.5 * totals[i]["half_days"] for i in kv[1]), sum(totals[i]["working_days"] for i in kv[1]))):
        w = sum(totals[i]["working_days"] for i in ids)
        pr = sum(totals[i]["present"] + 0.5 * totals[i]["half_days"] for i in ids)
        dept_rows.append([name, len(ids), f"{_pct(pr, w)}%", sum(int(totals[i]["absent"]) for i in ids),
                          sum(int(totals[i]["late_days"]) for i in ids), round(sum(totals[i]["ot_hours"] for i in ids), 1)])
    story += [Paragraph(f"By {dept_word.lower()} (lowest attendance first)", h2),
              _table(dept_rows, [60 * mm, 20 * mm, 25 * mm, 25 * mm, 22 * mm, 22 * mm])]

    # Contractors
    by_ctr: dict[str, list[str]] = defaultdict(list)
    for p in ts.people:
        by_ctr[p.contractor or "Own staff"].append(p.id)
    if len(by_ctr) > 1 or "Own staff" not in by_ctr:
        ctr_rows: list[list[object]] = [["Contractor", "Headcount", "Man-days", "Absent days", "OT hours"]]
        for name, ids in sorted(by_ctr.items()):
            ctr_rows.append([name, len(ids), f"{sum(totals[i]['present'] + 0.5 * totals[i]['half_days'] for i in ids):g}",
                             sum(int(totals[i]["absent"]) for i in ids), round(sum(totals[i]["ot_hours"] for i in ids), 1)])
        story += [Paragraph("By contractor", h2), _table(ctr_rows, [70 * mm, 25 * mm, 25 * mm, 27 * mm, 27 * mm])]

    # Needs attention
    people = {p.id: p for p in ts.people}
    lowest = sorted(totals.items(), key=lambda kv: _pct(kv[1]["present"] + 0.5 * kv[1]["half_days"], kv[1]["working_days"]))[:10]
    late_top = [kv for kv in sorted(totals.items(), key=lambda kv: -int(kv[1]["late_days"])) if kv[1]["late_days"]][:10]
    low_header: list[object] = ["Name", "ID", "Attendance", "Absent"]
    low_rows: list[list[object]] = [low_header] + [
        [people[i].name, people[i].emp_code,
         f"{_pct(t['present'] + 0.5 * t['half_days'], t['working_days'])}%", int(t["absent"])]
        for i, t in lowest if t["working_days"]
    ]
    late_header: list[object] = ["Name", "ID", "Late days", "Late min"]
    late_rows: list[list[object]] = [late_header] + [
        [people[i].name, people[i].emp_code, int(t["late_days"]), int(t["late_minutes"])] for i, t in late_top
    ]
    both = Table([[
        [Paragraph("Lowest attendance", h2), _table(low_rows, [40 * mm, 18 * mm, 18 * mm, 13 * mm], 2)],
        [Paragraph("Most late arrivals", h2), _table(late_rows, [40 * mm, 18 * mm, 15 * mm, 15 * mm], 2)],
    ]], colWidths=[92 * mm, 92 * mm])
    both.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story += [both, Spacer(1, 5 * mm), Paragraph(
        "Attendance = man-days present ÷ working days (weekly offs excluded; half day = 0.5). Late = first sighting "
        "after shift start + grace. Overtime = time after shift end, per the rules in Settings → Payroll &amp; overtime.",
        small,
    )]

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=13 * mm, rightMargin=13 * mm, topMargin=14 * mm,
                            bottomMargin=14 * mm, title=f"Attendance {month_start.strftime('%B %Y')}")
    doc.build(story)
    return buf.getvalue()
