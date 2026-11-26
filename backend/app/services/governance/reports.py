"""Report generation: PDF via a minimal built-in PDF writer.

Why not reportlab/weasyprint: Render has memory limits and requirements.txt
deliberately stays lean. A single-page-safe minimal PDF writer (helvetica,
plain text + simple tables) covers inspection/compliance/audit reports
without any new dependency. For pixel-perfect statutory layouts a provider
adapter can be added later — same pattern as OCR/voice.

Report content is assembled from REAL database rows only. Nothing is
invented; sections with no data say "No data".
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import (
    Attendance,
    AuditEvent,
    ComplianceAssessment,
    ComplianceRequirement,
    Contractor,
    ContractorDocument,
    CorrectiveAction,
    EmergencyEvent,
    Incident,
    Inspection,
    InspectionChecklistItem,
    Mine,
    SensorDevice,
    Shift,
    TelemetryReading,
    User,
    Worker,
)

# ---------------------------------------------------------------------------
# Minimal PDF writer (Helvetica, WinAnsi-safe subset)
# ---------------------------------------------------------------------------


def _pdf_escape(text: str) -> str:
    return (text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
            .encode("latin-1", "replace").decode("latin-1"))


def _wrap(text: str, width: int) -> list[str]:
    out = []
    for para in (text or "").splitlines():
        line = ""
        for word in para.split():
            candidate = f"{line} {word}".strip()
            if len(candidate) > width:
                out.append(line)
                line = word
            else:
                line = candidate
        out.append(line)
    return out


class SimplePdf:
    """Accumulates lines then emits a valid single-font PDF."""

    LINE_H = 14
    TOP = 790
    BOTTOM = 50
    WIDTH = 95  # characters at helvetica 10

    def __init__(self, title: str):
        self.lines: list[tuple[int, str]] = []  # (font_size, text)
        self.title = title

    def heading(self, text: str) -> None:
        self.lines.append((14, text))

    def sub(self, text: str) -> None:
        self.lines.append((11, text))

    def text(self, text: str) -> None:
        for line in _wrap(text, self.WIDTH):
            self.lines.append((10, line))

    def blank(self) -> None:
        self.lines.append((10, ""))

    def build(self) -> bytes:
        pages: list[list[tuple[int, str]]] = []
        page: list[tuple[int, str]] = []
        y = self.TOP
        for size, line in self.lines:
            if y - self.LINE_H * (2 if size >= 14 else 1) < self.BOTTOM:
                pages.append(page)
                page = []
                y = self.TOP
            page.append((size, line))
            y -= self.LINE_H * (2 if size >= 14 else 1)
        pages.append(page)

        content_parts = []
        page_refs = []
        for page in pages:
            stream = ["BT"]
            y = self.TOP
            for size, line in page:
                stream.append(f"/F1 {size} Tf")
                stream.append(f"1 0 0 1 50 {y} Tm")
                stream.append(f"({_pdf_escape(line)}) Tj")
                y -= self.LINE_H * (2 if size >= 14 else 1)
            stream.append("ET")
            content = " ".join(stream)
            content_parts.append(content)
            page_refs.append(len(content))

        objects: list[str] = []
        # 1: catalog, 2: pages, then per page: page obj + content obj; fonts last
        n_pages = len(pages)
        font_obj_num = 3 + 2 * n_pages
        objects.append("<< /Type /Catalog /Pages 2 0 R >>")
        kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n_pages))
        objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>")
        for i, content in enumerate(content_parts):
            page_num = 3 + 2 * i
            objects.append(
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                f"/Resources << /Font << /F1 {font_obj_num} 0 R >> >> "
                f"/Contents {page_num + 1} 0 R >>"
            )
            objects.append(f"<< /Length {len(content)} >>\nstream\n{content}\nendstream")
        objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

        out = bytearray(b"%PDF-1.4\n")
        offsets = [0]
        for i, obj in enumerate(objects, start=1):
            offsets.append(len(out))
            out.extend(f"{i} 0 obj\n{obj}\nendobj\n".encode("latin-1"))
        xref_pos = len(out)
        out.extend(f"xref\n0 {len(objects) + 1}\n".encode())
        out.extend(b"0000000000 65535 f \n")
        for off in offsets[1:]:
            out.extend(f"{off:010d} 00000 n \n".encode())
        out.extend(
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF".encode()
        )
        return bytes(out)


# ---------------------------------------------------------------------------
# Report builders (real data only)
# ---------------------------------------------------------------------------


def _fmt_dt(dt: datetime | None) -> str:
    return dt.strftime("%Y-%m-%d %H:%M UTC") if dt else "-"


def inspection_report(db: Session, inspection_id: str) -> bytes:
    insp = db.get(Inspection, inspection_id)
    if insp is None:
        raise ValueError("inspection not found")
    mine = db.get(Mine, insp.mine_id)
    items = db.execute(
        select(InspectionChecklistItem)
        .where(InspectionChecklistItem.inspection_id == inspection_id)
        .order_by(InspectionChecklistItem.position)
    ).scalars().all()
    actions = db.execute(
        select(CorrectiveAction).where(CorrectiveAction.inspection_id == inspection_id)
    ).scalars().all()

    pdf = SimplePdf("Inspection Report")
    pdf.heading("MineGuardAI - Inspection Report")
    pdf.text(f"Generated: {_fmt_dt(datetime.now(timezone.utc))}")
    pdf.blank()
    pdf.sub("Inspection")
    pdf.text(f"ID: {insp.id}")
    pdf.text(f"Mine: {mine.name if mine else insp.mine_id}")
    pdf.text(f"Type: {insp.inspection_type}   Status: {insp.status}")
    pdf.text(f"Scheduled: {_fmt_dt(insp.scheduled_at)}   Completed: {_fmt_dt(insp.completed_at)}")
    pdf.text(f"Compliance result: {insp.compliance_result}")
    pdf.blank()
    pdf.sub("Checklist")
    if not items:
        pdf.text("No checklist items recorded.")
    for it in items:
        pdf.text(f"[{it.result or 'unanswered'}] {it.label}" + (f" - {it.comment}" if it.comment else ""))
    pdf.blank()
    pdf.sub("Corrective actions")
    if not actions:
        pdf.text("No corrective actions linked.")
    for a in actions:
        pdf.text(f"[{a.status}/{a.priority}] due {_fmt_dt(a.due_date)} - {a.description}")
    pdf.blank()
    pdf.text("Sign-off: unsigned (report generated by system; inspector sign-off recorded in audit log).")
    return pdf.build()


def mine_compliance_report(db: Session, mine_id: str) -> bytes:
    mine = db.get(Mine, mine_id)
    if mine is None:
        raise ValueError("mine not found")
    reqs = db.execute(select(ComplianceRequirement).where(ComplianceRequirement.is_active.is_(True))).scalars().all()
    reqs = [r for r in reqs if r.mine_id in (None, mine_id)]
    pdf = SimplePdf("Compliance Report")
    pdf.heading("MineGuardAI - Compliance Report")
    pdf.text(f"Mine: {mine.name} ({mine.code})")
    pdf.text(f"Generated: {_fmt_dt(datetime.now(timezone.utc))}")
    pdf.blank()
    pdf.sub("Configured requirements")
    if not reqs:
        pdf.text("No compliance requirements configured.")
    for r in reqs:
        latest = db.execute(
            select(ComplianceAssessment)
            .where(ComplianceAssessment.requirement_id == r.id)
            .order_by(ComplianceAssessment.period_end.desc()).limit(1)
        ).scalar_one_or_none()
        status = latest.status if latest else "not_assessed"
        pdf.text(f"[{status}] {r.title} (source: {r.reference}, {r.frequency})")
    return pdf.build()


def mine_safety_report(db: Session, mine_id: str) -> bytes:
    """Combined safety snapshot: inspections, incidents, emergencies, actions."""
    mine = db.get(Mine, mine_id)
    if mine is None:
        raise ValueError("mine not found")
    inspections = db.execute(
        select(Inspection).where(Inspection.mine_id == mine_id)
        .order_by(Inspection.scheduled_at.desc()).limit(20)
    ).scalars().all()
    incidents = db.execute(
        select(Incident).where(Incident.mine_id == mine_id)
        .order_by(Incident.occurred_at.desc()).limit(20)
    ).scalars().all()
    emergencies = db.execute(
        select(EmergencyEvent).where(EmergencyEvent.mine_id == mine_id)
        .order_by(EmergencyEvent.created_at.desc()).limit(20)
    ).scalars().all()

    pdf = SimplePdf("Mine Safety Report")
    pdf.heading("MineGuardAI - Mine Safety Report")
    pdf.text(f"Mine: {mine.name} ({mine.code})")
    pdf.text(f"Generated: {_fmt_dt(datetime.now(timezone.utc))}")
    pdf.blank()
    pdf.sub(f"Recent inspections ({len(inspections)})")
    for i in inspections:
        pdf.text(f"{_fmt_dt(i.scheduled_at)} [{i.status}] result: {i.compliance_result}")
    pdf.blank()
    pdf.sub(f"Recent incidents ({len(incidents)})")
    for i in incidents:
        pdf.text(f"{_fmt_dt(i.occurred_at)} [{i.severity}] {i.title} ({i.status})")
    pdf.blank()
    pdf.sub(f"Recent emergencies ({len(emergencies)})")
    for e in emergencies:
        pdf.text(f"{_fmt_dt(e.created_at)} [{e.severity}] {e.title} ({e.status})")
    return pdf.build()


def mine_violation_report(db: Session, mine_id: str) -> bytes:
    """Violations report: failed checklist items + open corrective actions."""
    mine = db.get(Mine, mine_id)
    if mine is None:
        raise ValueError("mine not found")
    failed_items = db.execute(
        select(InspectionChecklistItem)
        .join(Inspection, InspectionChecklistItem.inspection_id == Inspection.id)
        .where(Inspection.mine_id == mine_id, InspectionChecklistItem.result == "fail")
        .order_by(Inspection.scheduled_at.desc()).limit(100)
    ).scalars().all()
    insp_ids = {i.id for i in db.execute(select(Inspection).where(Inspection.mine_id == mine_id)).scalars().all()}
    incident_ids = {i.id for i in db.execute(select(Incident).where(Incident.mine_id == mine_id)).scalars().all()}
    actions = [
        a for a in db.execute(select(CorrectiveAction).order_by(CorrectiveAction.due_date.desc())).scalars().all()
        if (a.inspection_id and a.inspection_id in insp_ids) or (a.incident_id and a.incident_id in incident_ids)
    ]
    pdf = SimplePdf("Violation Report")
    pdf.heading("MineGuardAI - Violation Report")
    pdf.text(f"Mine: {mine.name} ({mine.code})   Generated: {_fmt_dt(datetime.now(timezone.utc))}")
    pdf.blank()
    pdf.sub(f"Failed checklist items ({len(failed_items)})")
    if not failed_items:
        pdf.text("No failed checklist items.")
    for it in failed_items:
        pdf.text(f"[{it.label}]" + (f" - {it.comment}" if it.comment else ""))
    pdf.blank()
    pdf.sub(f"Corrective actions ({len(actions)})")
    if not actions:
        pdf.text("No corrective actions.")
    for a in actions:
        pdf.text(f"[{a.status}/{a.priority}] due {_fmt_dt(a.due_date)} - {a.description}")
    return pdf.build()


def corrective_action_report(db: Session, mine_id: str | None = None) -> bytes:
    """Corrective actions ledger (optionally mine-scoped)."""
    pdf = SimplePdf("Corrective Action Report")
    pdf.heading("MineGuardAI - Corrective Action Report")
    pdf.text(f"Generated: {_fmt_dt(datetime.now(timezone.utc))}")
    if mine_id:
        mine = db.get(Mine, mine_id)
        if mine is None:
            raise ValueError("mine not found")
        pdf.text(f"Mine: {mine.name} ({mine.code})")
    insp_ids = {i.id: i for i in db.execute(select(Inspection)).scalars().all()}
    inc_ids = {i.id: i for i in db.execute(select(Incident)).scalars().all()}
    actions = db.execute(select(CorrectiveAction).order_by(CorrectiveAction.due_date.desc()).limit(200)).scalars().all()
    if mine_id:
        actions = [a for a in actions
                   if (a.inspection_id and insp_ids.get(a.inspection_id, None) is not None
                       and insp_ids[a.inspection_id].mine_id == mine_id)
                   or (a.incident_id and inc_ids.get(a.incident_id, None) is not None
                       and inc_ids[a.incident_id].mine_id == mine_id)]
    pdf.blank()
    pdf.sub(f"Corrective actions ({len(actions)})")
    if not actions:
        pdf.text("No corrective actions.")
    for a in actions:
        assignee = "-"
        if a.assigned_to_id:
            u = db.get(User, a.assigned_to_id)
            assignee = u.full_name if u else a.assigned_to_id
        pdf.text(f"[{a.status}/{a.priority}] due {_fmt_dt(a.due_date)} | {assignee} | {a.description}")
    return pdf.build()


def emergency_report(db: Session, mine_id: str | None = None) -> bytes:
    """Emergency events ledger (optionally mine-scoped)."""
    pdf = SimplePdf("Emergency Report")
    pdf.heading("MineGuardAI - Emergency Report")
    pdf.text(f"Generated: {_fmt_dt(datetime.now(timezone.utc))}")
    stmt = select(EmergencyEvent).order_by(EmergencyEvent.created_at.desc()).limit(200)
    events = db.execute(stmt).scalars().all()
    if mine_id:
        mine = db.get(Mine, mine_id)
        if mine is None:
            raise ValueError("mine not found")
        pdf.text(f"Mine: {mine.name} ({mine.code})")
        events = [e for e in events if e.mine_id == mine_id]
    pdf.blank()
    pdf.sub(f"Emergency events ({len(events)})")
    if not events:
        pdf.text("No emergency events recorded.")
    for e in events:
        pdf.text(f"{_fmt_dt(e.created_at)} [{e.severity}/{e.status}] {e.emergency_type} - {e.title}")
    return pdf.build()


def contractor_compliance_report(db: Session) -> bytes:
    """Contractors, documents, expiry status and compliance roll-up."""
    pdf = SimplePdf("Contractor Compliance Report")
    pdf.heading("MineGuardAI - Contractor Compliance Report")
    pdf.text(f"Generated: {_fmt_dt(datetime.now(timezone.utc))}")
    contractors = db.execute(select(Contractor).where(Contractor.is_active.is_(True))).scalars().all()
    pdf.blank()
    pdf.sub(f"Contractors ({len(contractors)})")
    if not contractors:
        pdf.text("No contractors registered.")
    for c in contractors:
        docs = db.execute(
            select(ContractorDocument).where(ContractorDocument.contractor_id == c.id)
        ).scalars().all()
        pdf.blank()
        pdf.sub(c.name)
        if not docs:
            pdf.text("  No documents on record.")
        for d in docs:
            worker = db.get(Worker, d.worker_id) if d.worker_id else None
            whom = f" worker:{worker.full_name}" if worker else ""
            pdf.text(f"  [{d.verification_status}] {d.doc_type} - {d.title} expires {_fmt_dt(d.expires_on)}{whom}")
    return pdf.build()


def audit_report(db: Session, limit: int = 300) -> bytes:
    """Audit ledger export with hash-chain head (admin-only endpoint serves it)."""
    from app.services.governance import audit_chain

    verification = audit_chain.verify_chain(db)
    events = db.execute(select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(limit)).scalars().all()
    pdf = SimplePdf("Audit Report")
    pdf.heading("MineGuardAI - Tamper-Evident Audit Log (hash chain)")
    pdf.text(f"Generated: {_fmt_dt(datetime.now(timezone.utc))}")
    pdf.text(f"Chain verification: {'VALID' if verification.get('valid') else 'BROKEN at seq ' + str(verification.get("broken_at_seq"))}")
    pdf.text(f"Entries exported (newest first, max {limit}): {len(events)}")
    pdf.blank()
    for e in events:
        _m = f" mine:{e.mine_id}" if e.mine_id else ""
        pdf.text(f"#{e.seq} {_fmt_dt(e.created_at)} [{e.actor_role}] {e.action} {e.entity_type} {_m}")
        pdf.text(f"    hash: {e.event_hash[:24]}…")
    return pdf.build()


def workforce_report(db: Session, mine_id: str | None = None) -> bytes:
    """Workforce report: workers, shifts, recent attendance (real rows only)."""
    pdf = SimplePdf("Workforce Report")
    pdf.heading("MineGuardAI - Workforce Report")
    pdf.text(f"Generated: {_fmt_dt(datetime.now(timezone.utc))}")
    if mine_id:
        mine = db.get(Mine, mine_id)
        if mine is None:
            raise ValueError("mine not found")
        pdf.text(f"Mine: {mine.name} ({mine.code})")
    stmt = select(Worker).where(Worker.is_active.is_(True))
    workers = db.execute(stmt).scalars().all()
    if mine_id:
        workers = [w for w in workers if w.mine_id == mine_id]
    pdf.blank()
    pdf.sub(f"Active workers ({len(workers)})")
    if not workers:
        pdf.text("No worker records.")
    for w in workers:
        contractor = db.get(Contractor, w.contractor_id) if w.contractor_id else None
        c = f" ({contractor.name})" if contractor else ""
        pdf.text(f"{w.employee_code} {w.full_name}{c}")
    shifts = db.execute(select(Shift).order_by(Shift.starts_at.desc()).limit(20)).scalars().all()
    if mine_id:
        shifts = [s for s in shifts if s.mine_id == mine_id]
    pdf.blank()
    pdf.sub(f"Recent shifts ({len(shifts)})")
    for s in shifts:
        pdf.text(f"{s.name} {_fmt_dt(s.starts_at)} -> {_fmt_dt(s.ends_at)}")
    att = db.execute(select(Attendance).order_by(Attendance.created_at.desc()).limit(50)).scalars().all()
    if mine_id:
        att = [a for a in att if a.mine_id == mine_id]
    pdf.blank()
    pdf.sub(f"Recent attendance ({len(att)})")
    for a in att:
        worker = db.get(Worker, a.worker_id)
        who = worker.full_name if worker else a.worker_id
        pdf.text(f"{who}: in {_fmt_dt(a.check_in_at)} out {_fmt_dt(a.check_out_at)} ({a.verification})")
    return pdf.build()


def telemetry_report(db: Session, mine_id: str) -> bytes:
    """Environmental telemetry report: devices + recent readings (real data only)."""
    mine = db.get(Mine, mine_id)
    if mine is None:
        raise ValueError("mine not found")
    devices = db.execute(select(SensorDevice).where(SensorDevice.mine_id == mine_id)).scalars().all()
    recent = db.execute(
        select(TelemetryReading).where(TelemetryReading.mine_id == mine_id)
        .order_by(TelemetryReading.recorded_at.desc()).limit(50)
    ).scalars().all()
    looking_dev = {d.id: d for d in devices}
    pdf = SimplePdf("Telemetry Report")
    pdf.heading("MineGuardAI - Environmental Telemetry Report")
    pdf.text(f"Mine: {mine.name} ({mine.code})   Generated: {_fmt_dt(datetime.now(timezone.utc))}")
    pdf.blank()
    pdf.sub(f"Sensor devices ({len(devices)})")
    if not devices:
        pdf.text("No sensor devices registered.")
    for d in devices:
        src = " (DEMO — labelled simulated device)" if d.source == "demo" else ""
        pdf.text(f"{d.device_code} {d.parameter} [{d.unit}] src={d.source}{src}")
    pdf.blank()
    pdf.sub(f"Recent readings ({len(recent)})")
    if not recent:
        pdf.text("No telemetry readings recorded.")
    for r in recent:
        d = looking_dev.get(r.device_id)
        code = d.device_code if d else r.device_id
        pdf.text(f"{_fmt_dt(r.recorded_at)} {code}: {r.value}{r.unit} [{r.status}]")
    return pdf.build()
