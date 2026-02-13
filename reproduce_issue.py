
import io
import re
import logging
from ofxparse import OfxParser
import pandas as pd

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Mocking the banco list for get_banco_nome
bancos = [
    {"COMPE": "001", "Banco": "Banco do Brasil S.A."},
    {"COMPE": "341", "Banco": "Itaú Unibanco S.A."},
    {"COMPE": "033", "Banco": "Banco Santander (Brasil) S.A."},
    {"COMPE": "104", "Banco": "Caixa Econômica Federal"},
    {"COMPE": "237", "Banco": "Banco Bradesco S.A."},
]

def get_banco_nome(bank_id):
    """Retorna o nome do banco correspondente ao código COMPE do BANKID no OFX."""
    # Normaliza removendo zeros à esquerda para comparação consistente
    bank_id_norm = bank_id.lstrip("0") if bank_id else ""
    for banco in bancos:
        compe_norm = banco["COMPE"].lstrip("0") if banco["COMPE"] else ""
        if compe_norm == bank_id_norm:
            return banco["Banco"]
    return "Banco Desconhecido"

def _normalizar_ofx(file_str):
    """Normaliza o conteúdo OFX: corrige cabeçalho, datas, transações inválidas e valores."""
    from datetime import datetime as _dt
    
    # 0. Normaliza cabeçalho OFX (remove espaços extras nos valores)
    # Ex: "ENCODING: UTF - 8" -> "ENCODING:UTF-8"
    header_end = file_str.find("<")
    if header_end > 0:
        header_part = file_str[:header_end]
        body_part = file_str[header_end:]
        lines = header_part.splitlines(True)
        normalized_lines = []
        for line in lines:
            if ":" in line:
                key, _, value = line.partition(":")
                # Remove espaços do key e do value, e remove espaços internos do value
                clean_value = value.strip().replace(" ", "")
                # Preserva a quebra de linha original
                ending = ""
                if line.endswith("\r\n"):
                    ending = "\r\n"
                elif line.endswith("\n"):
                    ending = "\n"
                normalized_lines.append("{}:{}{}".format(key.strip(), clean_value, ending))
            else:
                normalized_lines.append(line)
        file_str = "".join(normalized_lines) + body_part
    
    # 1. Converte datas no formato dd/mm/yyyy HH:mm:ss para YYYYMMDDHHMMSS
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
    
    # 2. Remove blocos <STMTTRN> com TRNAMT ou FITID vazios (ex: "Saldo anterior")
    def _filtrar_transacao(match):
        bloco = match.group(0)
        # Se TRNAMT estiver vazio (tag seguida de outra tag ou fechamento)
        if re.search(r"<TRNAMT>\s*<", bloco) or re.search(r"<TRNAMT>\s*$", bloco, re.MULTILINE):
            return ""
        # Se FITID estiver vazio
        if re.search(r"<FITID>\s*<", bloco) or re.search(r"<FITID>\s*$", bloco, re.MULTILINE):
            return ""
        return bloco
    
    file_str = re.sub(
        r"<STMTTRN>.*?</STMTTRN>",
        _filtrar_transacao,
        file_str,
        flags=re.DOTALL
    )
    
    # 3. Normaliza valores monetários no formato brasileiro (ex: 9.500.00 -> 9500.00)
    def _normalizar_valor(match):
        valor_str = match.group(1).strip()
        # Se tem formato brasileiro (pontos como milhar): ex "9.500.00" ou "63.592.70"
        # Padrão: dígitos seguidos de .ddd uma ou mais vezes, terminando em .dd
        if re.match(r"^-?\d{1,3}(\.\d{3})+\.\d{2}$", valor_str):
            # Remove os pontos de milhar, mantém o último como decimal
            partes = valor_str.rsplit(".", 1)  # separa na última ocorrência
            inteiro = partes[0].replace(".", "")  # remove pontos de milhar
            return "<TRNAMT>{}.{}".format(inteiro, partes[1])
        return match.group(0)
    
    # 2.5 Remove asteriscos ou outros caracteres estranhos do valor
    file_str = re.sub(r"<TRNAMT>([^<\n]+)\*", r"<TRNAMT>\1", file_str)
    
    file_str = re.sub(r"<TRNAMT>([^<\n]+)", _normalizar_valor, file_str)
    
    return file_str

def extrair_ofx(file_path):
    print(f"Processing {file_path}...")
    try:
        with open(file_path, "rb") as f:
            file_bytes = f.read()
            
        file_str = file_bytes.decode("us-ascii", errors="ignore")
        file_str = _normalizar_ofx(file_str)
        
        # DEBUG: Dump normalized file
        debug_output = file_path + ".normalized.ofx"
        with open(debug_output, "w", encoding="utf-8") as f_debug:
            f_debug.write(file_str)
        print(f"Dumped normalized OFX to {debug_output}")
        
        # Parse!
        ofx = OfxParser.parse(io.StringIO(file_str))
        
        print(f"DEBUG: ofx.account: {ofx.account}")
        if ofx.account:
            print(f"DEBUG: ofx.account.statement: {ofx.account.statement}")
            if ofx.account.statement:
                print(f"DEBUG: ofx.account.statement.transactions type: {type(ofx.account.statement.transactions)}")
                print(f"DEBUG: ofx.account.statement.transactions len: {len(ofx.account.statement.transactions)}")
                # print(f"DEBUG: transactions: {ofx.account.statement.transactions}")
        
        # Check structure
        if ofx.account is None:
            print("Error: ofx.account is None")
            return
            
        if ofx.account.statement is None:
            print("Error: ofx.account.statement is None")
            return

        # Obtém o código do banco a partir da tag BANKID ou outra possível localização
        bank_id = ""
        if hasattr(ofx.account, "routing_number"):
             bank_id = ofx.account.routing_number
        elif hasattr(ofx.account, "bank_id"):
             bank_id = ofx.account.bank_id

        if not bank_id:
            match = re.search(r"<BANKID>(\d+)", file_str)  # Busca padrão "<BANKID>xxxx"
            if match:
                bank_id = match.group(1).strip()

        print(f"Bank ID extraído: {bank_id}")  

        # Busca o nome do banco com base no código BANKID
        banco = get_banco_nome(bank_id) if bank_id else "Banco Desconhecido"
        
        # Fallback: se não encontrou na lista, tenta usar a tag <ORG> do OFX
        if banco == "Banco Desconhecido":
            org_match = re.search(r"<ORG>([^<\n]+)", file_str)
            if org_match:
                banco = org_match.group(1).strip()
                
        print(f"Banco detectado: {banco}")
                
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
        
        df = pd.DataFrame(transactions)
        print(f"Extracted {len(df)} transactions.")
        return df

    except Exception as e:
        print(f"EXCEPTION: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    files = [
        r"c:\Users\Guilherme\Documents\_PROJETO\extratorio\zref\extrato_conta_corrente_1342-10371_2021-06.ofx",
        r"c:\Users\Guilherme\Documents\_PROJETO\extratorio\zref\extrato_conta_corrente_1342-10371_2021-08.ofx"
    ]
    
    for f in files:
        extrair_ofx(f)
