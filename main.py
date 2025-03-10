import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import io
import os
import logging
import re
from ofxparse import OfxParser 

st.set_page_config(
    page_title="Extratórios",
    page_icon="🧊",
    layout="wide",
    initial_sidebar_state="expanded",
)

logging.basicConfig(
    filename="app.log",
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

try:
    api_key = st.secrets["google"]["api_key"]
except (AttributeError, KeyError):
    api_key = os.getenv("GOOGLE_API_KEY")

if not api_key:
    st.error("🔴 ERRO: A chave da API do Google não foi encontrada!")
    logger.error("API Key não encontrada.")
    st.stop()

genai.configure(api_key=api_key)

def extrair_informacoes(file_bytes, mime_type) -> pd.DataFrame:
    """Extrai dados de arquivos não-OFX utilizando o modelo do Google Generative AI."""
    try:
        file_obj = io.BytesIO(file_bytes)
        uploaded_file = genai.upload_file(file_obj, mime_type=mime_type)
        prompt = """
        Você é um assistente especializado em **extração de dados financeiros** com foco em **análise e processamento de extratos bancários** de diferentes formatos e modelos.

        **Objetivo**:  
        Converter as informações do extrato bancário em um **JSON bem estruturado e validado**, garantindo que os campos sejam coerentes e que **não haja erros de formatação**.

        **Instruções**:
        - Extraia os dados e retorne um JSON **validado e bem formatado**, garantindo que:
            - Nenhum campo seja cortado.
            - O JSON seja **sempre fechado corretamente**.
            - **Nunca** retorne JSON truncado. Se necessário, adicione `]` no final para garantir integridade.
            - Os valores numéricos tenham **ponto como separador decimal**.
            - Se houver erro, retorne **[]** (um array vazio) ao invés de um JSON inválido.
            - Remova caracteres especiais ou trechos irrelevantes antes de retornar a resposta.
                    
        **Estrutura esperada do JSON**:
            "Data": "DD/MM/AAAA",
            "Histórico": "Descrição da transação, por exemplo: Transferência, Pagamento, Compra, IOF, Pix enviado",
            "Documento": "Número do documento da transação, se disponível. Caso contrário, manter vazio.",            
            "Valor": "Valor da transação com até 2 casas decimais, negativo para Débito, positivo para Crédito",
            "Débito/Crédito": "D para Débito, C para Crédito",
            "Origem/Destino": "Nome da pessoa ou empresa envolvida na transação, se disponível",
            "Banco": "Nome do banco ou instituição financeira do extrato"
        """
        response = genai.GenerativeModel("gemini-2.0-flash-thinking-exp-01-21").generate_content(
            [prompt, uploaded_file]
        )
        text_response = response.text.strip()
        match = re.search(r'(\[.*\])', text_response, re.DOTALL)
        json_data = match.group(1) if match else "[]"
        data = json.loads(json_data)
        df = pd.DataFrame(data)
        df["Valor"] = df["Valor"].abs()
        df["Valor"] = df["Valor"].map(lambda x: f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        return df
    except Exception as e:
        st.error(f"Erro ao processar o arquivo: {e}")
        logger.exception("Erro durante o processamento do arquivo:")
        return pd.DataFrame()

def extrair_ofx(file_bytes):
    """Processa arquivos OFX e retorna um DataFrame."""
    try:
        file_str = file_bytes.decode("us-ascii", errors="ignore")
        ofx = OfxParser.parse(io.StringIO(file_str))
        banco = ofx.account.institution.organization.strip() if hasattr(ofx, "account") else ""
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

st.title("Extratórios - Processamento Inteligente de Arquivos (v6)")
st.write("Faça o upload de arquivos PDF, Imagem, Texto, CSV ou OFX para extrair informações.")

uploaded_files = st.file_uploader(
    "Carregue arquivos PDF, Imagem, Texto, CSV ou OFX", 
    type=['pdf', 'png', 'jpg', 'jpeg', 'txt', 'csv', 'ofx'], 
    accept_multiple_files=True
)

todos_dados = []
for uploaded_file in uploaded_files:
    st.subheader(f"📄 Processando: {uploaded_file.name}")
    file_bytes = uploaded_file.read()
    mime_type = uploaded_file.type
    st.write(f"🔄 Extraindo dados do arquivo ({mime_type})...")
    
    dados_extrato = extrair_ofx(file_bytes) if uploaded_file.name.lower().endswith(".ofx") else extrair_informacoes(file_bytes, mime_type)
    
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
