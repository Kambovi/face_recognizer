"""Files made from a payroll run: payslip PDFs, salary register, bank
transfer sheet, EPFO ECR, ESIC contribution sheet, PT register."""
from __future__ import annotations

import io
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services import csvsafe

INK = colors.HexColor("#111827")
MUTED = colors.HexColor("#6B7280")
LINE = colors.HexColor("#E5E7EB")
BRAND = {"business": "#4F46E5", "school": "#EA580C", "hospital": "#0D9488"}


def _inr(n: float | int) -> str:
    """Indian digit grouping: 1234567 -> 12,34,567"""
    neg = n < 0
    s = f"{abs(int(round(n)))}"
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts: list[str] = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return ("-" if neg else "") + s


_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
         "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _words_below_100(n: int) -> str:
    return _ONES[n] if n < 20 else (_TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else ""))


def _words_below_1000(n: int) -> str:
    h, rest = divmod(n, 100)
    out = (_ONES[h] + " Hundred") if h else ""
    if rest:
        out += (" " if out else "") + _words_below_100(rest)
    return out


def amount_in_words(n: int) -> str:
    """Indian system: crore / lakh / thousand."""
    if n == 0:
        return "Zero"
    parts = []
    for div, name in ((10_000_000, "Crore"), (100_000, "Lakh"), (1000, "Thousand")):
        q, n = divmod(n, div)
        if q:
            parts.append(f"{_words_below_1000(q) if q < 1000 else amount_in_words(q)} {name}")
    if n:
        parts.append(_words_below_1000(n))
    return " ".join(parts)


def _month_label(month: str) -> str:
    import calendar

    y, m = month.split("-")
    return f"{calendar.month_name[int(m)]} {y}"


def _slip_story(slip: dict[str, Any], profile: dict[str, Any], styles: dict[str, ParagraphStyle]) -> list[Any]:
    brand = colors.HexColor(BRAND.get(str(profile.get("org_type")), BRAND["business"]))
    org = str(profile.get("org_name") or "")
    head = Table([[Paragraph(f"<b>{org}</b>", styles["org"]),
                   Paragraph(f"Payslip -- {_month_label(slip['month'])}", styles["right"])]],
                 colWidths=[110 * mm, 70 * mm])
    head.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, 0), 1.2, brand), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    a = slip.get("attendance") or {}
    info = [
        ["Employee", f"{slip['name']} ({slip['emp_code']})", "Paid days", f"{slip['paid_days']:g} / {slip['days_in_month']}"],
        ["Department", slip.get("department") or "-", "LOP days", f"{slip['lop_days']:g}"],
        ["Designation", slip.get("designation") or "-", "Present / Leave", f"{a.get('present') or 0} / {a.get('leave') or 0:g}"],
        ["UAN", slip.get("uan") or "-", "ESIC IP", slip.get("esic_ip") or "-"],
        ["Joined", slip.get("date_of_joining") or "-", "OT hours", f"{a.get('ot_hours') or 0:g}"],
    ]
    it = Table(info, colWidths=[28 * mm, 72 * mm, 32 * mm, 48 * mm])
    it.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 8.5), ("TEXTCOLOR", (0, 0), (0, -1), MUTED),
        ("TEXTCOLOR", (2, 0), (2, -1), MUTED), ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]))
    earn = slip["earnings"]
    ded = slip["deductions"]
    n = max(len(earn), len(ded))
    rows: list[list[Any]] = [["Earnings", "Full month", "Earned", "Deductions", "Amount"]]
    for i in range(n):
        e = earn[i] if i < len(earn) else None
        d = ded[i] if i < len(ded) else None
        rows.append([e["label"] if e else "", _inr(e["full"]) if e and e["full"] else "", _inr(e["amount"]) if e else "",
                     d["label"] if d else "", _inr(d["amount"]) if d else ""])
    rows.append(["Gross earnings", _inr(slip["gross_full"]), _inr(slip["gross"]), "Total deductions", _inr(slip["total_deductions"])])
    t = Table(rows, colWidths=[46 * mm, 26 * mm, 26 * mm, 52 * mm, 30 * mm])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5), ("FONT", (0, 1), (-1, -1), "Helvetica", 8.5),
        ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 8.5), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F4F6")),
        ("LINEABOVE", (0, -1), (-1, -1), 0.6, INK), ("ALIGN", (1, 0), (2, -1), "RIGHT"), ("ALIGN", (4, 0), (4, -1), "RIGHT"),
        ("LINEAFTER", (2, 0), (2, -1), 0.4, LINE), ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    net = Table([[f"Net pay: Rs. {_inr(slip['net'])}", f"({amount_in_words(int(slip['net']))} Rupees only)"]],
                colWidths=[60 * mm, 120 * mm])
    net.setStyle(TableStyle([("FONT", (0, 0), (0, 0), "Helvetica-Bold", 11), ("FONT", (1, 0), (1, 0), "Helvetica", 8.5),
                             ("TEXTCOLOR", (0, 0), (0, 0), brand), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                             ("BOX", (0, 0), (-1, -1), 0.6, LINE), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                             ("TOPPADDING", (0, 0), (-1, -1), 7)]))
    er = ", ".join(f"{e['label']} {_inr(e['amount'])}" for e in slip.get("employer", []) if e["amount"])
    foot = Paragraph(
        (f"Employer contributions (not deducted from pay): {er}. " if er else "")
        + "Computer-generated payslip; no signature required.", styles["small"])
    return [KeepTogether([head, Spacer(1, 4 * mm), it, Spacer(1, 4 * mm), t, Spacer(1, 4 * mm), net,
                          Spacer(1, 3 * mm), foot])]


