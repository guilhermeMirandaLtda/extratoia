import streamlit as st
import pandas as pd
import io
import os
import logging
import re
from ofxparse import OfxParser 
from version import VERSION
from banco import bancos

st.set_page_config(
    page_title="Extratórios",
    page_icon="🧊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

logging.basicConfig(
    filename="app.log",
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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
    
    file_str = re.sub(r"<TRNAMT>([^<\n]+)", _normalizar_valor, file_str)
    
    return file_str

def extrair_ofx(file_bytes):
    """Processa arquivos OFX e retorna um DataFrame."""
    try:
        file_str = file_bytes.decode("us-ascii", errors="ignore")
        file_str = _normalizar_ofx(file_str)
        ofx = OfxParser.parse(io.StringIO(file_str))
        

        # Obtém o código do banco a partir da tag BANKID ou outra possível localização
        bank_id = ""
        if not bank_id:
            match = re.search(r"<BANKID>(\d+)", file_str)  # Busca padrão "<BANKID>xxxx"
            if match:
                bank_id = match.group(1).strip()

        logger.debug(f"Bank ID extraído após verificação: {bank_id}")  # Log do BANKID para depuração


        logger.debug(f"Bank ID extraído: {bank_id}")  # Log do BANKID para depuração

        # Busca o nome do banco com base no código BANKID
        banco = get_banco_nome(bank_id) if bank_id else "Banco Desconhecido"
        
        # Fallback: se não encontrou na lista, tenta usar a tag <ORG> do OFX
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
        st.error(f"Erro ao processar o arquivo OFX: {e}")
        logger.exception("Erro durante o processamento do arquivo OFX:")
        return pd.DataFrame()

st.title("Extratórios - Processamento de Extratos OFX")
st.write("Faça o upload de arquivos OFX para extrair informações financeiras.")
st.caption(f"Versão: {VERSION}")

uploaded_files = st.file_uploader(
    "Carregue arquivos OFX", 
    type=['ofx'], 
    accept_multiple_files=True
)

todos_dados = []
for uploaded_file in uploaded_files:
    st.subheader(f"📄 Processando: {uploaded_file.name}")
    file_bytes = uploaded_file.read()
    st.write(f"🔄 Extraindo dados do arquivo OFX...")
    
    dados_extrato = extrair_ofx(file_bytes)
    
    if not dados_extrato.empty:
        todos_dados.append(dados_extrato)
        st.success("✅ Extração concluída!")
        st.dataframe(dados_extrato)
        
        # Convertendo os valores de string formatada para float
        dados_extrato["Valor"] = (
            dados_extrato["Valor"]
            .astype(str)
            .str.replace(".", "", regex=False)  # Remove separadores de milhar
            .str.replace(",", ".", regex=False)  # Troca vírgula decimal por ponto
            .astype(float)  # Converte para float
        )
        # Separa as transações de crédito e débito
        credit_df = dados_extrato[dados_extrato["Débito/Crédito"] == "C"]
        debit_df = dados_extrato[dados_extrato["Débito/Crédito"] == "D"]

        # Calcula a quantidade e os totais de crédito e débito
        credit_count = len(credit_df)
        debit_count = len(debit_df)
        credit_total = credit_df["Valor"].sum()
        debit_total = debit_df["Valor"].sum()
        total_count = len(dados_extrato)
        saldo_total = credit_total - debit_total  # Saldo final

        # Formatação correta para o padrão brasileiro
        resumo = pd.DataFrame({
            "Categoria": ["Crédito", "Débito", "Total"],
            "Quantidade": [credit_count, debit_count, total_count],
            "Valor": [f"{credit_total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                    f"{debit_total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                    f"{saldo_total:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")]
        })

        # Exibe o resumo abaixo do DataFrame extraído
        col1, col2 = st.columns(2)
        
        with col1:  
            st.write("### Resumo")
            st.table(resumo)
        with col2:
            pass
            
        st.divider()

    else:
        st.warning("⚠️ Nenhuma informação extraída.")

if todos_dados:
    df_final = pd.concat(todos_dados, ignore_index=True)
    
    def convert_df_to_excel(df):
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='Extratos')
        return output.getvalue()
    
    excel_data = convert_df_to_excel(df_final)
    st.download_button(
        label="📥 Baixar Extratos em Excel",
        data=excel_data,
        file_name="extratos.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
