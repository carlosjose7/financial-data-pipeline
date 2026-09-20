"""Variaveis centrais do pipeline. Nenhum caminho fica hardcoded no codigo.

Precedencia: variavel de ambiente > arquivo .env (na raiz do repo) > padrao abaixo.
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Carrega .env simples (sem dependencia externa): linhas CHAVE=VALOR, ignora # e vazias.
def _load_dotenv(path: Path = REPO_ROOT / ".env") -> None:
    try:
        if not path.is_file():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)
    except OSError:
        pass


_load_dotenv()

# --- Pastas de entrada / saida (configure via .env ou ambiente) ---
DEFAULT_EXTRATOS = (
    Path(r"C:\Users\Tesouraria\OneDrive - Igreja Batista em Jardim Ingá\Financeiro\Extratos")
)
DEFAULT_OUTPUT = (
    Path(r"C:\Users\Tesouraria\OneDrive - Igreja Batista em Jardim Ingá\Financeiro\ETL")
)

EXTRATOS_DIR = Path(os.getenv("EXTRATOS_DIR", str(DEFAULT_EXTRATOS)))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", str(DEFAULT_OUTPUT)))

# --- Subpastas por banco (dentro de EXTRATOS_DIR) ---
DIR_CORA = EXTRATOS_DIR / os.getenv("DIR_CORA", "Cora")
DIR_PAGSEGURO = EXTRATOS_DIR / os.getenv("DIR_PAGSEGURO", "PagSeguro")
DIR_BRADESCO = EXTRATOS_DIR / os.getenv("DIR_BRADESCO", "Bradesco")
DIR_MERCADOPAGO = EXTRATOS_DIR / os.getenv("DIR_MERCADOPAGO", "MercadoPago")

# --- Arquivos de saida (consumidos pelo Power BI) ---
OUTPUT_CONSOLIDADO = OUTPUT_DIR / os.getenv("OUTPUT_CONSOLIDADO", "Consolidado.csv")
OUTPUT_CALENDARIO = OUTPUT_DIR / os.getenv("OUTPUT_CALENDARIO", "dCalendario.csv")

# --- De-Para de nomes (Variacao -> Favorecido padrao). Editavel em Excel. ---
# Padrao: mesma pasta do Consolidado.csv. Se nao existir, Favorecido = Lancamento.
DEPARA_NOMES = Path(os.getenv("DEPARA_NOMES", str(OUTPUT_DIR / "DePara_Nomes.csv")))

# --- Flags de comportamento ---
def _as_bool(value: str, default: bool) -> bool:
    return str(value).strip().lower() in ("1", "true", "sim", "s", "yes", "y") if value != "" else default


BRADESCO_ENABLED = _as_bool(os.getenv("BRADESCO_ENABLED", "true"), True)
PDF_FALLBACK_ENABLED = _as_bool(os.getenv("PDF_FALLBACK_ENABLED", "false"), False)

# --- Schema padrao de saida (ordem das colunas do Consolidado.csv) ---
OUTPUT_COLUMNS = [
    "Data",
    "Lancamento",
    "Transacao",
    "Valor",
    "TipoTransacao",
    "Banco",
    "TransferenciaInterna",
    "ExcluirDoBalancete",
    "Arquivo",
    "Referencia",
    "Favorecido",
]

BANCOS = ("Cora", "PagSeguro", "MercadoPago", "Bradesco")