def payslips_pdf(slips: list[dict[str, Any]], profile: dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm,
                            bottomMargin=15 * mm, title="Payslips")
    styles = {
        "org": ParagraphStyle("org", fontName="Helvetica-Bold", fontSize=12, textColor=INK),
        "right": ParagraphStyle("right", fontName="Helvetica", fontSize=10, alignment=2, textColor=MUTED),
        "small": ParagraphStyle("small", fontName="Helvetica", fontSize=7.5, textColor=MUTED, leading=10),
    }
    story: list[Any] = []
    for i, s in enumerate(slips):
        if i:
            story.append(PageBreak())
        story += _slip_story(s, profile, styles)
    if not story:
        story.append(Paragraph("No payslips in this run.", styles["small"]))
    doc.build(story)
    return buf.getvalue()


def _csv(rows: list[list[Any]]) -> str:
    buf = io.StringIO()
    buf.write("﻿")
    csvsafe.writer(buf).writerows(rows)
    return buf.getvalue()


def salary_register_csv(slips: list[dict[str, Any]]) -> str:
    comp = ["basic", "da", "hra", "conveyance", "special", "other"]
    head = ["Emp ID", "Name", "Department", "Days in month", "Paid days", "LOP days", "OT hours",
            *[c.upper() for c in comp], "OT pay", "Other earnings", "Gross", "PF (EE)", "ESI (EE)", "PT", "TDS",
            "Other deductions", "Total deductions", "Net pay", "PF (ER) incl. EPS", "ESI (ER)", "Employer cost", "Warnings"]
    rows: list[list[Any]] = [head]
    for s in slips:
        e: dict[str, float] = {}
        for x in s["earnings"]:
            e[x["code"]] = e.get(x["code"], 0) + x["amount"]
        d: dict[str, float] = {}
        for x in s["deductions"]:
            d[x["code"]] = d.get(x["code"], 0) + x["amount"]
        er = {x["code"]: x["amount"] for x in s.get("employer", [])}
        rows.append([s["emp_code"], s["name"], s.get("department") or "", s["days_in_month"], s["paid_days"], s["lop_days"],
                     (s.get("attendance") or {}).get("ot_hours") or 0, *[e.get(c, 0) for c in comp], e.get("ot", 0),
                     e.get("adj", 0), s["gross"], d.get("pf", 0), d.get("esi", 0), d.get("pt", 0), d.get("tds", 0),
                     d.get("adj", 0), s["total_deductions"], s["net"], er.get("eps", 0) + er.get("epf_er", 0),
                     er.get("esi_er", 0), s["employer_cost"], "; ".join(s.get("warnings") or [])])
    return _csv(rows)


def bank_transfer_csv(slips: list[dict[str, Any]], accounts: dict[str, dict[str, str]], month: str) -> str:
    """Generic bulk-NEFT sheet. Most banks' corporate portals accept these
    columns or map them in one step; adjust to the client's bank template."""
    rows: list[list[Any]] = [["Beneficiary name", "Account number", "IFSC", "Amount", "Payment mode", "Narration", "Emp ID"]]
    for s in slips:
        if s.get("payment_mode", "bank") != "bank" or s["net"] <= 0:
            continue
        acc = accounts.get(s["employee_id"], {})
        rows.append([s["name"], acc.get("account", ""), acc.get("ifsc", ""), f"{s['net']:.2f}", "NEFT",
                     f"Salary {_month_label(month)}", s["emp_code"]])
    return _csv(rows)


def ecr_text(slips: list[dict[str, Any]]) -> str:
    """EPFO ECR 2.0 text file: one line per member, fields separated by #~#:
    UAN, name, gross wages, EPF wages, EPS wages, EDLI wages, EE share,
    EPS contribution, ER share (EPF - EPS diff), NCP days, refund of advances."""
    lines = []
    for s in slips:
        pf = s.get("pf")
        if not pf:
            continue
        fields = [s.get("uan") or "", s["name"].upper(), s["gross"], pf["epf_wage"], pf["eps_wage"], pf["edli_wage"],
                  pf["employee"], pf["eps"], pf["employer_epf"], int(round(s["lop_days"])), 0]
        lines.append("#~#".join(str(f) for f in fields))
    return "\n".join(lines) + ("\n" if lines else "")


def esi_csv(slips: list[dict[str, Any]]) -> str:
    """ESIC monthly contribution upload: IP number, name, days, wages, reason
    code for 0 days (blank here; fill per ESIC codes if needed)."""
    rows: list[list[Any]] = [["IP Number", "IP Name", "No of Days for which wages paid", "Total Monthly Wages",
                              "Reason Code for Zero workings days", "Last Working Day", "Employee contribution",
                              "Employer contribution"]]
    for s in slips:
        e = s.get("esi")
        if not e:
            continue
        rows.append([s.get("esic_ip") or "", s["name"], int(round(e["days"])), e["wage"], "",
                     s.get("date_of_leaving") or "", e["employee"], e["employer"]])
    return _csv(rows)


def pt_register_csv(slips: list[dict[str, Any]]) -> str:
    rows: list[list[Any]] = [["Emp ID", "Name", "State", "Gross", "Professional tax"]]
    for s in slips:
        pt = sum(d["amount"] for d in s["deductions"] if d["code"] == "pt")
        rows.append([s["emp_code"], s["name"], s.get("pt_state") or "", s["gross"], pt])
    return _csv(rows)
