import pandas as pd
import google.generativeai as genai
import json
import streamlit as st
import io
import os
from PyPDF2 import PdfReader, PdfWriter

try:
    api_key = st.secrets["google"]["api_key"]
except (AttributeError, KeyError):
    api_key = os.getenv("GOOGLE_API_KEY")

if not api_key:
    st.error("🔴 ERRO: A chave da API do Google não foi encontrada!")
    st.stop()

genai.configure(api_key=api_key)

def extrair_informacoes(file_bytes, mime_type) -> (pd.DataFrame, bool):
    try:
        file_obj = io.BytesIO(file_bytes)
        uploaded_file = genai.upload_file(file_obj, mime_type=mime_type)

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

        response = genai.GenerativeModel("gemini-2.0-flash-exp").generate_content(
            [prompt, uploaded_file],
            generation_config={
                "temperature": 1,
                "top_p": 0.95,
                "top_k": 40,
                "max_output_tokens": 8192,
                "response_mime_type": "application/json"
            }
        )

        response_dict = response.to_dict()
        foi_truncado = response_dict.get("candidates", [{}])[0].get("finish_reason") == "MAX_TOKENS"

        json_data = response.text.strip()

        # Ajuste caso JSON venha truncado
        if not json_data.startswith("[") or not json_data.endswith("]"):
            idx = json_data.rfind("},")
            if idx != -1:
                json_data = json_data[:idx + 1] + "]"
        if not json_data.endswith("]"):
            json_data += "]"

        try:
            data = json.loads(json_data)
            if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
                raise ValueError("A resposta não está no formato de lista de dicionários.")
            return pd.DataFrame(data), foi_truncado
        except (json.JSONDecodeError, ValueError) as e:
            st.error(f"Erro ao processar o JSON: {e}")
            return pd.DataFrame(), False

    except Exception as e:
        st.error(f"Erro ao processar o arquivo: {e}")
        return pd.DataFrame(), False

st.set_page_config(page_title='Extratórios', layout='wide')
st.title('Extratórios - Processamento Inteligente de Arquivos (v3)')
uploaded_files = st.file_uploader(
    "Carregue arquivos PDF, Imagem, Texto ou CSV", 
    type=['pdf','png','jpg','jpeg','txt','csv'], 
    accept_multiple_files=True
)

if uploaded_files:
    for uploaded_file in uploaded_files:
        st.subheader(f"📄 Processando: {uploaded_file.name}")
        
        # Lendo o conteúdo do arquivo em bytes
        file_bytes = uploaded_file.read()
        mime_type = uploaded_file.type

        if mime_type == "application/pdf":
            try:
                pdf_reader = PdfReader(io.BytesIO(file_bytes))
                num_pages = len(pdf_reader.pages)
                progress_bar = st.progress(0)
                final_df = pd.DataFrame()
                overall_truncated = False

                for i in range(num_pages):
                    pdf_writer = PdfWriter()
                    pdf_writer.add_page(pdf_reader.pages[i])
                    page_buffer = io.BytesIO()
                    pdf_writer.write(page_buffer)
                    page_buffer.seek(0)

                    page_df, was_truncated = extrair_informacoes(page_buffer.read(), "application/pdf")
                    if was_truncated:
                        overall_truncated = True
                    if not page_df.empty:
                        final_df = pd.concat([final_df, page_df], ignore_index=True)

                    progress_bar.progress(int(((i+1)/num_pages)*100))

                if overall_truncated:
                    st.warning("⚠️ Algumas páginas tiveram resposta truncada.")
                if not final_df.empty:
                    st.success("✅ Extração concluída!")
                    st.dataframe(final_df)
                else:
                    st.warning("⚠️ Nenhuma informação extraída do PDF.")

            except Exception as e:
                st.error(f"Erro ao dividir o PDF: {e}")
        
        else:
            # Se não for PDF, processa normalmente
            df, was_truncated = extrair_informacoes(file_bytes, mime_type)
            if was_truncated:
                st.warning("⚠️ A resposta foi cortada devido ao limite de tokens.")
            if not df.empty:
                st.success("✅ Extração concluída!")
                st.dataframe(df)
            else:
                st.warning("⚠️ Nenhuma informação extraída.")
