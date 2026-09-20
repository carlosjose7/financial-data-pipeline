"""ETL consolidado: le todos os CSVs de Extratos/<Banco>/ e gera Consolidado.csv + dCalendario.csv.

Uso via codigo:
    from src import config
    from src.etl import processar_tudo
    stats = processar_tudo()

Uso via CLI:
    python main.py [--extratos DIR] [--saida DIR] [--sem-bradesco] [--com-pdf]
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from src import config

# ---------------------------------------------------------------- helpers ---

def parse_valor_br(valor) -> float:
    """Converte '1.580,51' / '-144,68' / '9,81 ' / 240 -> float. Retorna 0.0 se vazio/invalido."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return 0.0
    t = str(valor).strip().replace("\u00a0", "")
    if t in ("", "-"):
        return 0.0
    tem_ponto = "." in t
    tem_virgula = "," in t
    if tem_ponto and tem_virgula:
        t = t.replace(".", "")  # milhar
    t = t.replace(",", ".")  # decimal BR -> US
    try:
        return float(t)
    except ValueError:
        return 0.0


def parse_data_br(valor) -> pd.Timestamp | None:
    """Aceita 'dd/MM/yyyy' e 'dd-MM-yyyy'. Retorna Timestamp ou None."""
    if valor is None or (not isinstance(valor, str) and pd.isna(valor)):
        return None
    t = str(valor).strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y"):
        try:
            return pd.to_datetime(t, format=fmt)
        except ValueError:
            continue
    return None


def _decode_smart(raw: bytes) -> str:
    """Decodifica bytes mistos: tenta UTF-8; linhas com bytes latin-1 caem para cp1252.

    Alguns exports do banco misturam encodings no mesmo arquivo (ex.: CORA_09-setembro-2025).
    Decodificar o arquivo inteiro como cp1252 geraria mojibake (Ã§) nas linhas UTF-8.
    """
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    linhas = []
    for line in raw.split(b"\n"):
        try:
            linhas.append(line.decode("utf-8-sig"))
        except UnicodeDecodeError:
            linhas.append(line.decode("cp1252"))
    return "\n".join(linhas)


def _read_csv_flexivel(path: Path, delimiter: str, **kwargs) -> pd.DataFrame:
    """Le CSV independente do encoding (utf-8, latin-1 ou misto por linha)."""
    import io
    return pd.read_csv(io.StringIO(_decode_smart(Path(path).read_bytes())),
                       delimiter=delimiter, **kwargs)


def _norm_txt_upper(texto: str) -> str:
    """Maiusculas sem acento para comparacao de regras (ex.: TRANSAÇÃO->TRANSACAO)."""
    t = (texto or "").upper()
    for a, b in (("Á", "A"), ("Ã", "A"), ("Â", "A"), ("É", "E"), ("Ê", "E"),
                 ("Í", "I"), ("Ó", "O"), ("Ô", "O"), ("Õ", "O"), ("Ú", "U"), ("Ç", "C")):
        t = t.replace(a, b)
    return t


def _eh_transferencia_interna(lanc: str, tran: str, banco: str) -> str:
    """Marca SIM para operacoes entre contas da propria organizacao (ignoradas pelo balancete).

    Regras (ordem importa):
    1. ACAMPAMENTO nunca e transferencia interna (vai para ExcluirDoBalancete).
    2. 'ENTRE CONTAS' no lancamento (ex.: 'Transferência entre contas PagBank').
    3. 'RESERV*' / 'PATRIMONIO' (ex.: 'Dinheiro retirado Reserva', 'Valor reservado').
    4. Nome da propria organizacao no lancamento (palavras-chave de IGREJA_KEYWORDS
       no .env, qualquer tipo de transacao).
    5. Menções cruzadas entre bancos (Cora <-> PagSeguro <-> Mercado Pago).
    """
    l = _norm_txt_upper(lanc)
    t = _norm_txt_upper(tran)
    if "ACAMPAMENTO" in l or "ACAMPAMENTO" in t:
        return "NAO"
    if "ENTRE CONTAS" in l:
        return "SIM"
    if "RESERV" in l or "PATRIMONIO" in l:
        return "SIM"
    if any(_norm_txt_upper(kw) in l for kw in config.IGREJA_KEYWORDS):
        return "SIM"
    b = (banco or "").upper()
    interna = (
        (b == "CORA" and ("PAGSEGURO" in l or "PAGBANK" in l or "MERCADO PAGO" in l))
        or (b == "PAGSEGURO" and ("CORA" in l or "MERCADO PAGO" in l))
        or (b == "MERCADO PAGO" and ("CORA" in l or "PAGSEGURO" in l or "PAGBANK" in l))
    )
    return "SIM" if interna else "NAO"


