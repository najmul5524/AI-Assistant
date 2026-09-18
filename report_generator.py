import re
import datetime
from pathlib import Path
from typing import List, Any, Optional

from fpdf import FPDF

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from config import REPORTS_DIR, BOT_NAME, BASE_DIR

_font_path = BASE_DIR / "fonts" / "kalpurush.ttf"
HAS_KALPURUSH = _font_path.exists()

def _has_bengali(text: str) -> bool:
    """Returns True if string contains Bengali Unicode characters."""
    return any('\u0980' <= c <= '\u09ff' for c in text)

class ExecutivePDF(FPDF):
    """Modern executive PDF document with header, footer, and Bengali HarfBuzz shaping."""
    def __init__(self, doc_title: str):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.doc_title = doc_title
        
    def header(self):
        if "Kalpurush" in self.fonts:
            self.set_font("Kalpurush", "", 8)
            self.set_text_color(148, 163, 184)
            self.cell(0, 7, f"{BOT_NAME} 24/7 AI • Confidential Executive Report", align="R")
            self.ln(9)
            
    def footer(self):
        self.set_y(-15)
        if "Kalpurush" in self.fonts:
            self.set_font("Kalpurush", "", 8)
            self.set_text_color(148, 163, 184)
            self.cell(0, 10, f"পৃষ্ঠা {self.page_no()}", align="C")

def generate_pdf_report(title: str, text_content: str, filename_prefix: str = "report") -> Path:
    """
    Generates an executive-quality PDF report using FPDF2 and uharfbuzz.
    Supports English and Bengali seamlessly with full OpenType text shaping (ligatures, conjuncts, vowels).
    Returns the Path to the generated PDF.
    """
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    sanitized_prefix = re.sub(r'[^\w\-]', '_', filename_prefix)[:20]
    file_path = REPORTS_DIR / f"{sanitized_prefix}_{timestamp}.pdf"

    pdf = ExecutivePDF(doc_title=title)
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(left=20, top=18, right=20)
    
    font_path = BASE_DIR / "fonts" / "kalpurush.ttf"
    if font_path.exists():
        pdf.add_font("Kalpurush", "", str(font_path))
        pdf.add_font("Kalpurush", "B", str(font_path))
        pdf.add_font("Kalpurush", "I", str(font_path))
        pdf.add_font("Kalpurush", "BI", str(font_path))
        try:
            pdf.set_text_shaping(True)
        except Exception as e:
            print(f"Warning: Text shaping could not be enabled: {e}")
        main_font = "Kalpurush"
    else:
        main_font = "Helvetica"

    pdf.add_page()
    
    # 1. Title Block
    pdf.set_font(main_font, "B", 17)
    pdf.set_text_color(15, 23, 42)
    pdf.multi_cell(0, 9, title)
    pdf.ln(2)
    
    # 2. Metadata bar
    now_str = datetime.datetime.now().strftime("%d %B, %Y | %I:%M %p")
    pdf.set_font(main_font, "", 9)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(0, 5, f"জেনারেটেড বাই: {BOT_NAME} AI | সময়: {now_str}")
    pdf.ln(7)
    
    # 3. Accent divider
    pdf.set_draw_color(59, 130, 246)
    pdf.set_line_width(0.7)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(6)
    
    # 4. Content Parsing (Headings, Bullets, Paragraphs)
    lines = text_content.split("\n")
    for line in lines:
        raw = line.strip()
        if not raw:
            pdf.ln(3)
            continue
            
        if raw.startswith("### "):
            head_txt = raw[4:].strip()
            pdf.ln(2)
            pdf.set_font(main_font, "B", 12)
            pdf.set_text_color(30, 41, 59)
            pdf.multi_cell(0, 7, head_txt)
            pdf.ln(2)
        elif raw.startswith("## "):
            head_txt = raw[3:].strip()
            pdf.ln(3)
            pdf.set_font(main_font, "B", 14)
            pdf.set_text_color(15, 23, 42)
            pdf.multi_cell(0, 8, head_txt)
            pdf.ln(2)
        elif raw.startswith("# "):
            head_txt = raw[2:].strip()
            pdf.ln(4)
            pdf.set_font(main_font, "B", 15)
            pdf.set_text_color(15, 23, 42)
            pdf.multi_cell(0, 9, head_txt)
            pdf.ln(2)
        elif raw.startswith("- ") or raw.startswith("* ") or raw.startswith("• "):
            bullet_body = raw[2:].strip()
            orig_lm = pdf.l_margin
            y = pdf.get_y()
            pdf.set_fill_color(59, 130, 246)
            pdf.circle(orig_lm + 1.5, y + 3.2, 0.9, style="F")
            
            pdf.set_left_margin(orig_lm + 6)
            pdf.set_x(orig_lm + 6)
            pdf.set_font(main_font, "", 10.5)
            pdf.set_text_color(51, 65, 85)
            
            html_bullet = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', bullet_body)
            try:
                pdf.write_html(f"<p>{html_bullet}</p>")
            except Exception:
                pdf.multi_cell(0, 6.5, bullet_body)
            pdf.set_left_margin(orig_lm)
            pdf.ln(1)
        else:
            pdf.set_font(main_font, "", 10.5)
            pdf.set_text_color(51, 65, 85)
            html_p = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', raw)
            try:
                pdf.write_html(f"<p>{html_p}</p>")
            except Exception:
                pdf.multi_cell(0, 6.5, raw)
            pdf.ln(1.5)
            
    # 5. Bottom divider & footer notice
    pdf.ln(6)
    pdf.set_draw_color(226, 232, 240)
    pdf.set_line_width(0.4)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(4)
    pdf.set_font(main_font, "I", 8.5)
    pdf.set_text_color(148, 163, 184)
    pdf.cell(0, 5, f"গোপনীয় ও নির্ভরযোগ্য তথ্যসমৃদ্ধ — প্রস্তুত করেছে {BOT_NAME} পার্সোনাল এআই।")
    
    pdf.output(str(file_path))
    return file_path

