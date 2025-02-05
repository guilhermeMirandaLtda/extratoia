import pdfplumber
import pandas as pd
import tempfile
import fitz  # PyMuPDF
from pdfminer.high_level import extract_text

def extract_text_pdfplumber(uploaded_pdf):
    """Extrai o texto completo de um PDF usando pdfplumber."""
    texto_completo = ""

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
        temp_pdf.write(uploaded_pdf.read())
        temp_pdf_path = temp_pdf.name

    with pdfplumber.open(temp_pdf_path) as pdf:
        for page in pdf.pages:
            texto_completo += page.extract_text() + "\n"

    return texto_completo.strip()

def extract_text_pymupdf(uploaded_pdf):
    """Extrai o texto completo de um PDF usando PyMuPDF (fitz)."""
    texto_completo = ""

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
        temp_pdf.write(uploaded_pdf.read())
        temp_pdf_path = temp_pdf.name

    with fitz.open(temp_pdf_path) as doc:
        for page in doc:
            texto_completo += page.get_text("text") + "\n"

    return texto_completo.strip()

def extract_text_pdfminer(uploaded_pdf):
    """Extrai o texto completo de um PDF usando PDFMiner."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
        temp_pdf.write(uploaded_pdf.read())
        temp_pdf_path = temp_pdf.name

    return extract_text(temp_pdf_path).strip()

def extract_tables_pdfplumber(uploaded_pdf):
    """Extrai tabelas de um PDF usando pdfplumber."""
    tables = []

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
        temp_pdf.write(uploaded_pdf.read())
        temp_pdf_path = temp_pdf.name

    with pdfplumber.open(temp_pdf_path) as pdf:
        for page in pdf.pages:
            extracted_tables = page.extract_tables()
            for table in extracted_tables:
                df = pd.DataFrame(table)
                df.dropna(how="all", inplace=True)
                df.dropna(axis=1, how="all", inplace=True)
                tables.append(df)

    return tables