def _norm_chave_nome(texto: str) -> str:
    import re
    import unicodedata
    s = unicodedata.normalize("NFKD", str(texto or "")).encode("ASCII", "ignore").decode()
    return re.sub(r"\s+", " ", s.upper().strip())


_MAPA_FAVORECIDO: dict | None = None


def _mapa_favorecido() -> dict:
    """Carrega DePara_Nomes.csv (Padrao;Variacao). Ausente => mapeamento identidade."""
    global _MAPA_FAVORECIDO
    if _MAPA_FAVORECIDO is None:
        _MAPA_FAVORECIDO = {}
        try:
            if config.DEPARA_NOMES.is_file():
                mapa = pd.read_csv(config.DEPARA_NOMES, sep=";", encoding="utf-8", dtype=str)
                for _, row in mapa.iterrows():
                    var, pad = str(row.get("Variacao", "")), str(row.get("Padrao", ""))
                    if var.strip() and pad.strip():
                        _MAPA_FAVORECIDO[_norm_chave_nome(var)] = pad.strip()
        except Exception:
            pass
    return _MAPA_FAVORECIDO


def _padronizar(df: pd.DataFrame, banco: str, arquivo: str) -> pd.DataFrame:
    """Aplica colunas de negocio e ordena no schema de saida."""
    df = df.copy()
    mapa = _mapa_favorecido()
    df["Favorecido"] = df["Lancamento"].astype(str).map(
        lambda v: mapa.get(_norm_chave_nome(v), str(v).strip())
    )
    df["Valor"] = df["Valor"].astype(float)
    df["TipoTransacao"] = df["Valor"].apply(lambda v: "CRÉDITO" if v >= 0 else "DÉBITO")
    df["Banco"] = banco
    df["Arquivo"] = arquivo
    df["TransferenciaInterna"] = df.apply(
        lambda r: _eh_transferencia_interna(r["Lancamento"], r["Transacao"], banco), axis=1
    )
    df["ExcluirDoBalancete"] = df["Lancamento"].str.upper().str.contains(
        "ACAMPAMENTO", na=False
    ).map(lambda x: "SIM" if x else "NAO")
    if "Referencia" not in df.columns:
        df["Referencia"] = ""
    df["Referencia"] = df["Referencia"].astype(str).str.strip()
    df["Data"] = pd.to_datetime(df["Data"])
    return df[config.OUTPUT_COLUMNS]


# ------------------------------------------------------------- parsers -------

def _limpa_nome_col(c: str) -> str:
    """Normaliza cabecalho: aspas de export ('Data' -> Data) + NFC (acentos compostos)."""
    import unicodedata
    return unicodedata.normalize("NFC", str(c).strip().strip("'").strip('"').strip())


def ler_cora(path: Path) -> pd.DataFrame:
    """CSV Cora: 'Data,Transação,Tipo Transação,Identificação,Valor' (virgula, UTF-8)."""
    raw = _read_csv_flexivel(path, delimiter=",")
    raw.columns = [_limpa_nome_col(c) for c in raw.columns]
    # normaliza pelos nomes esperados (com/sem acento)
    def col(*nomes):
        for n in nomes:
            if n in raw.columns:
                return n
        raise KeyError(f"Colunas {list(raw.columns)} em {path.name}")
    c_data = col("Data")
    c_trans = col("Transação", "Transacao")
    c_ident = col("Identificação", "Identificacao")
    c_valor = col("Valor")
    df = pd.DataFrame({
        "Data": raw[c_data].map(parse_data_br),
        "Transacao": raw[c_trans].astype(str).str.strip().str.strip("'\""),
        "Lancamento": raw[c_ident].astype(str).str.strip().str.strip("'\""),
        "Valor": raw[c_valor].map(parse_valor_br),
        "Referencia": "",
    })
    return df.dropna(subset=["Data"])


