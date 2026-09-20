"""Ponto de entrada CLI do pipeline.

Exemplos:
    python main.py
    python main.py --extratos "C:\\...\\Extratos" --saida "C:\\...\\ETL"
    python main.py --sem-bradesco
    python main.py --com-pdf
"""
import argparse
from pathlib import Path

from src import config
from src.etl import processar_tudo


def main() -> None:
    parser = argparse.ArgumentParser(description="Consolida extratos CSV para o Power BI.")
    parser.add_argument("--extratos", type=Path, default=config.EXTRATOS_DIR)
    parser.add_argument("--saida", type=Path, default=config.OUTPUT_DIR)
    parser.add_argument("--sem-bradesco", action="store_true",
                        help="Ignora a pasta Bradesco.")
    parser.add_argument("--com-pdf", action="store_true",
                        help="Ativa fallback de PDFs na raiz de Extratos.")
    args = parser.parse_args()

    stats = processar_tudo(
        extratos_dir=args.extratos,
        output_dir=args.saida,
        com_bradesco=(not args.sem_bradesco) and config.BRADESCO_ENABLED,
        com_pdf=args.com_pdf or config.PDF_FALLBACK_ENABLED,
    )
    print(f"Extratos : {stats['extratos_dir']}")
    print(f"Saida    : {stats['output_dir']}")
    print(f"Por banco: {stats['por_banco']} (arquivos: {stats['arquivos_lidos']})")
    print(f"Linhas   : {stats['total_antes_dedup']} -> {stats['total_final']} "
          f"(dedup: {stats['dedup_removidas']})")
    print(f"Periodo  : {stats['periodo'][0]} .. {stats['periodo'][1]}")
    print(f"Gerados  :\n  {stats['consolidado']}\n  {stats['calendario']}")


if __name__ == "__main__":
    main()