def generate_excel_report(title: str, headers: List[str], data_rows: List[List[Any]], filename_prefix: str = "report") -> Path:
    """
    Generates a beautifully formatted Excel report using OpenPyXL.
    Returns the Path to the generated .xlsx file.
    """
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    sanitized_prefix = re.sub(r'[^\w\-]', '_', filename_prefix)[:20]
    file_path = REPORTS_DIR / f"{sanitized_prefix}_{timestamp}.xlsx"

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Summary Report"

    # Title Block
    ws.merge_cells("A1:E1")
    title_cell = ws["A1"]
    title_cell.value = f"{title} - {BOT_NAME} Report"
    title_cell.font = Font(name="Calibri", size=15, bold=True, color="FFFFFF")
    title_cell.fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
    title_cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[1].height = 32

    # Date Block
    ws.merge_cells("A2:E2")
    date_cell = ws["A2"]
    date_cell.value = f"Exported: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    date_cell.font = Font(name="Calibri", size=9, italic=True, color="64748B")
    date_cell.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[2].height = 18

    # Headers Block (Row 4)
    header_fill = PatternFill(start_color="2563EB", end_color="2563EB", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    thin_border = Border(
        left=Side(style='thin', color='E2E8F0'),
        right=Side(style='thin', color='E2E8F0'),
        top=Side(style='thin', color='E2E8F0'),
        bottom=Side(style='thin', color='CBD5E1')
    )

    for col_num, header in enumerate(headers, 1):
        cell = ws.cell(row=4, column=col_num)
        cell.value = str(header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border
    ws.row_dimensions[4].height = 24

    # Data Rows
    row_alt_fill = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    for r_idx, row_data in enumerate(data_rows, 5):
        is_even = (r_idx % 2 == 0)
        for c_idx, val in enumerate(row_data, 1):
            cell = ws.cell(row=r_idx, column=c_idx)
            cell.value = val
            cell.font = Font(name="Calibri", size=10)
            cell.border = thin_border
            if is_even:
                cell.fill = row_alt_fill
            cell.alignment = Alignment(horizontal="left", vertical="center")
        ws.row_dimensions[r_idx].height = 20

    # Auto-adjust column widths
    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

    wb.save(str(file_path))
    return file_path
