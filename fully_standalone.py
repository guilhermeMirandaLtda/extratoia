
import io
import re
import logging
from ofxparse import OfxParser
import pandas as pd
import traceback

# Setup logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Mock data
bancos = [
    {"COMPE": "001", "Banco": "Banco do Brasil S.A."},
]

def get_banco_nome(bank_id):
    bank_id_norm = bank_id.lstrip("0") if bank_id else ""
    for banco in bancos:
        compe_norm = banco["COMPE"].lstrip("0") if banco["COMPE"] else ""
        if compe_norm == bank_id_norm:
            return banco["Banco"]
    return "Banco Desconhecido"

def _normalizar_ofx(file_str):
    """Normaliza o conteúdo OFX: corrige cabeçalho, datas, transações inválidas e valores."""
    from datetime import datetime as _dt
    
    # 0. Normaliza cabeçalho OFX
    header_end = file_str.find("<")
    if header_end > 0:
        header_part = file_str[:header_end]
        body_part = file_str[header_end:]
        lines = header_part.splitlines(True)
        normalized_lines = []
        for line in lines:
            if ":" in line:
                key, _, value = line.partition(":")
                clean_value = value.strip().replace(" ", "")
                ending = ""
                if line.endswith("\r\n"):
                    ending = "\r\n"
                elif line.endswith("\n"):
                    ending = "\n"
                normalized_lines.append("{}:{}{}".format(key.strip(), clean_value, ending))
            else:
                normalized_lines.append(line)
        file_str = "".join(normalized_lines) + body_part
    
    # 1. Converte datas
    def _converter_data(match):
        tag = match.group(1)
        data_str = match.group(2).strip()
        try:
            dt = _dt.strptime(data_str, "%d/%m/%Y %H:%M:%S")
            return f"<{tag}>{dt.strftime('%Y%m%d%H%M%S')}"
        except ValueError:
            return match.group(0)
    
    tags_data = r"<(DTSERVER|DTACCTUP|DTSTART|DTEND|DTPOSTED|DTUSER|DTAVAIL)>"
    pattern = tags_data + r"\s*(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2})"
    file_str = re.sub(pattern, _converter_data, file_str)
    
    # 2. Remove blocos <STMTTRN> com TRNAMT ou FITID vazios
    def _filtrar_transacao(match):
        bloco = match.group(0)
        if re.search(r"<TRNAMT>\s*<", bloco) or re.search(r"<TRNAMT>\s*$", bloco, re.MULTILINE):
            return ""
        if re.search(r"<FITID>\s*<", bloco) or re.search(r"<FITID>\s*$", bloco, re.MULTILINE):
            return ""
        return bloco
    
    file_str = re.sub(
        r"<STMTTRN>.*?</STMTTRN>",
        _filtrar_transacao,
        file_str,
        flags=re.DOTALL
    )
    
    # 3. Normaliza valores monetários
    def _normalizar_valor(match):
        valor_str = match.group(1).strip()
        if re.match(r"^-?\d{1,3}(\.\d{3})+\.\d{2}$", valor_str):
            partes = valor_str.rsplit(".", 1)
            inteiro = partes[0].replace(".", "")
            return "<TRNAMT>{}.{}".format(inteiro, partes[1])
        return match.group(0)
    
    # FIX: Remove asteriscos
    file_str = re.sub(r"<TRNAMT>([^<\n]+)\*", r"<TRNAMT>\1", file_str)
    
    file_str = re.sub(r"<TRNAMT>([^<\n]+)", _normalizar_valor, file_str)
    
    return file_str

def extrair_ofx(file_bytes):
    try:
        # Tenta decificar como utf-8, fallback para latin-1
        try:
            print("Attempting decode utf-8...")
            file_str = file_bytes.decode("utf-8")
            print("Decoded as UTF-8")
        except Exception as e:
            print(f"Decode UTF-8 failed with {type(e).__name__}: {e}")
            try:
                print("Attempting decode latin-1...")
                file_str = file_bytes.decode("latin-1", errors="ignore")
                print("Decoded as Latin-1")
            except Exception as e2:
                 print(f"Decode Latin-1 failed: {e2}")
                 raise e2
            
        print(f"DEBUG: file_str type: {type(file_str)}, len: {len(file_str)}")
        
        file_str = _normalizar_ofx(file_str)
        print(f"DEBUG: after normalizar type: {type(file_str)}, len: {len(file_str)}")
        
        # Check specific problematic content
        if "14.409.33" in file_str:
            print("DEBUG: Found 14.409.33 in content")
            match = re.search(r"<TRNAMT>.*?14\.409\.33.*?</TRNAMT>", file_str, re.DOTALL)
            if match:
                 print(f"DEBUG: Context: {match.group(0)!r}")

        print("Parsing...")
        # Encode back to bytes because ofxparse might prefer bytes or handles encoding internally
        file_bytes_normalized = file_str.encode("utf-8")
        ofx = OfxParser.parse(io.BytesIO(file_bytes_normalized))
        print("Parsed.")
        
        bank_id = ""
        if not bank_id:
            match = re.search(r"<BANKID>(\d+)", file_str)
            if match:
                bank_id = match.group(1).strip()

        banco = get_banco_nome(bank_id) if bank_id else "Banco Desconhecido"
        if banco == "Banco Desconhecido":
            org_match = re.search(r"<ORG>([^<\n]+)", file_str)
            if org_match:
                banco = org_match.group(1).strip()
                
        transactions = [
            {
                "Data": t.date.strftime("%d/%m/%Y"),
                "Histórico": t.memo if t.memo else t.payee,
                "Documento": t.checknum if t.checknum else "",                
                "Valor": f"{abs(t.amount):,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                "Débito/Crédito": "D" if t.type.lower() == "debit" else "C",
                "Origem/Destino": t.payee if t.payee else "",
                "Banco": banco
            }
            for t in ofx.account.statement.transactions
        ]
        return pd.DataFrame(transactions)
    except Exception as e:
        print("EXCEPTION CAUGHT:")
        print(traceback.format_exc())
        return pd.DataFrame()

if __name__ == "__main__":
    files = [
        r"c:\Users\Guilherme\Documents\_PROJETO\extratorio\zref\extrato_conta_corrente_1342-10371_2021-06.ofx",
        # r"c:\Users\Guilherme\Documents\_PROJETO\extratorio\zref\extrato_conta_corrente_1342-10371_2021-08.ofx"
    ]
    
    for f in files:
        print(f"\nProcessing {f}")
        with open(f, "rb") as cur_f:
            content = cur_f.read()
        df = extrair_ofx(content)
        if not df.empty:
            print(f"Success! {len(df)} transactions.")
        else:
            print("Failed (empty dataframe).")
