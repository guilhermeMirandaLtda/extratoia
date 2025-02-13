import pandas as pd
import google.generativeai as genai
import json
import streamlit as st
import io
import tempfile
import os

# Tentar carregar a chave da API do Streamlit Secrets ou variável de ambiente
try:
    api_key = st.secrets["google"]["api_key"]
except (AttributeError, KeyError):
    api_key = os.getenv("GOOGLE_API_KEY")  # Buscar em variáveis de ambiente

# Validar se a chave foi encontrada
if not api_key:
    st.error("🔴 ERRO: A chave da API do Google não foi encontrada! Defina no `.streamlit/secrets.toml` ou como variável de ambiente `GOOGLE_API_KEY`.")
    st.stop()

# Configurar API com a chave encontrada
genai.configure(api_key=api_key)
    
def extrair_informacoes(file_bytes, mime_type) -> (pd.DataFrame, bool):
    """
    Envia um arquivo para a API do Google Gemini e retorna um DataFrame estruturado.

    :param file_bytes: Conteúdo do arquivo (bytes).
    :param mime_type: Tipo MIME do arquivo (exemplo: "application/pdf", "image/png").
    :return: DataFrame contendo os dados extraídos.
    """
    try:
        # Criando um arquivo temporário na memória
        file_obj = io.BytesIO(file_bytes)

        # Faz upload do arquivo para a API (sem 'file_name')
        uploaded_file = genai.upload_file(file_obj, mime_type=mime_type)

        # Prompt otimizado
        prompt = """
        Você é um assistente especializado em **extração de dados financeiros** com foco em **análise e processamento de extratos bancários** de diferentes formatos e modelos.

                **Objetivo**:  
                Converter as informações do extrato bancário em um **JSON bem estruturado e validado**, garantindo que os campos sejam coerentes e que **não haja erros de formatação**.

                **Instruções**:
                Extraia os dados e retorne um JSON **validado e bem formatado**, garantindo que:
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

        # Solicitação à API
        response = genai.GenerativeModel("gemini-2.0-flash-exp").generate_content(
            [prompt, uploaded_file],
            generation_config={
                "temperature": 1,
                "top_p": 0.95,
                "top_k": 40,
                "max_output_tokens": 8192,
                "response_mime_type": "application/json"}
        )
        print(f"#### Response: {response}")

        # 🛠️ Identificar se houve truncamento por limite de tokens
        foi_truncado = False
        response_dict = response.to_dict()
        if response_dict.get("candidates", [{}])[0].get("finish_reason") == "MAX_TOKENS":
            foi_truncado = True
            

        # 🔹 Tratamento e validação do JSON 🔹
        try:
            json_data = response.text.strip()

            # 🛠️ Corrigir JSON truncado removendo a última entrada incompleta
            if not json_data.startswith("[") or not json_data.endswith("]"):
                json_data = json_data[:json_data.rfind("},") + 1] + "]"  # Remover entrada cortada e fechar JSON

            # Se ainda estiver truncado, forçamos o fechamento
            if not json_data.endswith("]"):
                json_data += "]"

            # Conversão para JSON
            data = json.loads(json_data)

            # Validação final: precisa ser uma lista de dicionários
            if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
                raise ValueError("A resposta da API não está no formato esperado.")

            return pd.DataFrame(data), foi_truncado

        except (json.JSONDecodeError, ValueError) as e:
            st.error(f"Erro ao processar o JSON: {e}")
            return pd.DataFrame(), False

    except Exception as e:
        st.error(f"Erro ao processar o arquivo: {e}")
        return pd.DataFrame(), False
    
    
# Configuração da página
st.set_page_config(page_title='Extrato IA', layout='wide')
st.title('Extrato IA - Processamento Inteligente de Arquivos')
st.write('Faça o upload de arquivos PDF, Imagem, Texto ou CSV para extrair informações.')

# Upload de arquivos
uploaded_files = st.file_uploader("Carregue arquivos PDF, Imagem, Texto ou CSV", 
                                  type=['pdf', 'png', 'jpg', 'jpeg', 'txt', 'csv'], 
                                  accept_multiple_files=True)

if uploaded_files:
    for uploaded_file in uploaded_files:
        st.subheader(f"📄 Processando: {uploaded_file.name}")
        
        # Obtendo os bytes e tipo MIME do arquivo
        file_bytes = uploaded_file.read()
        mime_type = uploaded_file.type

        # Enviando o arquivo para a API
        st.write(f"🔄 Extraindo dados do arquivo ({mime_type})...")

        dados_extrato, foi_truncado = extrair_informacoes(file_bytes, mime_type)

        # 🔹 Exibir aviso de truncamento antes de qualquer outro status 🔹
        if foi_truncado:
            st.warning("⚠️ A resposta foi cortada devido ao limite de tokens! Apenas as transações completas foram extraídas.")

        # Exibir os dados extraídos
        if not dados_extrato.empty:
            st.success("✅ Extração concluída!")
            st.dataframe(dados_extrato)
        else:
            st.warning("⚠️ Nenhuma informação extraída. Tente outro arquivo.")
