import streamlit as st
import time
import json
import pandas as pd
from module.extrair_texto import (
    extract_text_pdfplumber, extract_text_pymupdf, extract_text_pdfminer, extract_tables_pdfplumber
)
from module.llm_open import executar_openai

# Configuração da Página
st.set_page_config(page_title='Extrator de PDF', layout='wide')

# Título do Aplicativo
st.title("Extrato AI")
st.subheader("Mirandinha extraíndo informações!")
st.image("assets/image/mirandinha.png", use_container_width=True)

# Upload de Arquivos PDF
uploaded_files = st.file_uploader("📂 Carregar extratos bancários (PDF)", type=["pdf"], accept_multiple_files=True)

# Seletor de Bibliotecas de Extração
st.sidebar.subheader("📌 Escolha a biblioteca de extração de texto:")
use_pdfplumber = st.sidebar.checkbox("pdfplumber", value=True)
use_pymupdf = st.sidebar.checkbox("PyMuPDF (fitz)")
use_pdfminer = st.sidebar.checkbox("PDFMiner.six")

if uploaded_files:
    st.write(f"📌 {len(uploaded_files)} arquivos carregados.")
    process_button = st.button("🚀 Processar PDFs")

    if process_button:
        st.write("⏳ Iniciando o processamento...")
        resultados = []

        for pdf in uploaded_files:
            inicio = time.time()

            try:
                textos_extraidos = {}

                # Extração de texto usando bibliotecas selecionadas
                if use_pdfplumber:
                    textos_extraidos["pdfplumber"] = extract_text_pdfplumber(pdf)
                if use_pymupdf:
                    textos_extraidos["PyMuPDF (fitz)"] = extract_text_pymupdf(pdf)
                if use_pdfminer:
                    textos_extraidos["PDFMiner.six"] = extract_text_pdfminer(pdf)

                # Exibir texto extraído para cada biblioteca
                for biblioteca, texto in textos_extraidos.items():
                    st.subheader(f"📄 Texto Extraído ({biblioteca}) - {pdf.name}")
                    st.text_area(f"Texto - {biblioteca}", texto, height=300)

                # Criar prompt para OpenAI usando a extração da primeira biblioteca selecionada
                biblioteca_selecionada = list(textos_extraidos.keys())[0] if textos_extraidos else "Nenhuma"
                texto_para_openai = textos_extraidos.get(biblioteca_selecionada, "")

                prompt = f"""
                Você é um assistente especializado em extração de dados financeiros, 
                com foco em análise e processamento de extratos bancários de diversos formatos e modelos. 
                Seu objetivo é identificar, estruturar e converter informações de extratos bancários em arquivos organizados para análise posterior.
                O formato de saída deve ser **sempre um json object** com as colunas: 
                ["Data", "Histórico", "Documento", "Débito/Crédito", "Valor R$", "Origem/Destino", "Banco"].
                Informações Importantes:
                - Retorne **somente** o json, sem texto adicional.
                - Certifique-se de que todas as strings e estruturas estejam corretamente encerradas.
                - Certifique-se de que todas as Data estejam no formato "DD/MM/AAAA".
                - Certifique-se de Histórico, seja referente à descrição da transação. ex: "Transferência", "Pagamento", "Compra", "IOF", "Pix enviado" .
                - Certifique-se de Documento, seja referente ao número do documento da transação.
                - Certifique-se de Débito/Crédito, seja referente ao tipo da transação. ex: (D=Débito, C=Crédito).
                - Certifique-se de Valor R$, seja referente valor da transação com até 2 casas decimais (negativo para Débito, positivo para Crédito)
                - Certifique-se de Origem/Destino, seja referente ao nome da pessoa ou empresa envolvida na transação.
                - Certifique-se de Banco, nome do banco envolvido (ex: 'Banco X' ou 'Mesmo Banco' para transações internas).

                Segue o conteúdo extraído do extrato bancário ({biblioteca_selecionada}):
                {texto_para_openai}
                """

                # Simulação do envio para OpenAI (descomente quando for usar)
                resposta_formatada = executar_openai(prompt)

                resposta_formatada["Arquivo"] = pdf.name
                resultados.append(resposta_formatada)

                fim = time.time()
                tempo_total = fim - inicio
                st.write(f"⏳ Tempo de processamento: {tempo_total:.2f} segundos")

            except Exception as erro:
                st.error(f"❌ Erro ao processar {pdf.name}: {erro}")

        # Consolidar todos os DataFrames e exibir
        if resultados:
            df_final = pd.concat(resultados, ignore_index=True)
            st.subheader("📊 Extratos Consolidados")
            st.dataframe(df_final)

            # Adicionar opção para baixar os dados consolidados em CSV
            csv = df_final.to_csv(index=False).encode('utf-8')
            st.download_button("⬇️ Baixar Extratos Consolidados (CSV)", csv, "extratos_consolidados.csv", "text/csv")
