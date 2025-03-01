import streamlit as st
import pandas as pd
import google.generativeai as genai
import json
import io
import os
import logging
import re

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
    Envia o arquivo para o modelo gemini-2.0-pro-exp-02-05 e acumula os dados extraídos.
    Com response_mime_type "text/plain", a saída é tratada para extrair o JSON contido.
    Se a resposta ultrapassar o limite de tokens, a função solicita continuação até que
    todo o conteúdo seja processado.

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
            logger.debug(f"Texto bruto da resposta: {text_response[:300]}...")  # Log dos primeiros 300 caracteres

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

# Interface principal do Streamlit
st.title("Extratórios - Processamento Inteligente de Arquivos (v4)")
st.write("Faça o upload de arquivos PDF, Imagem, Texto ou CSV para extrair informações.")

uploaded_files = st.file_uploader("Carregue arquivos PDF, Imagem, Texto ou CSV", 
                                  type=['pdf', 'png', 'jpg', 'jpeg', 'txt', 'csv'], 
                                  accept_multiple_files=True)

for uploaded_file in uploaded_files:
    st.subheader(f"📄 Processando: {uploaded_file.name}")
    file_bytes = uploaded_file.read()
    mime_type = uploaded_file.type
    st.write(f"🔄 Extraindo dados do arquivo ({mime_type})...")
    dados_extrato, foi_truncado = extrair_informacoes(file_bytes, mime_type)

    if foi_truncado:
        st.warning("⚠️ A resposta foi cortada devido ao limite de tokens! Apenas as transações completas foram extraídas.")

    if not dados_extrato.empty:
        st.success("✅ Extração concluída!")
        st.dataframe(dados_extrato)
    else:
        st.warning("⚠️ Nenhuma informação extraída. Tente outro arquivo.")