def ler_pagseguro(path: Path) -> pd.DataFrame:
    """CSV PagSeguro: 'CODIGO DA TRANSACAO;DATA;TIPO;DESCRICAO;VALOR' (; , decimal virgula)."""
    raw = _read_csv_flexivel(path, delimiter=";")
    raw.columns = [_limpa_nome_col(c) for c in raw.columns]
    df = pd.DataFrame({
        "Data": raw["DATA"].map(parse_data_br),
        "Transacao": raw["TIPO"].astype(str).str.strip(),
        "Lancamento": raw["DESCRICAO"].astype(str).str.strip(),
        "Valor": raw["VALOR"].map(parse_valor_br),
        "Referencia": raw["CODIGO DA TRANSACAO"].astype(str).str.strip(),
    })
    return df.dropna(subset=["Data"])


def ler_bradesco(path: Path) -> pd.DataFrame:
    """CSV Bradesco: cabecalho 'Data;Lançamento;Dcto.;Crédito;Débito;Saldo' (; , latin1).

    Ignora linhas de Total/cabecalho/SALDO ANTERIOR pelo padrao de data.
    Desempilha Credito/Debito em uma coluna Valor unica.
    """
    raw = _read_csv_flexivel(path, delimiter=";", skiprows=2, dtype=str, engine="python")
    raw.columns = [str(c).strip() for c in raw.columns]
    # localiza colunas por posicao/nome (tolera variacoes de acento)
    cols = list(raw.columns)
    c_data, c_lanc = cols[0], cols[1]
    c_dcto = cols[2]
    c_cred = next((c for c in cols if "rédito" in c or "redito" in c or "Cr" in c), cols[3])
    c_deb = next((c for c in cols if "bito" in c or "bito" in c or "bito" in c or "ébito" in c or "De" in c), cols[4])
    # normaliza: so linhas com data valida dd/MM/yyyy
    raw["__data"] = raw[c_data].map(parse_data_br)
    raw = raw.dropna(subset=["__data"])
    raw = raw[~raw[c_lanc].astype(str).str.contains("SALDO ANTERIOR", na=False)]
    raw = raw[~raw[c_lanc].astype(str).str.contains("Total", na=False)]
    cred = pd.DataFrame({
        "Data": raw["__data"],
        "Transacao": "",
        "Lancamento": raw[c_lanc].astype(str).str.strip(),
        "Valor": raw[c_cred].map(parse_valor_br),
        "Referencia": raw[c_dcto].astype(str).str.strip(),
    })
    deb = pd.DataFrame({
        "Data": raw["__data"],
        "Transacao": "",
        "Lancamento": raw[c_lanc].astype(str).str.strip(),
        "Valor": raw[c_deb].map(lambda v: -abs(parse_valor_br(v)) if str(v).strip() not in ("", "nan", "None") else float("nan")),
        "Referencia": raw[c_dcto].astype(str).str.strip(),
    })
    df = pd.concat([cred, deb], ignore_index=True).dropna(subset=["Valor"])
    df = df[df["Valor"] != 0]
    return df.reset_index(drop=True)


