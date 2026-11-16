# SONANGOL (dados SIMULADOS) · publicação no Streamlit Community Cloud

Só o **painel** (`painel.py`) corre no Streamlit Cloud; a API Flask (`run_api.py`) precisa de um serviço próprio (ver abaixo).

1. Envie esta pasta para um repositório GitHub (sem `secrets.toml`).
2. share.streamlit.io → Create app → ficheiro principal **`painel.py`** → Python 3.12.
3. Secrets: `[sonangol]` `admin_senha = "…"` (modelo em `.streamlit/secrets.toml.example`). Sem isto a palavra-passe é a pública `sonangol-demo`.
4. A base de demonstração (500 postos) é gerada no 1.º arranque; o «modo vivo» mantém as leituras atuais enquanto a app estiver acordada. Os dados reiniciam quando a app reinicia.
5. Para o SIG-CAD online: Excel → «Pacote SIG-CAD (5 folhas)» → no SIG-CAD, Importar Excel/CSV.
   Para a API online, aloje `run_api.py` num serviço com Flask (Render/PythonAnywhere) e use o URL https.
