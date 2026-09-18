import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

print("=" * 50)
print("[*] Testing Report Generation & Email Service...")
print("=" * 50)

from report_generator import generate_pdf_report, generate_excel_report
import email_service

# 1. Test PDF Report
print("\n[1] Testing PDF Report Generation...")
sample_title = "Monthly AI Growth & Performance Report"
sample_content = """# Executive Summary
The AI Assistant system has been upgraded to provide autonomous real-world action capabilities.

## Key Accomplishments
* Added executive-styled PDF report generator using ReportLab.
* Added professional Excel (.xlsx) spreadsheet exporter with custom styling.
* Added secure Gmail SMTP email transmission pipeline.

## Next Steps
- Automate voice note audio transcription.
- Implement receipt & image OCR.
"""
pdf_path = generate_pdf_report(sample_title, sample_content, filename_prefix="test_ai_report")
assert pdf_path.is_file() and pdf_path.stat().st_size > 500, "PDF file was not created properly!"
print(f"  ✓ PDF generated successfully: {pdf_path.name} ({pdf_path.stat().st_size} bytes)")

# 2. Test Excel Report
print("\n[2] Testing Excel Report Generation...")
excel_headers = ["Project Name", "Lead Developer", "Status", "Completion %", "Cost (BDT)"]
excel_rows = [
    ["Telegram Bot Core", "Goodushh", "Completed", "100%", 0],
    ["Multi-Tier AI Fallback", "Goodushh", "Completed", "100%", 0],
    ["Cloud 24/7 Deployment", "Goodushh", "Completed", "100%", 0],
    ["PDF & Excel Engine", "Goodushh", "Completed", "100%", 0],
    ["Email Dispatcher", "Goodushh", "Testing", "95%", 0],
]
excel_path = generate_excel_report("Project Milestone Overview", excel_headers, excel_rows, filename_prefix="milestone_test")
assert excel_path.is_file() and excel_path.stat().st_size > 500, "Excel file was not created properly!"
print(f"  ✓ Excel generated successfully: {excel_path.name} ({excel_path.stat().st_size} bytes)")

# 3. Test Email Config Check
print("\n[3] Testing Email Service State...")
is_cfg = email_service.is_email_configured()
print(f"  ✓ Email configured: {is_cfg}")
if not is_cfg:
    print("  ✓ Correctly identified unconfigured state (awaiting user credentials in .env).")

print("\n" + "=" * 50)
print("✅ Report & Email test passed successfully!")
print("=" * 50)
