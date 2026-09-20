# financial-data-pipeline

Pipeline ETL que consolida extratos CSV da tesouraria e gera os arquivos consumidos
pelo dashboard Power BI.

## Fluxo

```text
<pasta>\Financeiro\Extratos/
  ├── Cora/*.csv            (virgula, UTF-8)
  ├── PagSeguro/*.csv       (ponto-e-virgula, decimal com virgula)
  ├── MercadoPago/*.csv     (ponto-e-virgula, cabecalho RELEASE_DATE apos resumo)
  └── Bradesco/*.CSV        (ponto-e-virgula, latin1, skiprows=2) — opcional
        │
        ▼  python main.py  (ou notebook, ou run_etl.bat)
<pasta>\Financeiro\ETL/
  ├── Consolidado.csv       (Data;Lancamento;Transacao;Valor;TipoTransacao;Banco;TransferenciaInterna;ExcluirDoBalancete;Arquivo;Referencia;Favorecido)
  └── dCalendario.csv       (Data;Ano;MesNumero;Mes;AnoMes;Trimestre)
        │
        ▼  Atualizar no Power BI
<arquivo>.pbix
```

## Estrutura do repo

```text
├── src/
│   ├── config.py   # TODAS as variaveis de caminho/comportamento (sem hardcoded no resto do codigo)
│   └── etl.py      # parsers por banco + consolidacao + dCalendario
├── main.py                         # CLI: python main.py [--extratos DIR] [--saida DIR] [--sem-bradesco] [--com-pdf]
├── Extracao_Processamento_Dados_Bancarios.ipynb  # versao interativa (usa src/, sem "SEU PATH")
├── requirements.txt
├── .env.example    # copie para .env e ajuste os caminhos
├── run_etl.bat     # duplo-clique no Windows
```

## Configuracao (sem editar codigo)

Precedencia: **variavel de ambiente > `.env` > padrao local** em `src/config.py`.

| Variavel | Padrao | Para que serve |
|---|---|---|
| `EXTRATOS_DIR` | `.../Financeiro/Extratos` | pasta raiz dos extratos |
| `OUTPUT_DIR` | `.../Financeiro/ETL` | onde grava `Consolidado.csv` / `dCalendario.csv` |
| `DIR_CORA` / `DIR_PAGSEGURO` / `DIR_BRADESCO` / `DIR_MERCADOPAGO` | nome da subpasta | renomear subpastas se preciso |
| `BRADESCO_ENABLED` | `true` | `false` ignora o Bradesco (so ha arquivos ate 2024) |
| `PDF_FALLBACK_ENABLED` | `false` | `true` le tambem `*.pdf` avulsos na raiz de Extratos (formato antigo do Mercado Pago) |

Exemplo `.env`:

```ini
# .env (local, fora do git)
EXTRATOS_DIR=C:\Caminho\Para\Financeiro\Extratos
OUTPUT_DIR=C:\Caminho\Para\Financeiro\ETL
IGREJA_KEYWORDS=NOME DA ORGANIZACAO
BRADESCO_ENABLED=true
PDF_FALLBACK_ENABLED=false
```

## Como executar

```bash
pip install -r requirements.txt

# 1) padrao (usa .env ou pastas locais dados/)
python main.py

# 2) pastas alternativas (sem editar codigo)
python main.py --extratos "D:\backup\Extratos" --saida "D:\backup\ETL"

# 3) flags
python main.py --sem-bradesco
python main.py --com-pdf
```

No Windows, duplo-clique em `run_etl.bat`.

## Regras de negocio (iguais às do Power BI)

- Datas aceitas: `dd/MM/yyyy` e `dd-MM-yyyy`; valores BR (`1.580,51`, `-144,68`).
- `TipoTransacao` derivado do sinal (`>= 0` → `CRÉDITO`).
- Remove duplicados por `(Data, Lancamento, Valor, Banco)` — cobre meses re-exportados como `... v2.csv`.
- `TransferenciaInterna=SIM` para operações entre contas da própria organização (excluído das medidas do BI, mas visível no detalhe):
  `ENTRE CONTAS` no lançamento (ex.: "Transferência entre contas PagBank") →
  `RESERV*`/`PATRIMONIO` (ex.: "Dinheiro retirado Reserva", "Valor reservado") →
  nome da organização (`IGREJA_KEYWORDS` no `.env`, qualquer transação) →
  menções cruzadas Cora ↔ PagSeguro ↔ Mercado Pago.
  `ACAMPAMENTO` nunca é transferência interna (vai para `ExcluirDoBalancete`).
- `ExcluirDoBalancete=SIM` para lançamentos com `ACAMPAMENTO`.
- Mercado Pago: ignora `Saída de dinheiro` (movimentação interna de reserva).
- Saída em `;`, UTF-8, `Data` como `dd/MM/yyyy` e `Valor` com ponto (`1234.56`), formato esperado pela query `M_Consolidado_v2.m`.
- `Referencia`: ID da transação (`REFERENCE_ID` no MP, `CODIGO DA TRANSACAO` no PagSeguro, `Dcto.` no Bradesco; vazio na Cora). Evita que o Power BI some linhas distintas com mesma descrição.
- `Favorecido`: nome normalizado via `DePara_Nomes.csv` (ao lado do `Consolidado.csv`, editável em Excel, formato `Padrao;Variacao`). Une variações de caixa/acentuação (95 grupos automáticos), empresas com/sem LTDA e apelidos confirmados (ex.: `Damaris Santos` → `DAMARIS SANTANA DOS SANTOS`). `Lancamento` original é preservado para auditoria. Use `Favorecido` nos visuais por pessoa/empresa.
  > Privacidade: o `DePara_Nomes.csv` real contém nomes de pessoas e **não vai para o git** (`.gitignore`, LGPD). O repo leva apenas `data/DePara_Nomes.example.csv` com dados fictícios como modelo.

## Power BI

1. Execute o ETL (gera `ETL/Consolidado.csv` + `ETL/dCalendario.csv`).
2. Abra o `.pbix` do dashboard e clique em **Atualizar**.
3. Se mudar as pastas, ajuste `EXTRATOS_DIR`/`OUTPUT_DIR` no `.env` — o `.pbix` continua apontando para `ETL/Consolidado.csv`.
