"""PDF fleet reports rendered with ReportLab and stored in object storage."""

from __future__ import annotations

import hashlib
import io
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, UpstreamError
from app.core.logging import get_logger
from app.integrations.storage import ObjectStorage, get_storage
from app.models.enums import AlertStatus, ComplianceFramework, ReportKind, ReportStatus
from app.models.identity import Tenant
from app.models.operations import Report
from app.repositories import UnitOfWork
from app.schemas.operations import ReportCreate
from app.services.audit import AuditService
from app.services.monitoring import DashboardService, MetricQueryService

log = get_logger("ofme.reports")

#: DejaVu is installed in the API image (``fonts-dejavu-core``); the fallback
#: keeps unit tests working on a workstation without it.
_FONT_CANDIDATES = (
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "DejaVuSans"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "DejaVuSans-Bold"),
)

_FONTS_READY = False


def _register_fonts() -> str:
    """Register a Unicode font and return the body font name."""
    global _FONTS_READY
    if not _FONTS_READY:
        for path, name in _FONT_CANDIDATES:
            if Path(path).exists():
                pdfmetrics.registerFont(TTFont(name, path))
        _FONTS_READY = True
    if "DejaVuSans" in pdfmetrics.getRegisteredFontNames():
        return "DejaVuSans"
    return "Helvetica"


def _styles() -> dict[str, ParagraphStyle]:
    font = _register_fonts()
    bold = "DejaVuSans-Bold" if font == "DejaVuSans" else "Helvetica-Bold"
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "OfmeTitle", parent=base["Title"], fontName=bold, fontSize=20, leading=24, spaceAfter=4
        ),
        "subtitle": ParagraphStyle(
            "OfmeSubtitle", parent=base["Normal"], fontName=font, fontSize=9, textColor=colors.grey
        ),
        "heading": ParagraphStyle(
            "OfmeHeading",
            parent=base["Heading2"],
            fontName=bold,
            fontSize=12,
            leading=16,
            spaceBefore=10,
            spaceAfter=4,
        ),
        "body": ParagraphStyle("OfmeBody", parent=base["Normal"], fontName=font, fontSize=8.5, leading=11),
        "cell": ParagraphStyle("OfmeCell", parent=base["Normal"], fontName=font, fontSize=7.5, leading=9),
        "cell_bold": ParagraphStyle(
            "OfmeCellBold", parent=base["Normal"], fontName=bold, fontSize=7.5, leading=9
        ),
    }


