"""Configuração e constantes da plataforma SONANGOL (dados SIMULADOS)."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
PASTA_DADOS = Path(os.environ.get("SONANGOL_DADOS", RAIZ.parent / "dados_sonangol"))
try:
    PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    (PASTA_DADOS / ".escrita").write_text("ok")
except OSError:      # alojamento só-de-leitura (ex.: Streamlit Cloud): usa a pasta temporária
    import tempfile
    PASTA_DADOS = Path(tempfile.gettempdir()) / "dados_sonangol"
    PASTA_DADOS.mkdir(parents=True, exist_ok=True)
CAMINHO_BD = Path(os.environ.get("SONANGOL_BD", PASTA_DADOS / "sonangol.db"))
GEO_JSON = RAIZ / "dados" / "geo_angola.json"

API_HOST = os.environ.get("SONANGOL_API_HOST", "127.0.0.1")
API_PORTA = int(os.environ.get("SONANGOL_API_PORTA", "8000"))
API_PREFIXO = "/api/v1"

AVISO_SIMULADO = ("DADOS SIMULADOS — esta plataforma é um ambiente de teste. Nenhuma informação aqui é oficial nem "
                  "pertence à Sonangol ou a qualquer empresa real.")

FUSO = timezone(timedelta(hours=1))          # Luanda (WAT, UTC+1)

# ---- catálogo de produtos (o mesmo conjunto do SIG-CAD) ----
PRODUTOS = {
    "Gasolina": dict(unidade="L", unidade_preco="Kz/L", preco=300.0, categoria="Derivado de petróleo"),
    "Gasóleo": dict(unidade="L", unidade_preco="Kz/L", preco=400.0, categoria="Derivado de petróleo"),
    "Jet A1": dict(unidade="L", unidade_preco="Kz/L", preco=520.0, categoria="Combustível de aviação"),
    "Petróleo iluminante": dict(unidade="L", unidade_preco="Kz/L", preco=150.0, categoria="Derivado de petróleo"),
    "GPL": dict(unidade="L", unidade_preco="Kz/botija 12 kg", preco=1200.0, categoria="Gás de petróleo liquefeito"),
}
NOMES_PRODUTOS = list(PRODUTOS)

ESTADOS_POSTO = ["Operacional", "Inoperacional", "Encerrado"]
ESTADOS_RESERVATORIO = ["Operacional", "Em manutenção", "Fora de serviço"]
ESTADOS_BOMBA = ["Operacional", "Avariada"]
ESTADOS_ENTREGA = ["Planeada", "Em trânsito", "Entregue", "Cancelada"]
TIPOS_MOVIMENTO = ["Saldo inicial", "Receção", "Venda", "Distribuição", "Ajuste"]
TIPOS_INSTALACAO = ["Refinaria", "Terminal de armazenamento", "Base logística", "Centro de distribuição"]
TIPOS_EMPRESA = ["Operadora", "Distribuidora", "Refinadora", "Logística"]
TIPOS_POSTO = ["Urbano", "Rodoviário", "Rural", "Aeroportuário", "Camionista"]

LIMIAR_BAIXO = 0.25        # abaixo disto o reservatório está com «stock reduzido»
FRACAO_MINIMO = 0.10       # quantidade mínima operacional = 10% da capacidade


def agora() -> datetime:
    """Hora actual de Luanda, sem fuso (naive)."""
    return datetime.now(FUSO).replace(tzinfo=None, microsecond=0)


def txt(dt: datetime | None) -> str | None:
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else None


def iso(s: str | None) -> str | None:
    """'2025-10-01 08:30:00' → '2025-10-01T08:30:00+01:00' (ISO 8601 com fuso de Luanda)."""
    return s.replace(" ", "T") + "+01:00" if s else None
