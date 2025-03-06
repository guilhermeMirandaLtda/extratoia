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
    menu_items={
        'Get Help': 'https://www.extremelycoolapp.com/help',
        'Report a bug': "https://www.extremelycoolapp.com/bug",
        'About': "# Esse app foi desenvolvido para extrair extratos dos mais variados formatos de bancos."
    }
)

# Configura o logger para gravar no arquivo "app.log"
logging.basicConfig(
    filename="app.log",
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Tentar carregar a chave da API do Streamlit Secrets ou variável de ambiente
try:
    api_key = st.secrets["google"]["api_key"]
except (AttributeError, KeyError):
    api_key = os.getenv("GOOGLE_API_KEY")

if not api_key:
    st.error("🔴 ERRO: A chave da API do Google não foi encontrada!")
    logger.error("API Key não encontrada.")
    st.stop()

# Configurar a API com a chave encontrada
genai.configure(api_key=api_key)

def extrair_informacoes(file_bytes, mime_type) -> (pd.DataFrame, bool):
    """
    Extrai dados de arquivos não-OFX utilizando o modelo do Google Generative AI.
    Retorna um DataFrame com os registros extraídos e um booleano indicando se houve truncamento.
    """
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
            "Débito/Crédito": "D para Débito, C para Crédito",
            "Valor": "Valor da transação com até 2 casas decimais, negativo para Débito, positivo para Crédito",
            "Origem/Destino": "Nome da pessoa ou empresa envolvida na transação, se disponível",
            "Banco": "Nome do banco ou instituição financeira do extrato"
        """
        all_data = []
        houve_truncamento = False
        current_prompt = prompt

        while True:
            response = genai.GenerativeModel("gemini-2.0-flash-thinking-exp-01-21").generate_content(
                [current_prompt, uploaded_file],
                generation_config={
                    "temperature": 1,
                    "top_p": 0.95,
                    "top_k": 64,
                    "max_output_tokens": 65536,
                    "stop_sequences": ["""CONTINUAR"""],
                    "response_mime_type": "text/plain"
                }
            )
            logger.debug(f"Response da API: {response}")
            response_dict = response.to_dict()
            current_truncado = (response_dict.get("candidates", [{}])[0].get("finish_reason") == "MAX_TOKENS")
            if current_truncado:
                houve_truncamento = True

            text_response = response.text.strip()
            logger.debug(f"Texto bruto da resposta: {text_response[:300]}...")

            # Extração do trecho que contenha um array JSON
            match = re.search(r'(\[.*\])', text_response, re.DOTALL)
            if match:
                json_data = match.group(1)
            else:
                json_data = text_response

            if not json_data.endswith("]"):
                json_data += "]"

            try:
                data = json.loads(json_data)
            except json.JSONDecodeError as e:
                st.error(f"Erro ao processar o JSON: {e}")
                logger.error(f"Erro no processamento do JSON: {e}")
                return pd.DataFrame(), False

            if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
                st.error("Formato inesperado da resposta da API.")
                logger.error("Formato inesperado da resposta da API.")
                return pd.DataFrame(), False

            logger.debug(f"Número de registros extraídos nesta interação: {len(data)}")
            all_data.extend(data)

            if not current_truncado:
                break
            else:
                current_prompt = "CONTINUAR"
                logger.debug("Resposta truncada. Solicitando continuação.")

        logger.info(f"Extração concluída com {len(all_data)} registros acumulados.")
        return pd.DataFrame(all_data), houve_truncamento

    except Exception as e:
        st.error(f"Erro ao processar o arquivo: {e}")
        logger.exception("Erro durante o processamento do arquivo:")
        return pd.DataFrame(), False

def object_to_dict(obj):
    if hasattr(obj, '__dict__'):
        result = {}
        for key, value in obj.__dict__.items():
            result[key] = object_to_dict(value)
        return result
    elif isinstance(obj, list):
        return [object_to_dict(item) for item in obj]
    else:
        return obj

def extrair_ofx(file_bytes):
    """
    Processa arquivos OFX e retorna um DataFrame com as colunas:
    "Data", "Histórico", "Documento", "Débito/Crédito", "Valor", "Origem/Destino", "Banco"
    """
    try:
        # Converte os bytes para string e utiliza StringIO para simular um arquivo
        file_str = file_bytes.decode("us-ascii", errors="ignore")
        ofx = OfxParser.parse(io.StringIO(file_str))
        
        # Extrai o nome do banco a partir de account.institution.organization
        banco = ""
        if (hasattr(ofx, "account") and hasattr(ofx.account, "institution") 
            and hasattr(ofx.account.institution, "organization")):
            banco = ofx.account.institution.organization.strip()

        transactions = []
        for transaction in ofx.account.statement.transactions:
            data = transaction.date.strftime("%d/%m/%Y")
            historico = transaction.memo if transaction.memo else transaction.payee
            documento = transaction.checknum if transaction.checknum else ""
            # Mapeia "Débito/Crédito" com base no tipo (debit -> "D", credit -> "C")
            t_type = getattr(transaction, "type", "").lower()
            debito_credito = "D" if t_type == "debit" else "C"
            valor = round(transaction.amount, 2)
            origem_destino = transaction.payee if transaction.payee else ""
            trans_dict = {
                "Data": data,
                "Histórico": historico,
                "Documento": documento,
                "Débito/Crédito": debito_credito,
                "Valor": valor,
                "Origem/Destino": origem_destino,
                "Banco": banco
            }
            transactions.append(trans_dict)

        return pd.DataFrame(transactions)
    except Exception as e:
        st.error(f"Erro ao processar o arquivo OFX: {e}")
        logger.exception("Erro durante o processamento do arquivo OFX:")
        return pd.DataFrame()
    
# Interface principal do Streamlit
st.title("Extratórios - Processamento Inteligente de Arquivos (v5)")
st.write("Faça o upload de arquivos PDF, Imagem, Texto, CSV ou OFX para extrair informações.")

uploaded_files = st.file_uploader(
    "Carregue arquivos PDF, Imagem, Texto, CSV ou OFX", 
    type=['pdf', 'png', 'jpg', 'jpeg', 'txt', 'csv', 'ofx'], 
    accept_multiple_files=True
)

for uploaded_file in uploaded_files:
    st.subheader(f"📄 Processando: {uploaded_file.name}")
    file_bytes = uploaded_file.read()
    mime_type = uploaded_file.type
    st.write(f"🔄 Extraindo dados do arquivo ({mime_type})...")

    # Verifica se o arquivo é OFX com base na extensão
    if uploaded_file.name.lower().endswith(".ofx"):
        dados_extrato = extrair_ofx(file_bytes)
        foi_truncado = False  # Não se aplica para OFX
    else:
        dados_extrato, foi_truncado = extrair_informacoes(file_bytes, mime_type)

    if foi_truncado:
        st.warning("⚠️ A resposta foi cortada devido ao limite de tokens! Apenas as transações completas foram extraídas.")

    if not dados_extrato.empty:
        st.success("✅ Extração concluída!")
        st.dataframe(dados_extrato)

        # Cálculo dos resumos
        # Separa as transações de crédito e débito
        credit_df = dados_extrato[dados_extrato["Débito/Crédito"] == "C"]
        debit_df = dados_extrato[dados_extrato["Débito/Crédito"] == "D"]
        
        # Quantidade e total de créditos
        credit_count = len(credit_df)
        credit_total = credit_df["Valor"].sum()
        
        # Quantidade e total de débitos (usando o valor absoluto para débitos)
        debit_count = len(debit_df)
        debit_total = debit_df["Valor"].abs().sum() * -1
        
        # Totais gerais
        total_count = len(dados_extrato)
        # O saldo total é calculado como (valor total dos débitos) - (valor total dos créditos)
        saldo_total = credit_total + debit_total 
        
        # Cria um DataFrame resumo
        resumo = pd.DataFrame({
            "Categoria": ["Crédito", "Débito", "Total"],
            "Quantidade": [credit_count, debit_count, total_count],
            "Valor": [f"{credit_total:,.2f}", f"{debit_total:,.2f}", f"{saldo_total:,.2f}"]
        }, columns=["Categoria", "Quantidade", "Valor"],)
        
        col1, col2 = st.columns(2)
        
        with col1:  
            st.write("### Resumo")
            st.table(resumo)
        with col2:
            pass
            
        st.divider()
    else:
        st.warning("⚠️ Nenhuma informação extraída. Tente outro arquivo.")