def ler_mercadopago_csv(path: Path) -> pd.DataFrame:
    """CSV Mercado Pago: bloco inicial + cabecalho 'RELEASE_DATE;TRANSACTION_TYPE;...'."""
    linhas = path.read_bytes()
    texto = None
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            texto = linhas.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    assert texto is not None
    rows = [r.split(";") for r in texto.splitlines()]
    rows_norm = [[_limpa_nome_col(c) for c in r] for r in rows]
    inicio = next((i for i, r in enumerate(rows_norm) if "RELEASE_DATE" in r), None)
    if inicio is None:
        return pd.DataFrame(columns=["Data", "Transacao", "Lancamento", "Valor", "Referencia"])
    hdr = rows_norm[inicio]
    i_data = hdr.index("RELEASE_DATE")
    i_lanc = hdr.index("TRANSACTION_TYPE")
    i_val = hdr.index("TRANSACTION_NET_AMOUNT")
    i_ref = hdr.index("REFERENCE_ID") if "REFERENCE_ID" in hdr else None
    regs = []
    for r in rows[inicio + 1:]:
        if len(r) <= max(i_data, i_lanc, i_val):
            continue
        lanc = r[i_lanc].strip().strip("'\"")
        if not lanc or lanc == "Saída de dinheiro":
            continue
        d = parse_data_br(r[i_data])
        if d is None:
            continue
        regs.append({"Data": d, "Transacao": lanc, "Lancamento": lanc,
                     "Valor": parse_valor_br(r[i_val]),
                     "Referencia": r[i_ref].strip().strip("'\"") if i_ref is not None and len(r) > i_ref else ""})
    cols = ["Data", "Transacao", "Lancamento", "Valor", "Referencia"]
    return pd.DataFrame(regs, columns=cols) if regs else pd.DataFrame(columns=cols)


# --- fallback PDF (opcional, formato antigo do Mercado Pago em PDF) ---
_MP_PATTERN = re.compile(
    r"(\d{2}-\d{2}-\d{4})"      # Data
    r"([\s\S]*?)"               # Descricao
    r"(\d{11})"                 # ID da operacao
    r"\s+R\$\s+([\d.,-]+)"      # Valor
    r"\s+R\$\s+([\d.,]+)"       # Saldo
)


def ler_mercadopago_pdf(path: Path) -> pd.DataFrame:
    from PyPDF2 import PdfReader  # import tardio: so exige PyPDF2 se o fallback for usado
    reader = PdfReader(str(path))
    texto = "".join([(p.extract_text() or "") for p in reader.pages])
    matches = _MP_PATTERN.findall(texto)
    df = pd.DataFrame(matches, columns=["Data", "Lancamento", "codigo", "Valor", "Saldo"])
    if df.empty:
        return pd.DataFrame(columns=["Data", "Transacao", "Lancamento", "Valor", "Referencia"])
    df["Data"] = df["Data"].map(parse_data_br)
    df["Valor"] = df["Valor"].map(parse_valor_br)
    df["Transacao"] = ""
    df["Lancamento"] = df["Lancamento"].astype(str).str.strip()
    df["Referencia"] = df["codigo"].astype(str).str.strip()
    return df.dropna(subset=["Data"])[["Data", "Transacao", "Lancamento", "Valor", "Referencia"]]


_PARSER_POR_BANCO = {
    "Cora": ler_cora,
    "PagSeguro": ler_pagseguro,
    "Bradesco": ler_bradesco,
    "MercadoPago": ler_mercadopago_csv,
}


