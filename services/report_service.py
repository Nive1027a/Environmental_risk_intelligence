# services/report_service.py
import io
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


class ReportService:
    @staticmethod
    def generate_pdf_report(payload: dict) -> io.BytesIO:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36,
                                topMargin=36, bottomMargin=36)
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle('ReportTitle', parent=styles['Heading1'], fontSize=18, leading=22,
                                     textColor=colors.HexColor('#0f172a'), spaceAfter=2)
        subtitle_style = ParagraphStyle('ReportSubtitle', parent=styles['Normal'], fontSize=10, leading=13,
                                        textColor=colors.HexColor('#64748b'), spaceAfter=14)
        section_heading = ParagraphStyle('SectionHeading', parent=styles['Heading2'], fontSize=12, leading=15,
                                         textColor=colors.HexColor('#0f172a'), spaceBefore=10, spaceAfter=6)
        cell_label = ParagraphStyle('CellLabel', parent=styles['Normal'], fontSize=9, leading=11,
                                    textColor=colors.HexColor('#334155'), fontName='Helvetica-Bold')
        cell_val = ParagraphStyle('CellVal', parent=styles['Normal'], fontSize=9, leading=11,
                                  textColor=colors.HexColor('#0f172a'))
        table_hdr = ParagraphStyle('TableHdr', parent=styles['Normal'], fontSize=9, leading=11,
                                   textColor=colors.HexColor('#1e293b'), fontName='Helvetica-Bold')
        body = ParagraphStyle('Body', parent=styles['Normal'], fontSize=9, leading=13,
                              textColor=colors.HexColor('#1e293b'))
        grid = [('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
                ('PADDING', (0, 0), (-1, -1), 5), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]

        location = payload.get('location', {})
        prediction = payload.get('prediction', {})
        risk = payload.get('risk', {})
        forecast = payload.get('forecast') or {}

        zone_name = str(location.get('name', 'N/A'))
        risk_score = f"{risk.get('risk_score', '-')}/100"
        risk_level = str(risk.get('risk_level', 'UNKNOWN')).upper()

        el = [Paragraph("Environmental Risk Intelligence Report", title_style),
              Paragraph("Air Quality Spatial Twin AI Engine — Automated Audit", subtitle_style),
              Paragraph("1. Location & Exposure Summary", section_heading)]

        rows = [
            ("Station / Zone Node:", zone_name),
            ("Coordinates:", f"{location.get('lat', '-')}, {location.get('lon', '-')}"),
            ("Predicted NO₂:", f"{prediction.get('no2', '-')} µg/m³"),
            ("Predicted PM2.5:", f"{prediction.get('pm25', '-')} µg/m³"),
            ("Overall Risk Score:", f"<b>{risk_score}</b>"),
            ("Risk Category:", f"<b>{risk_level}</b>"),
        ]
        t = Table([[Paragraph(a, cell_label), Paragraph(b, cell_val)] for a, b in rows], colWidths=[180, 360])
        t.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8fafc'))] + grid))
        el += [t, Spacer(1, 12), Paragraph("2. Risk Contributors Analysis", section_heading)]

        data = [[Paragraph("Factor Name", table_hdr), Paragraph("Contribution Weight", table_hdr)]]
        contributors = risk.get('contributors', [])
        if isinstance(contributors, list) and contributors:
            for item in contributors:
                if isinstance(item, dict):
                    data.append([Paragraph(str(item.get('factor', 'Unknown')), cell_val),
                                 Paragraph(f"{item.get('contribution', 0)}%", cell_val)])
        else:
            data.append([Paragraph("No primary contributors flagged", cell_val), Paragraph("-", cell_val)])
        ct = Table(data, colWidths=[340, 200])
        ct.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9'))] + grid))
        el += [ct, Spacer(1, 12), Paragraph("3. AI Automated Policy Advisory", section_heading)]

        try:
            score = float(risk.get('risk_score', 0))
        except (ValueError, TypeError):
            score = 0.0
        # thresholds aligned with the dashboard (High >= 70, Critical >= 85)
        if score >= 85:
            adv = "<b>CRITICAL ACTION:</b> Immediate traffic flow restrictions and temporary suspension of heavy industrial activity recommended."
        elif score >= 70:
            adv = "<b>WARNING:</b> Elevated pollutant levels. Issue public sensitivity alerts and restrict heavy vehicular movement during peak hours."
        else:
            adv = "<b>NOMINAL:</b> Environmental risks within manageable thresholds. Continue routine baseline monitoring."
        el.append(Paragraph(adv, body))

        # NEW section: ML forecast outlook
        if forecast:
            el.append(Paragraph("4. ML 24-Hour Forecast Outlook", section_heading))
            frows = [
                ("Forecast model:", f"{forecast.get('model', '-')} (held-out MAE {forecast.get('mae', '-')} µg/m³)"),
                ("Peak forecast risk:", f"{forecast.get('peak_risk', '-')}/100 ({forecast.get('peak_level', '-')})"),
                ("Peak time:", str(forecast.get('peak_time', '-')).replace('T', ' ')),
                ("Hours at HIGH/CRITICAL:", str(forecast.get('hours_high', '-'))),
                ("Mean forecast PM2.5:", f"{forecast.get('avg_pm25', '-')} µg/m³"),
            ]
            ft = Table([[Paragraph(a, cell_label), Paragraph(b, cell_val)] for a, b in frows], colWidths=[180, 360])
            ft.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8fafc'))] + grid))
            el.append(ft)
            el.append(Spacer(1, 6))
            el.append(Paragraph("<i>Forecast is city-level (Delhi centre) and based on real Open-Meteo/CAMS data.</i>", body))

        doc.build(el)
        buffer.seek(0)
        return buffer