def _table(rows: list[list[Any]], styles: dict[str, ParagraphStyle], widths: list[float]) -> Table:
    wrapped = [
        [cell if isinstance(cell, Paragraph) else Paragraph(str(cell), styles["cell"]) for cell in row]
        for row in rows
    ]
    table = Table(wrapped, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2f7")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


class ReportService:
    def __init__(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        actor_id: uuid.UUID | None = None,
        storage: ObjectStorage | None = None,
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.actor_id = actor_id
        self.uow = UnitOfWork(session, tenant_id)
        self.storage = storage or get_storage()
        self.audit = AuditService(session)

    # ------------------------------------------------------------------ queries
    async def list(self) -> list[Report]:
        return await self.uow.reports.recent()

    async def get(self, report_id: uuid.UUID) -> Report:
        return await self.uow.reports.get_or_404(report_id)

    async def download(self, report_id: uuid.UUID) -> tuple[Report, bytes]:
        report = await self.get(report_id)
        if report.status != ReportStatus.READY or not report.storage_key:
            raise BadRequestError("Report is not ready for download")
        data = await self.storage.aget_bytes(
            report.storage_key, bucket=self.storage.buckets["artifacts"]
        )
        return report, data

    async def delete(self, report_id: uuid.UUID) -> None:
        report = await self.get(report_id)
        if report.storage_key:
            try:
                self.storage.delete(report.storage_key, bucket=self.storage.buckets["artifacts"])
            except UpstreamError:
                log.warning("report.object_delete_failed", key=report.storage_key)
        await self.session.delete(report)
        await self.audit.record(
            action="report.deleted",
            resource_type="Report",
            resource_id=report_id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            before={"name": report.name, "kind": report.kind.value},
        )
        await self.session.commit()

    # ------------------------------------------------------------------ generate
    async def create(self, payload: ReportCreate, *, generate_now: bool = False) -> Report:
        now = datetime.now(UTC)
        period_start = now - timedelta(days=payload.period_days)
        name = payload.name or f"{payload.kind.value.title()} report {now:%Y-%m-%d %H:%M}"
        report = Report(
            tenant_id=self.tenant_id,
            name=name,
            kind=payload.kind,
            status=ReportStatus.PENDING,
            period_start=period_start,
            period_end=now,
            params={**payload.params, "period_days": payload.period_days},
            created_by=self.actor_id,
        )
        self.session.add(report)
        await self.session.flush()
        await self.audit.record(
            action="report.requested",
            resource_type="Report",
            resource_id=report.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={"name": name, "kind": payload.kind.value},
        )
        await self.session.commit()
        if generate_now:
            await self.generate(report)
        return report

    async def generate(self, report: Report) -> Report:
        """Render the PDF for ``report`` and persist it in object storage."""
        report.status = ReportStatus.GENERATING
        report.error = None
        await self.session.commit()
        try:
            data = await self.render(report)
        except Exception as exc:  # noqa: BLE001 - the failure is recorded on the row
            report.status = ReportStatus.FAILED
            report.error = str(exc)[:2000]
            await self.session.commit()
            log.error("report.generate_failed", report=str(report.id), error=str(exc))
            raise

        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        key = f"{self.tenant_id}/reports/{stamp}-{report.id}.pdf"
        stored = await self.storage.aput_bytes(
            key,
            data,
            bucket=self.storage.buckets["artifacts"],
            content_type="application/pdf",
            metadata={"report_id": str(report.id), "kind": report.kind.value},
        )
        report.storage_key = stored.key
        report.size_bytes = stored.size
        report.checksum_sha256 = stored.checksum_sha256
        report.status = ReportStatus.READY
        report.error = None
        report.generated_at = datetime.now(UTC)
        await self.session.flush()
        await self.audit.record(
            action="report.generated",
            resource_type="Report",
            resource_id=report.id,
            tenant_id=self.tenant_id,
            user_id=self.actor_id,
            after={
                "name": report.name,
                "kind": report.kind.value,
                "size_bytes": report.size_bytes,
                "checksum_sha256": report.checksum_sha256,
            },
        )
        await self.session.commit()
        return report

    async def render(self, report: Report) -> bytes:
        styles = _styles()
        tenant = await self.session.get(Tenant, self.tenant_id)
        dashboard = DashboardService(self.session, self.tenant_id)
        summary = await dashboard.summary()
        health = await dashboard.health(limit=100)
        alerts = await self.uow.alerts.open_alerts(limit=50)
        compliance = await self._compliance_rows()
        traffic = await self._traffic_rows()

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=16 * mm,
            rightMargin=16 * mm,
            topMargin=16 * mm,
            bottomMargin=16 * mm,
            title=report.name,
            author="OFME",
        )
        story: list[Any] = []
        story.append(Paragraph("OFME Fleet Report", styles["title"]))
        story.append(
            Paragraph(
                f"{report.name} &nbsp;·&nbsp; tenant {tenant.name if tenant else self.tenant_id}"
                f" &nbsp;·&nbsp; {report.period_start:%Y-%m-%d %H:%M} – {report.period_end:%Y-%m-%d %H:%M} UTC",
                styles["subtitle"],
            )
        )
        story.append(Spacer(1, 6))

        story.append(Paragraph("Executive summary", styles["heading"]))
        executive = [
            ["Metric", "Value"],
            ["Devices online", f"{summary['devices_online']} / {summary['devices_total']}"],
            ["Devices offline / error", f"{summary['devices_offline']} / {summary['devices_error']}"],
            ["Open alerts", str(summary["open_alerts"])],
            ["Critical alerts", str(summary["critical_alerts"])],
            ["Compliance score", "n/a" if summary["compliance_score"] is None else f"{summary['compliance_score']:.1f}%"],
            ["Policies drifted", str(summary["policies_drifted"])],
            ["SD-WAN tunnels up", f"{summary['tunnels_up']} / {summary['tunnels_total']}"],
            ["Jobs running", str(summary["jobs_running"])],
        ]
        story.append(_table(executive, styles, [70 * mm, 105 * mm]))

        story.append(Paragraph("Device health", styles["heading"]))
        device_rows: list[list[Any]] = [
            ["Device", "Status", "CPU", "Memory", "Disk", "Last sample"]
        ]
        for device in health:
            device_rows.append(
                [
                    device["name"],
                    device["status"],
                    _pct(device["cpu_pct"]),
                    _pct(device["memory_pct"]),
                    _pct(device["disk_pct"]),
                    _dt(device["recorded_at"]),
                ]
            )
        if len(device_rows) == 1:
            device_rows.append(["No devices", "—", "—", "—", "—", "—"])
        story.append(_table(device_rows, styles, [52 * mm, 24 * mm, 18 * mm, 22 * mm, 18 * mm, 41 * mm]))

        story.append(Paragraph("Open alerts", styles["heading"]))
        alert_rows: list[list[Any]] = [["Severity", "Alert", "Status", "Started"]]
        for alert in alerts:
            alert_rows.append(
                [
                    alert.severity.value,
                    alert.title,
                    alert.status.value,
                    _dt(alert.starts_at),
                ]
            )
        if len(alert_rows) == 1:
            alert_rows.append(["—", "No open alerts", "—", "—"])
        story.append(_table(alert_rows, styles, [20 * mm, 95 * mm, 25 * mm, 35 * mm]))

        if compliance:
            story.append(Paragraph("Compliance", styles["heading"]))
            compliance_rows: list[list[Any]] = [["Framework", "Score", "Passed / total", "Generated"]]
            for row in compliance:
                compliance_rows.append(
                    [
                        row.framework.value,
                        f"{row.score:.1f}%",
                        f"{row.controls_passed} / {row.controls_total}",
                        _dt(row.generated_at),
                    ]
                )
            story.append(_table(compliance_rows, styles, [30 * mm, 25 * mm, 40 * mm, 80 * mm]))

        if traffic:
            story.append(Paragraph("WAN throughput (latest per device)", styles["heading"]))
            traffic_rows: list[list[Any]] = [["Device", "Interface", "Received", "Transmitted"]]
            for row in traffic:
                traffic_rows.append(
                    [
                        row["name"],
                        row["interface_name"],
                        _bps(row["in_bps"]),
                        _bps(row["out_bps"]),
                    ]
                )
            story.append(_table(traffic_rows, styles, [65 * mm, 40 * mm, 35 * mm, 35 * mm]))

        story.append(Spacer(1, 10))
        story.append(
            Paragraph(
                f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M:%S} UTC by OFME. "
                "Figures are point-in-time snapshots; see the dashboard for live values.",
                styles["subtitle"],
            )
        )
        doc.build(story)
        return buffer.getvalue()

    async def _compliance_rows(self) -> list[Any]:
        rows: list[Any] = []
        for framework in ComplianceFramework:
            latest = await self.uow.compliance.latest(framework.value, limit=1)
            if latest:
                rows.append(latest[0])
        return rows

    async def _traffic_rows(self) -> list[dict[str, Any]]:
        data = await MetricQueryService(self.session, self.tenant_id).fleet_traffic(
            "wan", hours=24
        )
        return list(data["devices"])[:20]


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}%"


def _dt(value: datetime | None) -> str:
    return "—" if value is None else value.strftime("%Y-%m-%d %H:%M")


def _bps(value: float | None) -> str:
    if value is None:
        return "—"
    units = ["bps", "Kbps", "Mbps", "Gbps"]
    number = float(value)
    index = 0
    while number >= 1000 and index < len(units) - 1:
        number /= 1000
        index += 1
    return f"{number:.1f} {units[index]}"


def report_checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