def processar_banco(banco: str, pasta: Path) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Le todos os *.csv de uma pasta. Retorna (df_padronizado, arquivos_lidos, ignorados)."""
    parser = _PARSER_POR_BANCO[banco]
    frames, lidos, ignorados = [], [], []
    if not pasta.is_dir():
        return pd.DataFrame(columns=config.OUTPUT_COLUMNS), [], [f"{banco}/: pasta nao encontrada"]
    for path in sorted(pasta.glob("*.cs*")):  # .csv e .CSV
        try:
            df = parser(path)
            if not df.empty:
                frames.append(_padronizar(df, banco, path.name))
            lidos.append(path.name)
        except Exception as e:
            ignorados.append(f"{path.name}: {e}")
    base = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=config.OUTPUT_COLUMNS)
    return base, lidos, ignorados


def processar_pdfs_fallback(extratos_dir: Path) -> pd.DataFrame:
    """Le PDFs avulsos na raiz de Extratos (mercado_pago_*.pdf etc)."""
    frames = []
    for path in sorted(extratos_dir.glob("*.pdf")):
        try:
            df = ler_mercadopago_pdf(path)
            if not df.empty:
                frames.append(_padronizar(df, "MercadoPago", path.name))
        except Exception:
            continue
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=config.OUTPUT_COLUMNS)


def gerar_dcalendario(inicio: date = date(2021, 1, 1),
                      fim: date = date(2030, 12, 31)) -> pd.DataFrame:
    meses = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
             "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
    datas = pd.date_range(inicio, fim, freq="D")
    return pd.DataFrame({
        "Data": datas.strftime("%d/%m/%Y"),
        "Ano": datas.year,
        "MesNumero": datas.month,
        "Mes": [meses[m - 1] for m in datas.month],
        "AnoMes": datas.strftime("%Y-%m"),
        "Trimestre": [f"T{(m - 1) // 3 + 1}" for m in datas.month],
    })


def processar_tudo(extratos_dir: Path | None = None,
                   output_dir: Path | None = None,
                   com_bradesco: bool | None = None,
                   com_pdf: bool | None = None) -> dict:
    """Pipeline completo. Retorna estatisticas. Escreve Consolidado.csv + dCalendario.csv."""
    extratos_dir = Path(extratos_dir) if extratos_dir else config.EXTRATOS_DIR
    output_dir = Path(output_dir) if output_dir else config.OUTPUT_DIR
    com_bradesco = config.BRADESCO_ENABLED if com_bradesco is None else com_bradesco
    com_pdf = config.PDF_FALLBACK_ENABLED if com_pdf is None else com_pdf

    bancos = {"Cora": config.DIR_CORA if extratos_dir == config.EXTRATOS_DIR else extratos_dir / "Cora",
              "PagSeguro": config.DIR_PAGSEGURO if extratos_dir == config.EXTRATOS_DIR else extratos_dir / "PagSeguro",
              "MercadoPago": config.DIR_MERCADOPAGO if extratos_dir == config.EXTRATOS_DIR else extratos_dir / "MercadoPago"}
    if com_bradesco:
        bancos["Bradesco"] = config.DIR_BRADESCO if extratos_dir == config.EXTRATOS_DIR else extratos_dir / "Bradesco"

    partes, por_banco, arquivos, ignorados = [], {}, {}, []
    for banco, pasta in bancos.items():
        df, lidos, erros = processar_banco(banco, pasta)
        partes.append(df)
        por_banco[banco] = len(df)
        arquivos[banco] = len(lidos)
        ignorados.extend([f"{banco}/{e}" for e in erros])
    if com_pdf:
        pdfs = processar_pdfs_fallback(extratos_dir)
        partes.append(pdfs)
        por_banco["PDF_fallback"] = len(pdfs)

    base = pd.concat([p for p in partes if not p.empty], ignore_index=True) if partes else pd.DataFrame(
        columns=config.OUTPUT_COLUMNS)
    total_antes = len(base)
    if not base.empty:
        base = base.drop_duplicates(subset=["Data", "Lancamento", "Valor", "Banco", "Referencia"])
        base = base.sort_values(["Data", "Banco"]).reset_index(drop=True)
    dedup = total_antes - len(base)

    output_dir.mkdir(parents=True, exist_ok=True)
    consolidado_path = output_dir / config.OUTPUT_CONSOLIDADO.name
    calendario_path = output_dir / config.OUTPUT_CALENDARIO.name

    saida = base.copy()
    if not saida.empty:
        saida["Data"] = pd.to_datetime(saida["Data"]).dt.strftime("%d/%m/%Y")
        saida["Valor"] = saida["Valor"].map(lambda v: f"{v:.2f}")
    else:
        saida = pd.DataFrame(columns=config.OUTPUT_COLUMNS)
    saida.to_csv(consolidado_path, index=False, sep=";", encoding="utf-8")
    gerar_dcalendario().to_csv(calendario_path, index=False, sep=";", encoding="utf-8")

    return {
        "extratos_dir": str(extratos_dir),
        "output_dir": str(output_dir),
        "por_banco": por_banco,
        "arquivos_lidos": arquivos,
        "total_antes_dedup": total_antes,
        "dedup_removidas": dedup,
        "total_final": len(base),
        "ignorados": ignorados,
        "periodo": (str(base["Data"].min()), str(base["Data"].max())) if len(base) else (None, None),
        "consolidado": str(consolidado_path),
        "calendario": str(calendario_path),
    }
