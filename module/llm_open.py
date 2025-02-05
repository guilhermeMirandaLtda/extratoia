#module/llm_open.py
import streamlit as st
from openai import OpenAI
import json
import logging
import re
import tiktoken
import pandas as pd


# 🚀 Obtendo a chave da API do OpenAI do arquivo secrets.toml
try:
    OPENAI_API_KEY = st.secrets["openai"]["api_key"]
    print("🔑 API Key:", st.secrets["openai"]["api_key"])
except Exception as e:
    print("❌ ERRO ao acessar o secrets.toml:", e)


# ✅ Configura o cliente OpenAI com a chave da API
cliente_openai = OpenAI(api_key=OPENAI_API_KEY)

def dividir_texto(texto, modelo="gpt-4o-mini", limite_tokens=4000, overlap=200):
    """
    Divide um texto longo em partes menores para envio à API, garantindo que não haja perda de contexto.

    Args:
        texto (str): Texto completo a ser dividido.
        modelo (str): Modelo OpenAI usado para calcular os tokens.
        limite_tokens (int): Número máximo de tokens por bloco.
        overlap (int): Número de tokens repetidos entre blocos para manter o contexto.

    Returns:
        list: Lista de blocos de texto processados.
    """
    codificacao = tiktoken.encoding_for_model(modelo)

    # 🛠️ Melhor abordagem: Dividir por parágrafos em vez de sentenças individuais
    paragrafos = texto.strip().split("\n\n")  # Parágrafos são separados por duas quebras de linha

    blocos = []
    bloco_atual = []
    tokens_acumulados = 0

    for paragrafo in paragrafos:
        tokens_paragrafo = len(codificacao.encode(paragrafo))

        # Se ultrapassar o limite, fecha o bloco atual e inicia um novo
        if tokens_acumulados + tokens_paragrafo > limite_tokens:
            blocos.append("\n\n".join(bloco_atual))  # Preservando separação original
            sobreposicao = bloco_atual[-(overlap // tokens_paragrafo):] if bloco_atual else []
            bloco_atual = sobreposicao.copy()
            tokens_acumulados = sum(len(codificacao.encode(p)) for p in bloco_atual)

        bloco_atual.append(paragrafo)
        tokens_acumulados += tokens_paragrafo

    if bloco_atual:
        blocos.append("\n\n".join(bloco_atual))

    return blocos

def executar_openai(prompt):
    """
    Executa a API OpenAI com o prompt fornecido e retorna um DataFrame.

    Args:
        prompt (str): Instruções para a API OpenAI.

    Returns:
        pd.DataFrame: DataFrame contendo os dados extraídos da resposta JSON.
    """
    try:
        logging.info("🔍 Enviando requisição para OpenAI...")

        resposta = cliente_openai.chat.completions.create(
            model="gpt-4o-mini",  # Modelo atualizado para um mais confiável
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Você é um assistente especializado em extração de dados financeiros, "
                        "com foco em análise e processamento de extratos bancários."
                    )
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=16383,
            temperature=0.5,
            response_format={"type": "json_object"},  # Corrigido para garantir resposta JSON válida
        )

        texto_resposta = resposta.choices[0].message.content.strip()

        # 📌 Remover delimitadores ```json e ``` se existirem
        if texto_resposta.startswith("```json") and texto_resposta.endswith("```"):
            texto_resposta = texto_resposta[7:-3].strip()

        # 📌 Garantir que a resposta seja um JSON válido antes de converter
        try:
            dados = json.loads(texto_resposta)

            # 📌 Se os dados retornados forem um dicionário, tente extrair a lista correta
            if isinstance(dados, dict):
                # Verifica se há uma chave principal contendo a lista de transações
                for key in dados:
                    if isinstance(dados[key], list):
                        dados = dados[key]
                        break

            if not isinstance(dados, list):
                raise ValueError("A resposta da OpenAI não contém uma lista de transações.")

        except json.JSONDecodeError as erro_json:
            logging.error(f"❌ ERRO: A resposta da API não é um JSON válido! {erro_json}")
            return pd.DataFrame(columns=["Data", "Histórico", "Documento", "Débito/Crédito", "Valor R$", "Origem/Destino", "Banco"])

        # 📌 Converter JSON para DataFrame
        df = pd.DataFrame(dados)

        # ✅ Verificar se a resposta contém os campos esperados
        colunas_esperadas = ["Data", "Histórico", "Documento", "Débito/Crédito", "Valor R$", "Origem/Destino", "Banco"]
        for coluna in colunas_esperadas:
            if coluna not in df.columns:
                logging.warning(f"⚠️ A coluna esperada '{coluna}' não está presente na resposta.")

        return df

    except Exception as erro:
        logging.error(f"❌ ERRO ao conectar à OpenAI API: {erro}")
        return pd.DataFrame(columns=["Data", "Histórico", "Documento", "Débito/Crédito", "Valor R$", "Origem/Destino", "Banco"])