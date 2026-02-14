
import io
import re
import logging
from ofxparse import OfxParser
import pandas as pd
from datetime import datetime as _dt

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Mock data
bancos = [
    {"COMPE": "001", "Banco": "Banco do Brasil S.A."},
    {"COMPE": "237", "Banco": "Banco Bradesco S.A."},
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
    
    # Normaliza newlines para garantir que regex e splits funcionem bem
    file_str = file_str.replace('\r\n', '\n').replace('\r', '\n')
    
    # Remove linhas em branco/espaços do inicio para evitar que ofxparse pare de ler headers
    file_str = file_str.lstrip()

    # 0. Normaliza cabeçalho OFX
    if file_str.strip().startswith("<"):
        # Adiciona headers padrão forçando UTF-8
        print("DEBUG: Arquivo sem headers detectado. Adicionando headers padrao.")
        headers = """OFXHEADER:100
DATA:OFXSGML
VERSION:102
SECURITY:NONE
ENCODING:UTF-8
CHARSET:NONE
COMPRESSION:NONE
OLDFILEUID:NONE
NEWFILEUID:NONE
"""
        file_str = headers + "\n" + file_str
    else:
        # Se TEM headers, vamos garantir que são UTF-8
        print("DEBUG: Headers detectados. Forcando UTF-8.")
        
        # 1. Substitui ENCODING e CHARSET usando regex insensível a maiúsculas
        file_str = re.sub(r"^ENCODING:.*$", "ENCODING:UTF-8", file_str, flags=re.MULTILINE | re.IGNORECASE)
        file_str = re.sub(r"^CHARSET:.*$", "CHARSET:NONE", file_str, flags=re.MULTILINE | re.IGNORECASE)

        # 0. Normaliza cabeçalho existente
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
    
    # 2. Remove blocos vazios
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
    
    file_str = re.sub(r"<TRNAMT>([^<\n]+)\*", r"<TRNAMT>\1", file_str)
    file_str = re.sub(r"<TRNAMT>([^<\n]+)", _normalizar_valor, file_str)
    
    return file_str

def extrair_ofx(file_path):
    print(f"Processing {file_path}...")
    try:
        with open(file_path, "rb") as f:
            file_bytes = f.read()
            
        try:
            file_str = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            file_str = file_bytes.decode("latin-1", errors="ignore")
            
        file_str = _normalizar_ofx(file_str)
        
        file_bytes_normalized = file_str.encode("utf-8")
        
        if b"ENCODING:UTF-8" not in file_bytes_normalized[:1000]:
            print("ALERTA: Header ENCODING:UTF-8 não encontrado nos primeiros 1000 bytes!")
            headers = b"OFXHEADER:100\nDATA:OFXSGML\nVERSION:102\nSECURITY:NONE\nENCODING:UTF-8\nCHARSET:NONE\nCOMPRESSION:NONE\nOLDFILEUID:NONE\nNEWFILEUID:NONE\n\n"
            file_bytes_normalized = headers + file_bytes_normalized
        
        print("DEBUG: HEADERS BEING SENT TO OFXPARSER:")
        print(file_bytes_normalized[:500].decode('utf-8', errors='ignore'))
        print("-" * 20)

        ofx = OfxParser.parse(io.BytesIO(file_bytes_normalized))
        
        print("Parsing succesful!")

        # Obtém o código do banco
        bank_id = ""
        if hasattr(ofx.account, "routing_number"):
             bank_id = ofx.account.routing_number
        elif hasattr(ofx.account, "bank_id"):
             bank_id = ofx.account.bank_id

        if not bank_id:
            match = re.search(r"<BANKID>(\d+)", file_str)
            if match:
                bank_id = match.group(1).strip()

        print(f"Bank ID: {bank_id}")  

        banco = get_banco_nome(bank_id) if bank_id else "Banco Desconhecido"
        print(f"Banco: {banco}")
        
        transactions = [
            {
                "Data": t.date.strftime("%d/%m/%Y"),
                "Histórico": t.memo if t.memo else t.payee,
                "Valor": f"{abs(t.amount):,.2f}",
                "Débito/Crédito": "D" if t.type.lower() == "debit" else "C"
            }
            for t in ofx.account.statement.transactions
        ]
        
        df = pd.DataFrame(transactions)
        print(f"Extracted {len(df)} transactions.")
        print(df.head())
        return df

    except Exception as e:
        print(f"EXCEPTION: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    files = [
        r"c:\Users\Guilherme\Documents\_PROJETO\extratorio\zref\Bradesco_13022026_091343.OFX"
    ]
    
if __name__ == "__main__":
    files = [
        r"c:\Users\Guilherme\Documents\_PROJETO\extratorio\zref\Bradesco_13022026_091343.OFX"
    ]
    
    with open("debug_log.txt", "w", encoding="utf-8") as log_file:
        for f in files:
            log_file.write(f"Processing {f}\n")
            try:
                # Modifying extrair_ofx to use logging/print to file would be complex without rewriting it.
                # Instead, let's just run it and catch exception here, but we also need the debug prints inside.
                # Let's redefine print for the scope or just change the function to write to file.
                pass 
            except Exception:
                pass

# Re-implementing the execution part purely for debugging
    import sys
    
    # Redirect stdout/stderr to file
    sys.stdout = open("debug_log.txt", "w", encoding="utf-8")
    sys.stderr = sys.stdout

    print("Starting debug run...")
    for f in files:
        extrair_ofx(f)
    
    print("Finished.")
