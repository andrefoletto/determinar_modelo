# %% Celula 001 - Consolidar Jan..Dez/2025 (MMsmXXX.csv)

import re, calendar
from pathlib import Path
import numpy as np
import pandas as pd

BASE_DIR = Path(r"C:\GitHub\determinar_modelo")
ANO = 2025
FREQ = "15min"
FILL = 0.0

FNAME_RE = re.compile(r"^(at|re)(\d{2})(sm\d{3})([abc])\.csv$", re.IGNORECASE)

COL_ORDER = [
    ("at","a","P fase A"), ("at","b","P fase B"), ("at","c","P fase C"),
    ("re","a","Q fase A"), ("re","b","Q fase B"), ("re","c","Q fase C"),
]

def read_series(fp, name):
    df = pd.read_csv(fp)
    v = [c for c in df.columns if c != "Time"][0]
    df["Time"] = pd.to_datetime(df["Time"])
    df[v] = pd.to_numeric(df[v], errors="coerce")
    return df.set_index("Time")[v].rename(name)

def offset_h(ano, mes):
    return (pd.Timestamp(ano, mes, 1) - pd.Timestamp(ano, 1, 1)).total_seconds() / 3600.0

for MES in range(1, 13):
    MES2 = f"{MES:02d}"
    D = BASE_DIR / f"00 Memoria de massa {MES2} {ANO}"

    last = calendar.monthrange(ANO, MES)[1]
    idx = pd.date_range(pd.Timestamp(ANO, MES, 1, 0, 0), pd.Timestamp(ANO, MES, last, 23, 45), freq=FREQ)
    hdec = offset_h(ANO, MES) + np.arange(len(idx)) * 0.25

    meters = sorted({FNAME_RE.match(fp.name).group(3).lower()
                     for fp in D.glob("*.csv")
                     if FNAME_RE.match(fp.name) and FNAME_RE.match(fp.name).group(2) == MES2})

    for sm in meters:
        out = pd.DataFrame(index=idx)
        for tipo, fase, col in COL_ORDER:
            out[col] = read_series(D / f"{tipo}{MES2}{sm}{fase}.csv", col)
        out = out.fillna(FILL).reset_index(drop=True)
        out.insert(0, "Hora_decimal", hdec)
        out.to_csv(D / f"{MES2}{sm}.csv", index=False, sep=",", decimal=".", encoding="utf-8")

# %% Celula 002 - Emendar (01..12) em um CSV anual por medidor (2025), meses ausentes = zeros

import re
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(r"C:\GitHub\determinar_modelo")
ANO  = 2025

OUT  = BASE / f"01 Memoria de massa {ANO}"
OUT.mkdir(exist_ok=True)

COLS = ["P fase A","P fase B","P fase C","Q fase A","Q fase B","Q fase C"]
MONTH_RE = re.compile(r"^(\d{2})(sm\d{3})\.csv$", re.I)

# grade anual (2025 não bissexto): 0.00 .. 8759.75
n_year = 365 * 24 * 4
h_year = np.arange(n_year, dtype=float) * 0.25
year_index = pd.Index(h_year, name="Hora_decimal")

# descobre medidores (união dos meses)
meters = {
    m.group(2).lower()
    for mm in range(1, 13)
    for m in [MONTH_RE.match(fp.name) for fp in (BASE / f"00 Memoria de massa {mm:02d} {ANO}").glob("*.csv")]
    if m and m.group(1) == f"{mm:02d}"
}
meters = sorted(meters)

def read_month(fp: Path) -> pd.DataFrame:
    df = pd.read_csv(fp, usecols=["Hora_decimal"] + COLS)
    df["Hora_decimal"] = pd.to_numeric(df["Hora_decimal"], errors="coerce")
    df[COLS] = df[COLS].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    return df.dropna(subset=["Hora_decimal"]).set_index("Hora_decimal")[COLS]

for med in meters:
    out = pd.DataFrame(0.0, index=year_index, columns=COLS)

    for mm in range(1, 13):
        fp = BASE / f"00 Memoria de massa {mm:02d} {ANO}" / f"{mm:02d}{med}.csv"
        if fp.exists():
            dfm = read_month(fp)
            out.loc[out.index.intersection(dfm.index), COLS] = dfm.loc[out.index.intersection(dfm.index), COLS]

    out.reset_index().to_csv(OUT / f"{med}.csv", index=False, sep=",", decimal=".", encoding="utf-8")
    print(f"[OK] {med}.csv")

# %% Celula 003 - Gerar séries trifásicas (P e Q somadas) -> 3fsmXXX.csv

from pathlib import Path
import numpy as np
import pandas as pd

IN_DIR  = Path(r"C:\GitHub\determinar_modelo\01 Memoria de massa 2025")
OUT_DIR = Path(r"C:\GitHub\determinar_modelo\02 Memoria de massa trifasica 2025")
OUT_DIR.mkdir(exist_ok=True)

P = ["P fase A", "P fase B", "P fase C"]
Q = ["Q fase A", "Q fase B", "Q fase C"]

for fp in sorted(IN_DIR.glob("sm*.csv")):
    df = pd.read_csv(fp, usecols=["Hora_decimal"] + P + Q)
    df[P + Q] = df[P + Q].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    out = pd.DataFrame({
        "Hora_decimal": df["Hora_decimal"],
        "P_3f": df[P].sum(axis=1),
        "Q_3f": df[Q].sum(axis=1),
    })
    out.to_csv(OUT_DIR / f"3f{fp.name}", index=False, sep=",", decimal=".", encoding="utf-8")
    print(f"[OK] 3f{fp.name}")

# %% Celula 004 - Cortar P_3f negativa (exceto sm019 e sm027) e salvar como artefatos_

from pathlib import Path
import pandas as pd
import numpy as np
import re

IN_DIR  = Path(r"C:\GitHub\determinar_modelo\02 Memoria de massa trifasica 2025")
OUT_DIR = Path(r"C:\GitHub\determinar_modelo\03 Memoria de massa trifasica artefatos 2025")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Medidores com FV (podem ter P_3f negativa)
PV_OK = {"sm019", "sm027"}

# piso para potência ativa (kW)
P_MIN = 0

# Aceita "3fsmXXX.csv" (gerado na Celula 003)
RE_3F = re.compile(r"^3f(sm\d{3})\.csv$", re.IGNORECASE)

n_files = 0
n_edited = 0

for fp in sorted(IN_DIR.glob("3fsm*.csv")):
    m = RE_3F.match(fp.name)
    if not m:
        continue

    sm = m.group(1).lower()

    df = pd.read_csv(fp, usecols=["Hora_decimal", "P_3f", "Q_3f"])
    df["Hora_decimal"] = pd.to_numeric(df["Hora_decimal"], errors="coerce")
    df["P_3f"] = pd.to_numeric(df["P_3f"], errors="coerce").fillna(0.0)
    df["Q_3f"] = pd.to_numeric(df["Q_3f"], errors="coerce").fillna(0.0)

    if sm not in PV_OK:
        # corta negativos e substitui por 0 kW
        neg_mask = df["P_3f"] < 0
        if neg_mask.any():
            df.loc[neg_mask, "P_3f"] = P_MIN
            n_edited += 1

    out_name = f"artefatos_{fp.name}"  # inclui também sm019 e sm027 (apenas renomeia)
    df.to_csv(OUT_DIR / out_name, index=False, sep=",", decimal=".", encoding="utf-8")

    n_files += 1
    print(f"[OK] {fp.name} -> {out_name}  ({'PV' if sm in PV_OK else 'SEM_PV'})")

print(f"\nConcluído: {n_files} arquivos processados; {n_edited} arquivos com P_3f negativa corrigida.")

# %% Celula 005 - Apenas renomear e salvar em "04 Memoria de massa nomeada 2025"

from pathlib import Path
import pandas as pd

IN_DIR  = Path(r"C:\GitHub\determinar_modelo\03 Memoria de massa trifasica artefatos 2025")
OUT_DIR = Path(r"C:\GitHub\determinar_modelo\04 Memoria de massa nomeada 2025")
OUT_DIR.mkdir(exist_ok=True)

# MAPA DE NOMES (sem prefixo "interpolados_")
NAME_MAP = {
    "artefatos_3fsm003": "zeros_sm003_PQ_225QUIMICA_2025_225kVA",
    "artefatos_3fsm004": "zeros_sm004_PQ_1125POLI1_2025_112.5kVA",
    "artefatos_3fsm007": "zeros_sm007_PQ_225CCSHB_2025_225kVA",
    "artefatos_3fsm010": "zeros_sm010_PQ_225CCSHC2_2025_225kVA",
    "artefatos_3fsm011": "zeros_sm011_PQ_1125CE2_2025_112.5kVA",
    "artefatos_3fsm012": "zeros_sm012_PQ_150DENDROL_2025_150kVA",
    "artefatos_3fsm014": "zeros_sm014_PQ_225LSOLOS_2025_225kVA",
    "artefatos_3fsm016": "zeros_sm016_PQ_150ENGQUIM_2025_150kVA",
    "artefatos_3fsm019": "zeros_sm019_PQ_150INRI_2025_150kVA",
    "artefatos_3fsm021": "zeros_sm021_PQ_300CCR2_2025_300kVA",
    "artefatos_3fsm022": "zeros_sm022_PQ_225CTC_2025_225kVA",
    "artefatos_3fsm023": "zeros_sm023_PQ_225CCNE_2025_225kVA",
    "artefatos_3fsm024": "zeros_sm024_PQ_300CAL_2025_300kVA",
    "artefatos_3fsm025": "zeros_sm025_PQ_750INPE_2025_750kVA",
    "artefatos_3fsm027": "zeros_sm027_PQ_225CTISM2_2025_225kVA",
    "artefatos_3fsm029": "zeros_sm029_PQ_300CEU2C_2025_300kVA",
    "artefatos_3fsm032": "zeros_sm032_PQ_225CPD_2025_225kVA",
    "artefatos_3fsm033": "zeros_sm033_PQ_1125P21_2025_112.5kVA",
    "artefatos_3fsm035": "zeros_sm035_PQ_225FONO_2025_225kVA",
    "artefatos_3fsm036": "zeros_sm036_PQ_225RU2_2025_225kVA",
    "artefatos_3fsm037": "zeros_sm037_PQ_225CCSHC1_2025_225kVA",
    "artefatos_3fsm039": "zeros_sm039_PQ_300CEU2D_2025_300kVA",
    "artefatos_3fsm040": "zeros_sm040_PQ_300CEU2B_2025_300kVA",
    "artefatos_3fsm041": "zeros_sm041_PQ_225HIDR_2025_225kVA",
    "artefatos_3fsm042": "zeros_sm042_PQ_225CCSHA_2025_225kVA",
    "artefatos_3fsm043": "zeros_sm043_PQ_225PISCINAS_2025_225kVA",
    "artefatos_3fsm045": "zeros_sm045_PQ_300CTEC_2025_300kVA",
    "artefatos_3fsm046": "zeros_sm046_PQ_225CEFD_2025_225kVA",
    "artefatos_3fsm050": "zeros_sm050_PQ_500CONV1_2025_500kVA",
    "artefatos_3fsm051": "zeros_sm051_PQ_500P18_2025_500kVA",
    "artefatos_3fsm053": "zeros_sm053_PQ_225CE1_2025_225kVA",
    "artefatos_3fsm054": "zeros_sm054_PQ_500CONV2_2025_500kVA",
    "artefatos_3fsm055": "zeros_sm055_PQ_500REITORIA_2025_500kVA",
    "artefatos_3fsm056": "zeros_sm056_PQ_500P19_2025_500kVA",
    "artefatos_3fsm057": "zeros_sm057_PQ_500BIBC_2025_500kVA",
    "artefatos_3fsm058": "zeros_sm058_PQ_500ODONTO_2025_500kVA",
    "artefatos_3fsm059": "zeros_sm059_PQ_500CCR1_2025_500kVA",
    "artefatos_3fsm060": "zeros_sm060_PQ_500GRAFICA_2025_500kVA",
    "artefatos_3fsm136": "zeros_sm136_PQ_750RU_2025_750kVA",
}

for fp in sorted(IN_DIR.glob("artefatos_3fsm*.csv")):
    key = fp.stem
    if key not in NAME_MAP:
        continue

    df = pd.read_csv(fp, usecols=["Hora_decimal", "P_3f", "Q_3f"])
    out_fp = OUT_DIR / f"{NAME_MAP[key]}.csv"
    df.to_csv(out_fp, index=False, sep=",", decimal=".", encoding="utf-8")
    print(f"[OK] {out_fp.name}")

# %% Celula 006 - Contagem: Dias Completos / Incompletos / Sem Registro (simples)

from pathlib import Path
import pandas as pd

IN_DIR  = Path(r"C:\GitHub\determinar_modelo\04 Memoria de massa nomeada 2025")
OUT_DIR = Path(r"C:\GitHub\determinar_modelo\05 Resumo contagem dias 2025")
OUT_DIR.mkdir(exist_ok=True)

rows = []

for fp in sorted(IN_DIR.glob("zeros_sm*_PQ_*.csv")):
    df = pd.read_csv(fp, usecols=["Hora_decimal", "P_3f"])

    df["Dia"] = (df["Hora_decimal"] // 24).astype(int)  # 0..364
    g = df.groupby("Dia")["P_3f"]

    completos    = g.apply(lambda s: (s != 0).all()).sum()
    sem_registro = g.apply(lambda s: (s == 0).all()).sum()
    incompletos  = g.ngroups - completos - sem_registro

    rows.append({
        "Arquivo": fp.name,
        "Dias Completos": int(completos),
        "Dias Incompletos": int(incompletos),
        "Dias Sem Registro": int(sem_registro),
    })

df_out = pd.DataFrame(rows).sort_values("Arquivo")
out_fp = OUT_DIR / "resumo_status_dias.csv"
df_out.to_csv(out_fp, index=False, sep=",", decimal=".", encoding="utf-8")

print(f"[OK] {out_fp}")

# %% Celula 007 - Gráfico por arquivo (P_3f e Q_3f) e salvar PNG

from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt

IN_DIR  = Path(r"C:\GitHub\determinar_modelo\04 Memoria de massa nomeada 2025")
OUT_DIR = Path(r"C:\GitHub\determinar_modelo\06 Grafico memoria de massa nomeada 2025")
OUT_DIR.mkdir(exist_ok=True)

for fp in sorted(IN_DIR.glob("zeros_sm*_PQ_*.csv")):
    df = pd.read_csv(fp, usecols=["Hora_decimal", "P_3f", "Q_3f"])

    fig, ax = plt.subplots(figsize=(25, 5))
    ax.plot(df["Hora_decimal"], df["P_3f"], label="P_3f (kW)")
    ax.plot(df["Hora_decimal"], df["Q_3f"], label="Q_3f (kVAr)")

    ax.set_title(fp.stem)
    ax.set_xlabel("Hora_decimal (h)")
    ax.set_ylabel("Demanda")
    ax.grid(True, alpha=0.3)
    ax.legend()

    out_fp = OUT_DIR / f"{fp.stem}.png"
    fig.tight_layout()
    fig.savefig(out_fp, dpi=600)
    plt.close(fig)

    print(f"[OK] {out_fp.name}")

# %% Celula 008 - Grafico demanda ativa e reativa (RGE 15min 2025)

from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt

IN_FILE = Path(r"C:\GitHub\determinar_modelo\00_memoria_de_massa_RGE_15min_2025.csv")
OUT_DIR = Path(r"C:\GitHub\determinar_modelo\07 Grafico memoria de massa RGE 15min 2025")
OUT_DIR.mkdir(exist_ok=True)

# Leitura
df = pd.read_csv(IN_FILE, usecols=["Hora_decimal", "P_3f", "Q_3f"])

# Plot
fig, ax = plt.subplots(figsize=(25, 5))

ax.plot(df["Hora_decimal"], df["P_3f"], label="P_3f (kW)")
ax.plot(df["Hora_decimal"], df["Q_3f"], label="Q_3f (kVAr)")

ax.set_title("Memória de Massa RGE 2025 — 15 min")
ax.set_xlabel("Hora_decimal (h)")
ax.set_ylabel("Demanda")
ax.grid(True, alpha=0.3)
ax.legend()

# Salva
out_fp = OUT_DIR / "memoria_massa_RGE_15min_2025.png"
fig.tight_layout()
fig.savefig(out_fp, dpi=200)
plt.close(fig)

print(f"[OK] {out_fp}")

# %% Celula 009 - Contagem de desligamentos parcial (<800 kW) e total (=0)

from pathlib import Path
import pandas as pd

IN_FILE = Path(r"C:\GitHub\determinar_modelo\00_memoria_de_massa_RGE_15min_2025.csv")
OUT_DIR = Path(r"C:\GitHub\determinar_modelo\08 Resumo contagem desligamentos RGE 2025")
OUT_DIR.mkdir(exist_ok=True)

# Leitura
df = pd.read_csv(IN_FILE, usecols=["Hora_decimal", "P_3f"])

# Flags de desligamento
df["Desligamento_Total"]   = (df["P_3f"] == 0)
df["Desligamento_Parcial"] = (df["P_3f"] < 800) & (df["P_3f"] > 0)

# Função para extrair períodos contínuos
def extrair_periodos(mask, tipo):
    eventos = []
    em_evento = False
    inicio = None

    for hora, ativo in zip(df["Hora_decimal"], mask):
        if ativo and not em_evento:
            inicio = hora
            em_evento = True
        elif not ativo and em_evento:
            fim = hora - 0.25  # último ponto válido
            duracao = fim - inicio + 0.25
            eventos.append((tipo, inicio, fim, duracao))
            em_evento = False

    # Fecha evento se terminar no fim do arquivo
    if em_evento:
        fim = df["Hora_decimal"].iloc[-1]
        duracao = fim - inicio + 0.25
        eventos.append((tipo, inicio, fim, duracao))

    return eventos

# Extrai períodos
eventos = []
eventos += extrair_periodos(df["Desligamento_Total"], "TOTAL")
eventos += extrair_periodos(df["Desligamento_Parcial"], "PARCIAL")

# DataFrame de saída
df_out = pd.DataFrame(eventos, columns=[
    "Tipo_Desligamento",
    "Hora_Inicio",
    "Hora_Fim",
    "Duracao_h"
]).sort_values(["Tipo_Desligamento", "Hora_Inicio"])

# Salva
OUT_FILE = OUT_DIR / "resumo_periodos_desligamento_RGE_2025.csv"
df_out.to_csv(OUT_FILE, index=False, sep=",", decimal=".", encoding="utf-8")

print(f"[OK] {OUT_FILE}")
print(f"Eventos TOTAL: {(df_out['Tipo_Desligamento'] == 'TOTAL').sum()}")
print(f"Eventos PARCIAL: {(df_out['Tipo_Desligamento'] == 'PARCIAL').sum()}")

# %% Celula 010 - Zerar todos os medidores internos nos períodos de desligamento TOTAL da RGE (P_RGE == 0)
# Saída: cópias dos 39 CSVs com prefixo "desligamentos_" na pasta 09...

from pathlib import Path
import pandas as pd
import numpy as np

# ------------------ CAMINHOS ------------------
DIR_BASE = Path(r"C:\GitHub\determinar_modelo")

RGE_FILE = DIR_BASE / "00_memoria_de_massa_RGE_15min_2025.csv"
IN_DIR   = DIR_BASE / "04 Memoria de massa nomeada 2025"

OUT_DIR  = DIR_BASE / "09 Memoria de massa nomeada com desligamentos 2025"
OUT_DIR.mkdir(exist_ok=True)

# ------------------ PARAMETROS ------------------
DT_H = 0.25
P_ZERO_KW = 0.0   # desligamento TOTAL conforme RGE (estrito)

# ------------------ LEITURA RGE (BASE FIXA) ------------------
# A RGE define os instantes de desligamento total (P_3f == 0)
df_rge = pd.read_csv(RGE_FILE, encoding="latin-1", usecols=["Hora_decimal", "P_3f"])
df_rge = df_rge.sort_values("Hora_decimal").reset_index(drop=True)

# Conjunto de instantes (Hora_decimal) em que a RGE está zerada
horas_total_off = set(df_rge.loc[df_rge["P_3f"] == P_ZERO_KW, "Hora_decimal"].astype(float).tolist())

print(f"[INFO] Instantes RGE com desligamento TOTAL (P=0): {len(horas_total_off)} pontos de 15 min")

# ------------------ PROCESSA 39 MEDIDORES ------------------
files = sorted(IN_DIR.glob("zeros_sm*_PQ_*.csv"))
print(f"[INFO] Medidores encontrados: {len(files)}")

for fp in files:
    df = pd.read_csv(fp, usecols=["Hora_decimal", "P_3f", "Q_3f"])
    df = df.sort_values("Hora_decimal").reset_index(drop=True)

    # máscara: horas em que a RGE está desligada (total)
    mask_off = df["Hora_decimal"].astype(float).isin(horas_total_off)

    # zera P e Q nessas horas
    df.loc[mask_off, ["P_3f", "Q_3f"]] = 0.0

    out_fp = OUT_DIR / f"desligamentos_{fp.name}"
    df.to_csv(out_fp, index=False, sep=",", decimal=".", encoding="utf-8")

    print(f"[OK] {out_fp.name}")

# %% Celula 011 - Graficos dos medidores com desligamentos totais aplicados

from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt

DIR_BASE = Path(r"C:\GitHub\determinar_modelo")

IN_DIR  = DIR_BASE / "09 Memoria de massa nomeada com desligamentos 2025"
OUT_DIR = DIR_BASE / "10 Grafico memoria de massa nomeada com desligamentos 2025"
OUT_DIR.mkdir(exist_ok=True)

files = sorted(IN_DIR.glob("desligamentos_zeros_sm*_PQ_*.csv"))

print(f"[INFO] Arquivos encontrados: {len(files)}")

for fp in files:
    df = pd.read_csv(fp, usecols=["Hora_decimal", "P_3f", "Q_3f"])

    fig, ax = plt.subplots(figsize=(20, 5))

    ax.plot(df["Hora_decimal"], df["P_3f"], label="P_3f (kW)", linewidth=0.8)
    ax.plot(df["Hora_decimal"], df["Q_3f"], label="Q_3f (kVAr)", linewidth=0.8)

    ax.set_title(fp.stem)
    ax.set_xlabel("Hora_decimal (h)")
    ax.set_ylabel("Potência")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right")

    out_fp = OUT_DIR / f"{fp.stem}.png"
    fig.tight_layout()
    fig.savefig(out_fp, dpi=180)
    plt.close(fig)

    print(f"[OK] {out_fp.name}")

# %% Celula 012 - Mesclar Ano Letivo 2025 com as leituras (P e Q) - medidores com desligamentos aplicados
# Entrada:
#   C:\GitHub\determinar_modelo\09 Memoria de massa nomeada com desligamentos 2025
#   arquivos: desligamentos_zeros_smXXX_PQ_YYY_2025_ZZZkVA.csv
# Ano letivo:
#   C:\GitHub\determinar_modelo\00_dados_de_entrada_ano_letivo_2025_15min.csv
# Saída:
#   C:\GitHub\determinar_modelo\11 Memoria de massa nomeada com desligamentos com ano letivo 2025
#   prefixo: letivo_
#
# Observação:
# - Unir por Hora_decimal (medidor) = Hora_decimal (ano letivo)
# - Não manter colunas duplicadas no resultado final

from pathlib import Path
import pandas as pd

IN_DIR = Path(r"C:\GitHub\determinar_modelo\09 Memoria de massa nomeada com desligamentos 2025")
ANO_LETIVO_FP = Path(r"C:\GitHub\determinar_modelo\00_dados_de_entrada_ano_letivo_2025_15min.csv")

OUT_DIR = Path(r"C:\GitHub\determinar_modelo\11 Memoria de massa nomeada com desligamentos com ano letivo 2025")
OUT_DIR.mkdir(exist_ok=True)

# -------------------------
# 1) Carrega base do ano letivo
# -------------------------
ano = pd.read_csv(ANO_LETIVO_FP, low_memory=False)

# Cabeçalho esperado (conforme seu arquivo):
# Hora_decimal,Mes,Dia_semana,Aula,UFSM,Posto
req_cols = ["Hora_decimal", "Mes", "Dia_semana", "Aula", "UFSM", "Posto"]
for c in req_cols:
    if c not in ano.columns:
        raise RuntimeError(f"Coluna '{c}' não encontrada em: {ANO_LETIVO_FP}")

ano["Hora_decimal"] = pd.to_numeric(ano["Hora_decimal"], errors="coerce").round(2)
ano = ano.dropna(subset=["Hora_decimal"]).copy()

ano = ano[req_cols]
ano = ano.drop_duplicates(subset=["Hora_decimal"], keep="first").set_index("Hora_decimal")

# -------------------------
# 2) Varre arquivos e mescla
# -------------------------
for fp in sorted(IN_DIR.glob("desligamentos_zeros_sm*_PQ_*.csv")):
    df = pd.read_csv(fp)

    if "Hora_decimal" not in df.columns:
        print(f"[PULA] Sem 'Hora_decimal': {fp.name}")
        continue

    df["Hora_decimal"] = pd.to_numeric(df["Hora_decimal"], errors="coerce").round(2)
    df = df.dropna(subset=["Hora_decimal"]).copy()

    df = df.set_index("Hora_decimal")
    merged = df.join(ano, how="left").reset_index()

    out_fp = OUT_DIR / ("letivo_" + fp.name)
    merged.to_csv(out_fp, index=False, sep=",", decimal=".", encoding="utf-8")
    print(f"[OK] {out_fp.name}")

# %% Celula 013 - Preencher periodos faltantes por similaridade + fator RGE (base otimizada pela P_RGE)

from pathlib import Path
import pandas as pd
import numpy as np

DIR_BASE = Path(r"C:\GitHub\determinar_modelo")

IN_DIR  = DIR_BASE / "11 Memoria de massa nomeada com desligamentos com ano letivo 2025"
RGE_FP  = DIR_BASE / "00_memoria_de_massa_RGE_15min_2025.csv"

OUT_DIR = DIR_BASE / "12 Memoria de massa nomeada com desligamentos com ano letivo similaridade 2025"
OUT_DIR.mkdir(exist_ok=True)

DIAS_UTEIS = {"SEGUNDA", "TERCA", "QUARTA", "QUINTA", "SEXTA"}
FIM_SEMANA = {"SABADO", "DOMINGO"}
UFSM_ESPECIAL = "SEM_ATIV"

# ------------------ RGE ------------------
rge = pd.read_csv(RGE_FP, usecols=["Hora_decimal", "P_3f"])
rge["Hora_decimal"] = pd.to_numeric(rge["Hora_decimal"], errors="coerce").round(2)
rge = rge.dropna().drop_duplicates("Hora_decimal").set_index("Hora_decimal")["P_3f"]
rge.name = "P_RGE"

def norm_txt(s):
    return s.astype(str).str.strip().str.upper()

def grupo_similaridade(dia_semana, ufsm):
    d = str(dia_semana).strip().upper()
    u = str(ufsm).strip().upper()
    if u == UFSM_ESPECIAL:
        return "FIM_SEMANA"
    if d in DIAS_UTEIS:
        return "DIA_UTIL"
    if d in FIM_SEMANA:
        return "FIM_SEMANA"
    return "FIM_SEMANA"

def preencher(df_in):
    df = df_in.copy()

    df["Hora_decimal"] = pd.to_numeric(df["Hora_decimal"], errors="coerce").round(2)
    df["P_3f"] = pd.to_numeric(df["P_3f"], errors="coerce")
    df["Q_3f"] = pd.to_numeric(df["Q_3f"], errors="coerce")

    df["Dia_semana"] = norm_txt(df["Dia_semana"])
    df["UFSM"] = norm_txt(df["UFSM"])

    df = df.dropna(subset=["Hora_decimal"]).sort_values("Hora_decimal").drop_duplicates("Hora_decimal")

    df = df.set_index("Hora_decimal").join(rge, how="left").reset_index()

    df["TOD"] = (df["Hora_decimal"] % 24).round(2)
    df["GRUPO_SIM"] = [grupo_similaridade(d, u) for d, u in zip(df["Dia_semana"], df["UFSM"])]

    faltante = ((df["P_3f"].fillna(0.0) == 0.0) & (df["Q_3f"].fillna(0.0) == 0.0)) | df["P_3f"].isna() | df["Q_3f"].isna()
    rge_on = df["P_RGE"].fillna(0.0) > 0

    alvo_mask = faltante & rge_on
    base_mask = (~faltante) & rge_on

    cand = df.loc[base_mask, ["Hora_decimal", "GRUPO_SIM", "TOD", "P_3f", "Q_3f", "P_RGE"]].copy()

    grupos = {}
    for (g, tod), sub in cand.groupby(["GRUPO_SIM", "TOD"], sort=False):
        grupos[(g, float(tod))] = sub.reset_index(drop=True)

    preenchidos = 0

    for i in np.where(alvo_mask)[0]:
        g = df.at[i, "GRUPO_SIM"]
        tod = float(df.at[i, "TOD"])
        prge_alvo = df.at[i, "P_RGE"]

        key = (g, tod)
        if key not in grupos:
            continue

        base_df = grupos[key]

        # --- NOVO CRITÉRIO: base mais próxima em P_RGE ---
        diff_rge = (base_df["P_RGE"] - prge_alvo).abs()
        j = diff_rge.idxmin()

        prge_base = base_df.at[j, "P_RGE"]
        if prge_base == 0 or not np.isfinite(prge_base):
            continue

        fator = prge_alvo / prge_base

        df.at[i, "P_3f"] = base_df.at[j, "P_3f"] * fator
        df.at[i, "Q_3f"] = base_df.at[j, "Q_3f"] * fator

        preenchidos += 1

    df.drop(columns=["P_RGE", "TOD", "GRUPO_SIM"], inplace=True)

    print(f"    preenchidos: {preenchidos} pontos")
    return df

# ------------------ EXECUÇÃO ------------------
files = sorted(IN_DIR.glob("letivo_desligamentos_zeros_sm*_PQ_*.csv"))
print(f"[INFO] Arquivos encontrados: {len(files)}")

for fp in files:
    print(f"Processando: {fp.name}")
    df0 = pd.read_csv(fp)
    df1 = preencher(df0)

    out_fp = OUT_DIR / f"similaridade_{fp.name}"
    df1.to_csv(out_fp, index=False, sep=",", decimal=".", encoding="utf-8")
    print(f"[OK] {out_fp.name}")

print("Processamento concluído.")

# %% Celula 014 - Graficos (P e Q) dos medidores com similaridade + ajuste pela RGE (2025)

from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt

DIR_BASE = Path(r"C:\GitHub\determinar_modelo")

IN_DIR  = DIR_BASE / "12 Memoria de massa nomeada com desligamentos com ano letivo similaridade 2025"
OUT_DIR = DIR_BASE / "13 Grafico memoria de massa nomeada com desligamentos com ano letivo similaridade 2025"
OUT_DIR.mkdir(exist_ok=True)

files = sorted(IN_DIR.glob("similaridade_letivo_desligamentos_zeros_sm*_PQ_*.csv"))
print(f"[INFO] Arquivos encontrados: {len(files)}")

for fp in files:
    df = pd.read_csv(fp, usecols=["Hora_decimal", "P_3f", "Q_3f"])

    fig, ax = plt.subplots(figsize=(20, 5))
    ax.plot(df["Hora_decimal"], df["P_3f"], label="P_3f (kW)", linewidth=0.8)
    ax.plot(df["Hora_decimal"], df["Q_3f"], label="Q_3f (kVAr)", linewidth=0.8)

    ax.set_title(fp.stem)
    ax.set_xlabel("Hora_decimal (h)")
    ax.set_ylabel("Potência")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right")

    out_fp = OUT_DIR / f"{fp.stem}.png"
    fig.tight_layout()
    fig.savefig(out_fp, dpi=180)
    plt.close(fig)

    print(f"[OK] {out_fp.name}")

# %% Celula 015 - Preparar arquivos base (renomear, FILTRAR colunas e salvar)
# Lê:
#   ...\12 Memoria de massa nomeada com desligamentos com ano letivo similaridade 2025
# Arquivos:
#   similaridade_letivo_desligamentos_zeros_smXXX_PQ_YYY_2025_ZZZkVA.csv
# Salva em:
#   ...\14 Memoria de massa para simulacao I e base para nao medidos 2025
# Renomeia removendo o prefixo:
#   "similaridade_letivo_desligamentos_zeros_"
# Mantém APENAS:
#   Hora_decimal, P_3f, Q_3f
# Resultado:
#   smXXX_PQ_YYY_2025_ZZZkVA.csv

from pathlib import Path
import pandas as pd

DIR_BASE = Path(r"C:\GitHub\determinar_modelo")

IN_DIR  = DIR_BASE / "12 Memoria de massa nomeada com desligamentos com ano letivo similaridade 2025"
OUT_DIR = DIR_BASE / "14 Memoria de massa para simulacao I e base para nao medidos 2025"
OUT_DIR.mkdir(exist_ok=True)

PREFIXO = "similaridade_letivo_desligamentos_zeros_"
KEEP_COLS = ["Hora_decimal", "P_3f", "Q_3f"]

files = sorted(IN_DIR.glob(f"{PREFIXO}sm*_PQ_*.csv"))
print(f"[INFO] Arquivos encontrados: {len(files)}")

for fp in files:
    novo_nome = fp.name
    if novo_nome.startswith(PREFIXO):
        novo_nome = novo_nome[len(PREFIXO):]

    # lê só o necessário (mais rápido e evita levar colunas extras)
    df = pd.read_csv(fp, usecols=KEEP_COLS)

    out_fp = OUT_DIR / novo_nome
    df.to_csv(out_fp, index=False, sep=",", decimal=".", encoding="utf-8")

    print(f"[OK] {out_fp.name}")

# %% Celula 016 - Gerar curvas estimadas (ordem por dependencias: medidas -> estimadas base -> estimadas finais)
from pathlib import Path
from io import StringIO
import re
import pandas as pd

IN_DIR  = Path(r"C:\GitHub\determinar_modelo\14 Memoria de massa para simulacao I e base para nao medidos 2025")
OUT_DIR = Path(r"C:\GitHub\determinar_modelo\15 Memoria de massa estimada para simulacao I dos trafos nao medidos 2025")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# -----------------------------------------------------------------------------
# TABELA (como no PDF/tabela): Curvas_base em smXXX separados por "+"
# Observação: smXXX pode ser:
#   - curva medida (existe arquivo em IN_DIR)
#   - curva estimada (é um alvo "Curva" desta tabela; ex.: sm044, sm002, sm047...)
# O script resolve isso automaticamente e ordena a execução por dependências.
# -----------------------------------------------------------------------------
TABLE = r"""Curva,Fator_area,Fator_dens,Curvas_base
sm001_PQ_225DANCA_2025_225kVA,0.04,1.00,sm037+sm023+sm007+sm053+sm024+sm042+sm045+sm022+sm011+sm010+sm018
sm002_PQ_1125INDIGENA_2025_300kVA,0.08,1.86,sm029+sm039
sm005_PQ_150GEOMAT_2025_150kVA,0.09,1.11,sm046+sm035+sm004
sm006_PQ_1125NIDAL_2025_112.5kVA,0.10,1.00,sm014+sm003+sm012+sm048+sm009
sm008_PQ_1125NAPO1_2025_112.5kVA,0.60,1.18,sm033
sm009_PQ_75SOLOS_2025_75kVA,0.11,1.03,sm014+sm003+sm012
sm013_PQ_150POLI2_2025_150kVA,0.38,1.00,sm046+sm035+sm004+sm005
sm015_PQ_225BIOT_2025_225kVA,1.60,1.12,sm033
sm017_PQ_150CTISM1_2025_150kVA,0.81,1.20,sm027
sm018_PQ_150MUSICA_2025_150kVA,0.03,1.08,sm037+sm023+sm007+sm053+sm024+sm042+sm045+sm022+sm011+sm010
sm020_PQ_1125DESTIL_2025_112.5kVA,0.09,0.78,sm056+sm021+sm059+sm051+sm016
sm026_PQ_150TEROC_2025_150kVA,0.18,2.11,sm046+sm035+sm004+sm005
sm028_PQ_150TAMBO_2025_150kVA,0.07,1.17,sm056+sm021+sm059+sm051+sm016
sm030_PQ_300CEU2A_2025_300kVA,0.83,0.83,sm040
sm031_PQ_225AGITTEC_2025_225kVA,0.15,0.59,sm055
sm038_PQ_225HVU_2025_225kVA,1.33,0.95,sm058
sm044_PQ_300CEU2E_2025_300kVA,0.42,0.75,sm029+sm039
sm047_PQ_225REDEBIO_2025_225kVA,0.13,0.94,sm056+sm021+sm059+sm051+sm016
sm048_PQ_225CCS_2025_225kVA,0.72,0.84,sm014+sm003+sm012
sm132_PQ_1125PARQUE2_2025_112.5kVA,0.24,0.44,sm055
sm201_PQ_300CEU2F_2025_300kVA,0.22,1.00,sm029+sm039+sm044+sm002
sm202_PQ_225NUDEMA_2025_225kVA,0.04,1.00,sm056+sm021+sm059+sm051+sm016+sm047+sm020+sm028
sm203_PQ_150PARQUE3_2025_150kVA,0.02,1.00,sm056+sm021+sm059+sm051+sm016+sm047+sm020+sm028
sm204_PQ_1125BIOFLOR_2025_112.5kVA,0.03,1.00,sm056+sm021+sm059+sm051+sm016+sm047+sm020+sm028
sm205_PQ_1125PISCIC_2025_112.5kVA,0.03,1.00,sm056+sm021+sm059+sm051+sm016+sm047+sm020+sm028
sm206_PQ_1125USINALATIC_2025_112.5kVA,0.03,1.00,sm056+sm021+sm059+sm051+sm016+sm047+sm020+sm028
sm207_PQ_1125ZOOTEC_2025_112.5kVA,0.04,1.00,sm056+sm021+sm059+sm051+sm016+sm047+sm020+sm028
sm208_PQ_500P17_2025_500kVA,0.31,1.00,sm014+sm003+sm012+sm048+sm009
sm209_PQ_150LARP_2025_150kVA,0.16,1.00,sm014+sm003+sm012+sm048+sm009
sm210_PQ_150BIOEQ_2025_150kVA,0.19,1.00,sm033+sm015+sm008
sm211_PQ_150QPETR_2025_150kVA,0.31,1.00,sm033+sm015+sm008
sm212_PQ_225NAPO2_2025_225kVA,0.41,1.00,sm033+sm015+sm008
sm213_PQ_300BIOINS_2025_300kVA,0.38,1.00,sm033+sm015+sm008
sm214_PQ_75ENATURAL_2025_75kVA,0.16,1.00,sm033+sm015+sm008
sm215_PQ_500PAVCT_2025_500kVA,8.57,1.00,sm041
sm216_PQ_75CEEMA_2025_75kVA,0.36,1.00,sm041
sm217_PQ_150HANGAR_2025_150kVA,0.79,1.00,sm041
sm218_PQ_150LMCC_2025_150kVA,0.71,1.00,sm041
sm219_PQ_225LMOT_2025_225kVA,0.67,1.00,sm019
sm220_PQ_225ARQUIT_2025_225kVA,0.05,1.00,sm037+sm023+sm007+sm053+sm024+sm042+sm045+sm022+sm011+sm010+sm018
sm221_PQ_150AVIARIO1_2025_150kVA,0.11,1.00,sm037+sm023+sm007+sm053+sm024+sm042+sm045+sm022+sm011+sm010+sm018
sm222_PQ_1125LETRAS_2025_112.5kVA,0.35,1.00,sm046+sm035+sm004+sm005
sm223_PQ_1125POLI3_2025_112.5kVA,0.24,1.00,sm046+sm035+sm004+sm005
sm224_PQ_150MEDIC_2025_150kVA,0.14,1.00,sm046+sm035+sm004+sm005
sm225_PQ_150MUSEU_2025_150kVA,0.25,0.59,sm055
sm226_PQ_225ACESS_2025_225kVA,0.20,0.59,sm055
sm227_PQ_75BOT1_2025_75kVA,0.08,0.59,sm055
sm228_PQ_75BOT2_2025_75kVA,0.08,0.59,sm055
sm229_PQ_1125FATEC_2025_112.5kVA,0.18,1.00,sm055
sm230_PQ_150INCUB_2025_150kVA,0.20,1.00,sm055
sm231_PQ_225COMUN_2025_225kVA,0.30,1.00,sm055
sm232_PQ_225DERCA_2025_225kVA,0.37,1.00,sm055
sm233_PQ_75NTE_2025_75kVA,0.10,1.00,sm055
sm234_PQ_150PARQUE1_2025_150kVA,0.30,0.59,sm055
sm235_PQ_225PLANET_2025_225kVA,0.09,2.11,sm046+sm035+sm004+sm005
sm236_PQ_45REMATE_2025_45kVA,0.06,0.59,sm055
sm237_PQ_75ECUMENICO_2025_75kVA,0.06,2.56,sm055
sm238_PQ_45CETAS_2025_45kVA,0.05,1.00,sm058+sm038
sm239_PQ_225BANCOS_2025_225kVA,0.15,2.56,sm055
sm240_PQ_225MAN_2025_225kVA,0.68,0.59,sm055
sm241_PQ_150ALMOX_2025_150kVA,0.15,0.59,sm055
sm242_PQ_75RESIDUOS_2025_75kVA,0.10,0.59,sm055
sm243_PQ_75RACOES_2025_75kVA,0.02,1.00,sm056+sm021+sm059+sm051+sm016+sm047+sm020+sm028
sm244_PQ_75COXILHA_2025_75kVA,0.04,1.00,sm014+sm003+sm012+sm048+sm009
sm245_PQ_75GALPAO_2025_75kVA,0.08,1.00,sm014+sm003+sm012+sm048+sm009
sm246_PQ_75MADAME_2025_75kVA,0.03,1.00,sm014+sm003+sm012+sm048+sm009
sm247_PQ_75POMAR_2025_75kVA,0.03,1.00,sm014+sm003+sm012+sm048+sm009
sm248_PQ_75SUINOC_2025_75kVA,0.03,1.00,sm056+sm021+sm059+sm051+sm016+sm047+sm020+sm028
sm249_PQ_45AVIARIO2_2025_45kVA,0.02,1.00,sm056+sm021+sm059+sm051+sm016+sm047+sm020+sm028
"""

spec = pd.read_csv(StringIO(TABLE))

NEEDED_COLS = {"Curva", "Fator_area", "Fator_dens", "Curvas_base"}
missing = [c for c in sorted(NEEDED_COLS) if c not in spec.columns]
if missing:
    raise ValueError(f"Tabela (TABLE) sem colunas obrigatórias: {missing}. Encontradas: {list(spec.columns)}")

# -----------------------------------------------------------------------------
# 1) Indexar curvas MEDIDAS disponíveis (somente arquivos que existem em IN_DIR)
# -----------------------------------------------------------------------------
measured_files = sorted(IN_DIR.glob("sm*_PQ_*_2025_*kVA.csv"))
if not measured_files:
    raise FileNotFoundError(f"Nenhum arquivo 'sm*_PQ_*_2025_*kVA.csv' encontrado em: {IN_DIR}")

# mapa: "sm040" -> "sm040_PQ_300CEU2B_2025_300kVA" (stem)
measured_map = {}
for fp in measured_files:
    m = re.match(r"^(sm\d{3})_", fp.stem, flags=re.IGNORECASE)
    if m:
        measured_map[m.group(1).lower()] = fp.stem

# -----------------------------------------------------------------------------
# 2) Indexar alvos estimados desta tabela (para resolver bases do tipo sm044, sm002 etc.)
# -----------------------------------------------------------------------------
target_map = {}  # "sm044" -> "sm044_PQ_..."
for curve in spec["Curva"].astype(str):
    m = re.match(r"^(sm\d{3})_", curve.strip(), flags=re.IGNORECASE)
    if m:
        target_map[m.group(1).lower()] = curve.strip()

def read_curve_csv(stem: str) -> pd.DataFrame:
    f = IN_DIR / f"{stem}.csv"
    if not f.exists():
        raise FileNotFoundError(f"Arquivo base não encontrado: {f}")

    df = pd.read_csv(f)
    needed = {"Hora_decimal", "P_3f", "Q_3f"}
    if not needed.issubset(df.columns):
        raise ValueError(
            f"Arquivo {f.name} não possui colunas {needed}. "
            f"Colunas encontradas: {list(df.columns)}"
        )

    df = df[["Hora_decimal", "P_3f", "Q_3f"]].copy()
    df["Hora_decimal"] = pd.to_numeric(df["Hora_decimal"], errors="raise")
    df["P_3f"] = pd.to_numeric(df["P_3f"], errors="coerce").fillna(0.0)
    df["Q_3f"] = pd.to_numeric(df["Q_3f"], errors="coerce").fillna(0.0)
    return df

def resolve_base_token(token: str) -> tuple[str, str]:
    """
    Retorna (kind, name):
      - kind="measured", name=stem do arquivo medido (existente em IN_DIR)
      - kind="estimated", name=Curva (alvo) que será/foi gerada neste script
    token esperado: "sm040", "sm044", "sm002", ...
    """
    t = token.strip().lower()

    if t in measured_map:
        return ("measured", measured_map[t])

    if t in target_map:
        return ("estimated", target_map[t])

    raise KeyError(
        f"Base '{token}' não resolvida: não existe como medida em IN_DIR e não é alvo desta tabela.\n"
        f" - medidas conhecidas (exemplos): {list(measured_map.keys())[:10]}...\n"
        f" - alvos estimados (exemplos): {list(target_map.keys())[:10]}..."
    )

def build_target(target_curve: str, factor_area: float, factor_dens: float, base_tokens: list[str],
                 built_cache: dict[str, pd.DataFrame]) -> pd.DataFrame:
    dfs = []
    for tok in base_tokens:
        kind, name = resolve_base_token(tok)
        if kind == "measured":
            dfs.append(read_curve_csv(name))
        else:
            # estimated: precisa existir no cache (já gerado)
            if name not in built_cache:
                raise RuntimeError(f"Dependência ainda não gerada: base '{tok}' -> '{name}' para alvo '{target_curve}'")
            dfs.append(built_cache[name])

    base0 = dfs[0].set_index("Hora_decimal")
    sum_p = base0["P_3f"].copy()
    sum_q = base0["Q_3f"].copy()

    for d in dfs[1:]:
        di = d.set_index("Hora_decimal").reindex(sum_p.index)
        sum_p = sum_p + di["P_3f"].fillna(0.0)
        sum_q = sum_q + di["Q_3f"].fillna(0.0)

    scale = float(factor_area) * float(factor_dens)

    out = pd.DataFrame({
        "Hora_decimal": sum_p.index.values,
        "P_3f": (sum_p.values * scale),
        "Q_3f": (sum_q.values * scale),
    })

    if len(out) != 35040:
        print(f"[AVISO] {target_curve}: comprimento = {len(out)} (esperado 35040).")

    return out

# -----------------------------------------------------------------------------
# 3) Ordenação por dependências (topological-like):
#    - executa em "camadas": primeiro quem depende só de medidas,
#      depois quem depende das estimadas já criadas, etc.
# -----------------------------------------------------------------------------
rows = []
for _, r in spec.iterrows():
    target = str(r["Curva"]).strip()
    fa = float(r["Fator_area"])
    fd = float(r["Fator_dens"])
    bases = [b.strip() for b in str(r["Curvas_base"]).split("+") if b.strip()]
    if not bases:
        raise ValueError(f"Curvas_base vazio para {target}")
    rows.append((target, fa, fd, bases))

pending = rows[:]
built_cache: dict[str, pd.DataFrame] = {}
built_order: list[str] = []

stage = 0
while pending:
    stage += 1
    progressed = 0
    still_pending = []

    for (target, fa, fd, bases) in pending:
        # checa se todas as bases já são resolvíveis:
        ok = True
        for tok in bases:
            kind, name = resolve_base_token(tok)
            if kind == "estimated" and name not in built_cache:
                ok = False
                break

        if not ok:
            still_pending.append((target, fa, fd, bases))
            continue

        # gera
        df_out = build_target(target, fa, fd, bases, built_cache)
        built_cache[target] = df_out
        df_out.to_csv(OUT_DIR / f"{target}.csv", index=False)

        built_order.append(target)
        progressed += 1

    print(f"[ETAPA {stage}] Geradas {progressed} curvas estimadas.")
    if progressed == 0:
        # Diagnóstico: listar as primeiras pendências e o que falta
        msg = ["Não foi possível avançar: há dependências faltando ou ciclo.\n"]
        for (target, _, _, bases) in still_pending[:10]:
            faltas = []
            for tok in bases:
                kind, name = resolve_base_token(tok)
                if kind == "estimated" and name not in built_cache:
                    faltas.append(f"{tok}->{name}")
            msg.append(f" - {target} depende de: {', '.join(faltas)}")
        raise RuntimeError("\n".join(msg))

    pending = still_pending

print(f"Concluído: {len(built_order)} curvas estimadas geradas em:\n{OUT_DIR}")
print("Ordem de geração (primeiras 20):")
print("\n".join(built_order[:20]))

# %% Celula 017 - Graficos das curvas ESTIMADAS (P e Q) - trafos nao medidos (Simulacao I)

from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt

IN_DIR  = Path(r"C:\GitHub\determinar_modelo\15 Memoria de massa estimada para simulacao I dos trafos nao medidos 2025")
OUT_DIR = Path(r"C:\GitHub\determinar_modelo\16 Grafico memoria de massa estimada para simulacao I dos trafos nao medidos 2025")
OUT_DIR.mkdir(parents=True, exist_ok=True)

files = sorted(IN_DIR.glob("sm*_PQ_*.csv"))
print(f"[INFO] Arquivos encontrados: {len(files)}")

for fp in files:
    df = pd.read_csv(fp, usecols=["Hora_decimal", "P_3f", "Q_3f"])

    fig, ax = plt.subplots(figsize=(20, 5))
    ax.plot(df["Hora_decimal"], df["P_3f"], label="P_3f (kW)", linewidth=0.8)
    ax.plot(df["Hora_decimal"], df["Q_3f"], label="Q_3f (kVAr)", linewidth=0.8)

    ax.set_title(fp.stem)
    ax.set_xlabel("Hora_decimal (h)")
    ax.set_ylabel("Potência")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right")

    out_fp = OUT_DIR / f"{fp.stem}.png"
    fig.tight_layout()
    fig.savefig(out_fp, dpi=180)
    plt.close(fig)

    print(f"[OK] {out_fp.name}")

print("Concluído.")

# %% Celula 018 - Gerar e salvar mascara de desligamento total (RGE)
# Saída:
#   C:\GitHub\determinar_modelo\01_mascara_apagao_RGE_2025.csv
#
# Critério:
#   apagao_total = 1 quando |P_3f| <= EPS (default EPS=1e-9)

from pathlib import Path
import numpy as np
import pandas as pd

DIR_BASE = Path(r"C:\GitHub\determinar_modelo")
RGE_FP   = DIR_BASE / "00_memoria_de_massa_RGE_15min_2025.csv"
OUT_FP   = DIR_BASE / "01_mascara_apagao_RGE_2025.csv"

EPS = 1e-9  # tolerância para "zero" (evita problemas com float)

rge = pd.read_csv(RGE_FP)

# Validar colunas mínimas
need_cols = {"Hora_decimal", "P_3f"}
missing = need_cols - set(rge.columns)
if missing:
    raise ValueError(f"Arquivo RGE sem colunas necessárias {missing}. Encontradas: {list(rge.columns)}")

rge = rge[["Hora_decimal", "P_3f"]].copy()
rge["Hora_decimal"] = pd.to_numeric(rge["Hora_decimal"], errors="coerce")
rge["P_3f"]         = pd.to_numeric(rge["P_3f"], errors="coerce").fillna(0.0)

# Limpeza e unicidade
rge = (
    rge.dropna(subset=["Hora_decimal"])
       .drop_duplicates(subset=["Hora_decimal"], keep="last")
       .sort_values("Hora_decimal")
)

# Máscara (1 = apagão total)
rge["apagao_total"] = (rge["P_3f"].abs() <= EPS).astype(int)

mask_out = rge[["Hora_decimal", "apagao_total"]]
mask_out.to_csv(OUT_FP, index=False, encoding="utf-8")

print(f"[OK] Mascara salva: {OUT_FP}")
print(f"Total pontos apagão: {int(mask_out['apagao_total'].sum())} / {len(mask_out)}")

# %% Celula 019 - Funções utilitárias: carregar mascara e aplicar apagão
# Uso:
#   mascara_zero = carregar_mascara_apagao(hora_decimal)
#   P, Q = aplicar_apagao(P, Q, mascara_zero)

from pathlib import Path
import numpy as np
import pandas as pd

DIR_BASE    = Path(r"C:\GitHub\determinar_modelo")
ARQ_MASCARA = DIR_BASE / "01_mascara_apagao_RGE_2025.csv"


def carregar_mascara_apagao(hora_decimal: np.ndarray, arq_mascara: Path = ARQ_MASCARA) -> np.ndarray:
    """
    Retorna um array booleano (mesmo tamanho de hora_decimal) com True onde apagao_total == 1.
    Alinha por Hora_decimal (reindex). Valores faltantes => 0 (sem apagão).
    """
    mascara_df = pd.read_csv(arq_mascara)

    colunas_necessarias = {"Hora_decimal", "apagao_total"}
    faltantes = colunas_necessarias - set(mascara_df.columns)
    if faltantes:
        raise ValueError(
            f"Máscara sem colunas necessárias {faltantes}. "
            f"Encontradas: {list(mascara_df.columns)}"
        )

    mascara_df = mascara_df[["Hora_decimal", "apagao_total"]].copy()
    mascara_df["Hora_decimal"] = pd.to_numeric(mascara_df["Hora_decimal"], errors="coerce")
    mascara_df["apagao_total"] = (
        pd.to_numeric(mascara_df["apagao_total"], errors="coerce")
        .fillna(0)
        .astype(int)
    )

    mascara_df = (
        mascara_df.dropna(subset=["Hora_decimal"])
        .drop_duplicates(subset=["Hora_decimal"], keep="last")
        .set_index("Hora_decimal")
        .sort_index()
    )

    mascara_alinhada = (
        mascara_df["apagao_total"]
        .reindex(hora_decimal)
        .fillna(0)
        .to_numpy()
        .astype(bool)
    )

    return mascara_alinhada


def aplicar_apagao(P: np.ndarray, Q: np.ndarray, mascara_zero: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Zera P e Q onde mascara_zero é True. Retorna (P, Q).
    """
    if P.shape != Q.shape or P.shape != mascara_zero.shape:
        raise ValueError(
            f"Shapes incompatíveis: P{P.shape}, Q{Q.shape}, mascara{mascara_zero.shape}"
        )

    P[mascara_zero] = 0.0
    Q[mascara_zero] = 0.0
    return P, Q


print("[OK] Funções utilitárias carregadas: carregar_mascara_apagao(), aplicar_apagao()")

# %% Celula 020 - Gerar curvas dos carregadores VE (sm254 e sm255) para 2025 (15 min) + zerar em apagão RGE
# Saída:
#   17 Memoria de massa estimada carregadores VE para simulacao 2025\sm254_PQ_75VE1_2025_75kVA.csv
#   17 Memoria de massa estimada carregadores VE para simulacao 2025\sm255_PQ_75VE2_2025_75kVA.csv

from pathlib import Path
import numpy as np
import pandas as pd

DIR_SAIDA = Path(r"C:\GitHub\determinar_modelo\17 Memoria de massa estimada carregadores VE para simulacao 2025")
DIR_SAIDA.mkdir(parents=True, exist_ok=True)

ARQS_SAIDA = [
    DIR_SAIDA / "sm254_PQ_75VE1_2025_75kVA.csv",
    DIR_SAIDA / "sm255_PQ_75VE2_2025_75kVA.csv",
]

# ------------------------
# Parâmetros
# ------------------------
FP = 0.98
N_DIAS = 365
PTS_DIA = 96
DT_H = 0.25

INICIOS = [32, 42, 52, 62]  # 08:00, 10:30, 13:00, 15:30
PERFIL_P = np.array([60, 55, 35, 20, 15, 10, 5], dtype=float)  # kW (7 passos)
ENERGIA_SESSAO_KWH = PERFIL_P.sum() * DT_H
if abs(ENERGIA_SESSAO_KWH - 50.0) > 1e-6:
    raise ValueError(f"Perfil não fecha 50 kWh. Energia por sessão = {ENERGIA_SESSAO_KWH:.3f} kWh")

tan_phi = np.tan(np.arccos(FP))

# ------------------------
# Série anual
# ------------------------
N = N_DIAS * PTS_DIA
hora_decimal = np.arange(N, dtype=float) * DT_H

P = np.zeros(N, dtype=float)
for d in range(N_DIAS):
    base = d * PTS_DIA
    for s in INICIOS:
        i0 = base + s
        i1 = i0 + len(PERFIL_P)
        P[i0:i1] += PERFIL_P

Q = P * tan_phi

# ------------------------
# Zerar em apagão total RGE
# ------------------------
mascara_zero = carregar_mascara_apagao(hora_decimal)
P, Q = aplicar_apagao(P, Q, mascara_zero)

df = pd.DataFrame({"Hora_decimal": hora_decimal, "P_3f": P, "Q_3f": Q})

for arq in ARQS_SAIDA:
    df.to_csv(arq, index=False, encoding="utf-8")

print("[OK] Celula 020 concluída.")
print(f"Arquivos:\n- {ARQS_SAIDA[0]}\n- {ARQS_SAIDA[1]}")
print(f"FP={FP:.3f} -> tan(phi)={tan_phi:.6f} | Energia/sessão={ENERGIA_SESSAO_KWH:.1f} kWh | Dias={N_DIAS}")
print(f"Pontos zerados por apagão: {int(mascara_zero.sum())}")

# %% Celula 021 - Gerar curvas dos poços (sm253 e sm252) + zerar em apagão RGE
# Saída:
#   18 Memoria de massa estimada pocos para simulacao 2025\sm253_PQ_30POCO1_2025_30kVA.csv
#   18 Memoria de massa estimada pocos para simulacao 2025\sm252_PQ_45POCO2_2025_45kVA.csv

from pathlib import Path
import numpy as np
import pandas as pd

DIR_SAIDA = Path(r"C:\GitHub\determinar_modelo\18 Memoria de massa estimada pocos para simulacao 2025")
DIR_SAIDA.mkdir(parents=True, exist_ok=True)

ARQ_POCO1 = DIR_SAIDA / "sm253_PQ_30POCO1_2025_30kVA.csv"
ARQ_POCO2 = DIR_SAIDA / "sm252_PQ_45POCO2_2025_45kVA.csv"

# ------------------------
# Parâmetros
# ------------------------
FP = 0.85
N_DIAS = 365
PTS_DIA = 96
DT_H = 0.25

S1_KVA = 20.0  # Poço 1
S2_KVA = 30.0  # Poço 2
DESLOC_MIN = 30
DESLOC_PASSOS = int(DESLOC_MIN / 15)  # 2 passos

phi = np.arccos(FP)
sin_phi = np.sin(phi)

P1_LIGADO = S1_KVA * FP
Q1_LIGADO = S1_KVA * sin_phi

P2_LIGADO = S2_KVA * FP
Q2_LIGADO = S2_KVA * sin_phi

IDX_08 = 8 * 4
IDX_18 = 18 * 4


def construir_mascara_dia_ligado_desligado() -> np.ndarray:
    """
    96 pontos (15 min).
    00-08: 1h ON / 3h OFF  (ciclo 16, ON 4)
    08-18: 1h ON / 1h OFF  (ciclo 8,  ON 4)
    18-24: 1h ON / 3h OFF  (ciclo 16, ON 4)
    """
    m = np.zeros(PTS_DIA, dtype=bool)

    for k in range(0, IDX_08, 16):
        m[k:k+4] = True
    for k in range(IDX_08, IDX_18, 8):
        m[k:k+4] = True
    for k in range(IDX_18, PTS_DIA, 16):
        m[k:k+4] = True

    return m


mascara_dia = construir_mascara_dia_ligado_desligado()

# ------------------------
# Série anual
# ------------------------
N = N_DIAS * PTS_DIA
hora_decimal = np.arange(N, dtype=float) * DT_H

P1 = np.zeros(N, dtype=float)
Q1 = np.zeros(N, dtype=float)
P2 = np.zeros(N, dtype=float)
Q2 = np.zeros(N, dtype=float)

for d in range(N_DIAS):
    base = d * PTS_DIA

    m1 = mascara_dia
    m2 = np.roll(mascara_dia, DESLOC_PASSOS)

    P1[base:base+PTS_DIA] = np.where(m1, P1_LIGADO, 0.0)
    Q1[base:base+PTS_DIA] = np.where(m1, Q1_LIGADO, 0.0)

    P2[base:base+PTS_DIA] = np.where(m2, P2_LIGADO, 0.0)
    Q2[base:base+PTS_DIA] = np.where(m2, Q2_LIGADO, 0.0)

# ------------------------
# Zerar em apagão total RGE
# ------------------------
mascara_zero = carregar_mascara_apagao(hora_decimal)
P1, Q1 = aplicar_apagao(P1, Q1, mascara_zero)
P2, Q2 = aplicar_apagao(P2, Q2, mascara_zero)

df1 = pd.DataFrame({"Hora_decimal": hora_decimal, "P_3f": P1, "Q_3f": Q1})
df2 = pd.DataFrame({"Hora_decimal": hora_decimal, "P_3f": P2, "Q_3f": Q2})

df1.to_csv(ARQ_POCO1, index=False, encoding="utf-8")
df2.to_csv(ARQ_POCO2, index=False, encoding="utf-8")

print("[OK] Celula 021 concluída.")
print(f"Arquivos:\n- {ARQ_POCO1}\n- {ARQ_POCO2}")
print(f"Poço 2 deslocado: +{DESLOC_MIN} min ({DESLOC_PASSOS} passos)")
print(f"Pontos zerados por apagão: {int(mascara_zero.sum())}")

# %% Celula 022 - Curvas das bombas de irrigação (sm256 e sm257) + zerar em apagão RGE
# Saída:
#   19 Memoria de massa estimada irrigacao para simulacao 2025\sm256_PQ_45IRRIGA_2025_45kVA.csv
#   19 Memoria de massa estimada irrigacao para simulacao 2025\sm257_PQ_45PIVO_2025_45kVA.csv

from pathlib import Path
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

DIR_SAIDA = Path(r"C:\GitHub\determinar_modelo\19 Memoria de massa estimada irrigacao para simulacao 2025")
DIR_SAIDA.mkdir(parents=True, exist_ok=True)

ARQ_1 = DIR_SAIDA / "sm256_PQ_45IRRIGA_2025_45kVA.csv"
ARQ_2 = DIR_SAIDA / "sm257_PQ_45PIVO_2025_45kVA.csv"

# ------------------------
# Parâmetros
# ------------------------
ANO = 2025
FP = 0.85
S_KVA = 30.0

PTS_DIA = 96
DT_MIN = 15
DT_H = 0.25
N_DIAS = 365
N = N_DIAS * PTS_DIA

MESES_ATIVOS = {10, 11, 12, 1, 2, 3}  # outubro..março

# Ciclo 6h ON / 6h OFF (12h)
PASSOS_LIGADO = int((6 * 60) / DT_MIN)       # 24
PASSOS_CICLO  = int((12 * 60) / DT_MIN)      # 48
DESLOC_HORAS  = 3
DESLOC_PASSOS = int((DESLOC_HORAS * 60) / DT_MIN)  # 12

phi = np.arccos(FP)
sin_phi = np.sin(phi)

P_LIGADO = S_KVA * FP
Q_LIGADO = S_KVA * sin_phi

# Máscara diária base (bomba 1): começa ligada no início do dia
mascara_dia = np.zeros(PTS_DIA, dtype=bool)
for k in range(0, PTS_DIA, PASSOS_CICLO):
    mascara_dia[k:k+PASSOS_LIGADO] = True

mascara_dia_deslocada = np.roll(mascara_dia, DESLOC_PASSOS)

# ------------------------
# Série anual
# ------------------------
hora_decimal = np.arange(N, dtype=float) * DT_H

P1 = np.zeros(N, dtype=float)
Q1 = np.zeros(N, dtype=float)
P2 = np.zeros(N, dtype=float)
Q2 = np.zeros(N, dtype=float)

data_inicio = datetime(ANO, 1, 1)

for d in range(N_DIAS):
    dia = data_inicio + timedelta(days=d)
    base = d * PTS_DIA

    if dia.month in MESES_ATIVOS:
        P1[base:base+PTS_DIA] = np.where(mascara_dia, P_LIGADO, 0.0)
        Q1[base:base+PTS_DIA] = np.where(mascara_dia, Q_LIGADO, 0.0)

        P2[base:base+PTS_DIA] = np.where(mascara_dia_deslocada, P_LIGADO, 0.0)
        Q2[base:base+PTS_DIA] = np.where(mascara_dia_deslocada, Q_LIGADO, 0.0)

# ------------------------
# Zerar em apagão total RGE
# ------------------------
mascara_zero = carregar_mascara_apagao(hora_decimal)
P1, Q1 = aplicar_apagao(P1, Q1, mascara_zero)
P2, Q2 = aplicar_apagao(P2, Q2, mascara_zero)

df1 = pd.DataFrame({"Hora_decimal": hora_decimal, "P_3f": P1, "Q_3f": Q1})
df2 = pd.DataFrame({"Hora_decimal": hora_decimal, "P_3f": P2, "Q_3f": Q2})

df1.to_csv(ARQ_1, index=False, encoding="utf-8")
df2.to_csv(ARQ_2, index=False, encoding="utf-8")

print("[OK] Celula 022 concluída.")
print(f"Arquivos:\n- {ARQ_1}\n- {ARQ_2}")
print(f"Período ativo (meses): {sorted(MESES_ATIVOS)} | Deslocamento bomba2 = {DESLOC_HORAS}h")
print(f"Pontos zerados por apagão: {int(mascara_zero.sum())}")

# %% Celula 023 - Curva Antena AM + climatização (sm250) + zerar em apagão RGE
# Saída:
#   20 Memoria de massa estimada antena AM para simulacao 2025\sm250_PQ_1125ANTENA_2025_112.5kVA.csv

from pathlib import Path
import numpy as np
import pandas as pd

DIR_SAIDA = Path(r"C:\GitHub\determinar_modelo\20 Memoria de massa estimada antena AM para simulacao 2025")
DIR_SAIDA.mkdir(parents=True, exist_ok=True)

ARQ_CSV = DIR_SAIDA / "sm250_PQ_1125ANTENA_2025_112.5kVA.csv"

# ------------------------
# Tempo
# ------------------------
N_DIAS = 365
PTS_DIA = 96
DT_MIN = 15
DT_H = 0.25
N = N_DIAS * PTS_DIA

hora_decimal = np.arange(N, dtype=float) * DT_H

# ------------------------
# Antena AM fixa (24/7)
# ------------------------
S_AM = 20.0
FP_AM = 0.90
phi_am = np.arccos(FP_AM)
P_AM = S_AM * FP_AM
Q_AM = S_AM * np.sin(phi_am)

# ------------------------
# Climatização cíclica (24/7): 2h ON / 1h OFF
# ------------------------
S_AC = 10.0
FP_AC = 0.95
phi_ac = np.arccos(FP_AC)
P_AC_LIGADO = S_AC * FP_AC
Q_AC_LIGADO = S_AC * np.sin(phi_ac)

PASSOS_LIGADO = int((2 * 60) / DT_MIN)     # 8
PASSOS_CICLO  = int((3 * 60) / DT_MIN)     # 12

mascara_dia = np.zeros(PTS_DIA, dtype=bool)
for k in range(0, PTS_DIA, PASSOS_CICLO):
    mascara_dia[k:k + PASSOS_LIGADO] = True

# ------------------------
# Série anual
# ------------------------
P = np.full(N, P_AM, dtype=float)
Q = np.full(N, Q_AM, dtype=float)

for d in range(N_DIAS):
    base = d * PTS_DIA
    P[base:base + PTS_DIA] += np.where(mascara_dia, P_AC_LIGADO, 0.0)
    Q[base:base + PTS_DIA] += np.where(mascara_dia, Q_AC_LIGADO, 0.0)

# ------------------------
# Zerar em apagão total RGE
# ------------------------
mascara_zero = carregar_mascara_apagao(hora_decimal)
P, Q = aplicar_apagao(P, Q, mascara_zero)

df = pd.DataFrame({"Hora_decimal": hora_decimal, "P_3f": P, "Q_3f": Q})
df.to_csv(ARQ_CSV, index=False, encoding="utf-8")

print("[OK] Celula 023 concluída.")
print(f"Arquivo:\n- {ARQ_CSV}")
print(f"Pontos zerados por apagão: {int(mascara_zero.sum())}")

# %% Celula 024 - Curva de eventos esporádicos (sm251) + zerar em apagão RGE
# Saída:
#   21 Memoria de massa estimada eventos para simulacao 2025\sm251_PQ_45PONTE_2025_45kVA.csv
#
# Premissas:
# - Carga: 30 kVA, fp=0.95
# - Eventos: 2 dias/mês, dias 1 e 15
# - Janela: 08:00-20:00

from pathlib import Path
import numpy as np
import pandas as pd
from datetime import datetime

DIR_SAIDA = Path(r"C:\GitHub\determinar_modelo\21 Memoria de massa estimada eventos para simulacao 2025")
DIR_SAIDA.mkdir(parents=True, exist_ok=True)

ARQ_CSV = DIR_SAIDA / "sm251_PQ_45PONTE_2025_45kVA.csv"

ANO = 2025
N_DIAS = 365
PTS_DIA = 96
DT_MIN = 15
DT_H = 0.25
N = N_DIAS * PTS_DIA

hora_decimal = np.arange(N, dtype=float) * DT_H

# Carga do evento
S_EVT = 30.0
FP_EVT = 0.95
phi_evt = np.arccos(FP_EVT)
P_LIGADO = S_EVT * FP_EVT
Q_LIGADO = S_EVT * np.sin(phi_evt)

IDX_08 = 8 * 4
IDX_20 = 20 * 4  # exclusivo

# Define eventos: dias 1 e 15 de cada mês
datas_evento = []
for mes in range(1, 13):
    datas_evento.append(datetime(ANO, mes, 1))
    datas_evento.append(datetime(ANO, mes, 15))

data_inicio = datetime(ANO, 1, 1)
indices_dia_evento = set()
for dt in datas_evento:
    idx_dia = (dt - data_inicio).days
    if 0 <= idx_dia < N_DIAS:
        indices_dia_evento.add(idx_dia)

P = np.zeros(N, dtype=float)
Q = np.zeros(N, dtype=float)

for d in range(N_DIAS):
    if d in indices_dia_evento:
        base = d * PTS_DIA
        P[base + IDX_08 : base + IDX_20] = P_LIGADO
        Q[base + IDX_08 : base + IDX_20] = Q_LIGADO

# Zerar em apagão total RGE
mascara_zero = carregar_mascara_apagao(hora_decimal)
P, Q = aplicar_apagao(P, Q, mascara_zero)

df = pd.DataFrame({"Hora_decimal": hora_decimal, "P_3f": P, "Q_3f": Q})
df.to_csv(ARQ_CSV, index=False, encoding="utf-8")

print("[OK] Celula 024 concluída.")
print(f"Arquivo:\n- {ARQ_CSV}")
print(f"Eventos no ano: {len(indices_dia_evento)} (esperado 24)")
print(f"Pontos zerados por apagão: {int(mascara_zero.sum())}")

# %% Celula 025 - Converter curvas para PU (Loadshape OpenDSS) a partir de multiplas pastas
# Saída separada em:
#   Cargas_Medidas   <- arquivos vindos da pasta 14
#   Cargas_Estimadas <- arquivos vindos da pasta 15
#   Cargas_Especiais <- todo o resto (17..21)

from pathlib import Path
import pandas as pd
import re

# -----------------------------
# Pastas de entrada (origens)
# -----------------------------
DIR_MEDIDAS = Path(r"C:\GitHub\determinar_modelo\14 Memoria de massa para simulacao I e base para nao medidos 2025")
DIR_ESTIMADAS = Path(r"C:\GitHub\determinar_modelo\15 Memoria de massa estimada para simulacao I dos trafos nao medidos 2025")

DIR_ESPECIAIS = [
    Path(r"C:\GitHub\determinar_modelo\17 Memoria de massa estimada carregadores VE para simulacao 2025"),
    Path(r"C:\GitHub\determinar_modelo\18 Memoria de massa estimada pocos para simulacao 2025"),
    Path(r"C:\GitHub\determinar_modelo\19 Memoria de massa estimada irrigacao para simulacao 2025"),
    Path(r"C:\GitHub\determinar_modelo\20 Memoria de massa estimada antena AM para simulacao 2025"),
    Path(r"C:\GitHub\determinar_modelo\21 Memoria de massa estimada eventos para simulacao 2025"),
]

# -----------------------------
# Pastas de saída (PU)
# -----------------------------
DIR_SAIDA_BASE = Path(r"C:\GitHub\determinar_modelo")

DIR_SAIDA_MEDIDAS   = DIR_SAIDA_BASE / "Cargas_Medidas"
DIR_SAIDA_ESTIMADAS = DIR_SAIDA_BASE / "Cargas_Estimadas"
DIR_SAIDA_ESPECIAIS = DIR_SAIDA_BASE / "Cargas_Especiais"

for d in (DIR_SAIDA_MEDIDAS, DIR_SAIDA_ESTIMADAS, DIR_SAIDA_ESPECIAIS):
    d.mkdir(parents=True, exist_ok=True)

# -----------------------------
# Extrai potencia kVA do nome do arquivo
# Ex: sm058_PQ_500ODONTO_2025_500kVA.csv -> 500
# -----------------------------
def extrair_kva(nome_arquivo: str) -> float:
    m = re.search(r"_([0-9.]+)kVA", nome_arquivo)
    if not m:
        raise ValueError(f"Nao foi possivel extrair kVA de: {nome_arquivo}")
    return float(m.group(1))

# -----------------------------
# Função de conversão (1 pasta -> 1 pasta de saída)
# -----------------------------
def converter_pasta_para_pu(pasta_entrada: Path, pasta_saida: Path) -> int:
    if not pasta_entrada.exists():
        print(f"[PULA] Pasta nao encontrada: {pasta_entrada}")
        return 0

    cont = 0
    for fp in sorted(pasta_entrada.glob("sm*_PQ_*.csv")):
        kva = extrair_kva(fp.name)

        df = pd.read_csv(fp, usecols=["Hora_decimal", "P_3f", "Q_3f"])

        # Converte para float
        df["P_3f"] = pd.to_numeric(df["P_3f"], errors="coerce").fillna(0.0)
        df["Q_3f"] = pd.to_numeric(df["Q_3f"], errors="coerce").fillna(0.0)

        # PU
        df["P_pu"] = df["P_3f"] / kva
        df["Q_pu"] = df["Q_3f"] / kva

        out_df = df[["Hora_decimal", "P_pu", "Q_pu"]]

        # Nome de saída
        out_name = fp.stem + "_pu.csv"
        out_path = pasta_saida / out_name

        # Salva SEM cabeçalho (OpenDSS)
        out_df.to_csv(out_path, index=False, header=False)

        print(f"[OK] {out_path.name} | base = {kva} kVA | destino = {pasta_saida.name}")
        cont += 1

    return cont

# -----------------------------
# Processamento por grupo
# -----------------------------
total_medidas = converter_pasta_para_pu(DIR_MEDIDAS, DIR_SAIDA_MEDIDAS)
total_estimadas = converter_pasta_para_pu(DIR_ESTIMADAS, DIR_SAIDA_ESTIMADAS)

total_especiais = 0
for pasta in DIR_ESPECIAIS:
    total_especiais += converter_pasta_para_pu(pasta, DIR_SAIDA_ESPECIAIS)

total = total_medidas + total_estimadas + total_especiais

print("\n-----------------------------")
print("[RESUMO]")
print(f"Medidas   : {total_medidas}")
print(f"Estimadas : {total_estimadas}")
print(f"Especiais : {total_especiais}")
print(f"TOTAL     : {total}")
print(f"Saída base: {DIR_SAIDA_BASE}")
print("-----------------------------")

# %% Celula 026 – PRIMEIRA SIMULACAO OPEN-DSS (UFSM 2025)

import os
import shutil
from pathlib import Path
from py_dss_interface import DSS

WORK_DIR = Path(r"C:\GitHub\determinar_modelo")
SIM_DIR  = WORK_DIR / "Simulacao 001"
SIM_DIR.mkdir(parents=True, exist_ok=True)

os.chdir(WORK_DIR)

MON_NAME = "GERAL"
EXPORT_DIR = SIM_DIR

def find_exported_monitor_file(export_dir: Path, mon_name: str) -> Path:
    cands = sorted(
        export_dir.glob(f"*{mon_name}*.csv"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )
    if not cands:
        cands2 = sorted(
            export_dir.glob("Mon_*.csv"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        if cands2:
            return cands2[0]
        raise FileNotFoundError(
            f"Nenhum CSV do monitor contendo '{mon_name}' em {export_dir}"
        )
    return cands[0]

# --- OpenDSS ---
dss = DSS()
dss.text("Clear")
dss.text(f'cd "{WORK_DIR}"')

dss.text(
    "New Circuit.UFSM bus1=0010 basekv=13.8 phases=3 "
    "puZ0=[1.24 2.50] puZ1=[0.43 0.98] puZ2=[0.43 0.98]"
)
dss.text(f'Redirect "{WORK_DIR / "UFSM_wiredata.dss"}"')
dss.text(f'Redirect "{WORK_DIR / "UFSM_linhas.dss"}"')
dss.text(f'Redirect "{WORK_DIR / "UFSM_chaves.dss"}"')
dss.text(f'Redirect "{WORK_DIR / "UFSM_caps.dss"}"')
dss.text(f'Redirect "{WORK_DIR / "UFSM_trafos_medidos.dss"}"')
dss.text(f'Redirect "{WORK_DIR / "UFSM_trafos_cargas_especiais.dss"}"')
dss.text(f'Redirect "{WORK_DIR / "UFSM_trafos_estimados.dss"}"')
dss.text(f'Redirect "{WORK_DIR / "UFSM_cargas_medidas.dss"}"')
dss.text(f'Redirect "{WORK_DIR / "UFSM_cargas_especiais.dss"}"')
dss.text(f'Redirect "{WORK_DIR / "UFSM_cargas_estimadas.dss"}"')

dss.text(f'Set DataPath="{EXPORT_DIR}"')

dss.text("New Monitor.GERAL element=line.0015_0016 terminal=1 mode=1 ppolar=no")
dss.text("Set VoltageBases=[13.8,0.38,0.22]")
dss.text("CalcVoltageBases")
dss.text("Set Mode=Yearly Hour=0 Sec=0 StepSize=0.25h Number=35040")
dss.text("Solve")
dss.text("Export Monitors GERAL")

fp = find_exported_monitor_file(EXPORT_DIR, MON_NAME)
dst = SIM_DIR / "UFSM_Mon_geral_1.csv"

if fp.resolve() != dst.resolve():
    if dst.exists():
        dst.unlink()
    shutil.move(str(fp), str(dst))

print("Concluido. Monitor exportado:", dst)

# %% Celula 027 - Criar "Curva_de_Carga_sim_1.csv" a partir do monitor e aplicar shift anual

import os
from pathlib import Path
import numpy as np
import pandas as pd

WORK_DIR = Path(r"C:\GitHub\determinar_modelo")
SIM_DIR  = WORK_DIR / "Simulacao 001"
SIM_DIR.mkdir(parents=True, exist_ok=True)

os.chdir(WORK_DIR)

MON_NAME = "GERAL"
DT_H = 0.25
EXPECTED_N = 35040
hora = np.round(np.arange(0.0, 8760.0, DT_H), 10)

mon_fp = SIM_DIR / f"UFSM_Mon_{MON_NAME.lower()}_1.csv"
out_fp = SIM_DIR / "Curva_de_Carga_sim_1.csv"

if not mon_fp.exists():
    raise FileNotFoundError(f"Monitor CSV not found: {mon_fp}")

mon = pd.read_csv(mon_fp, encoding="utf-8-sig", sep=None, engine="python")
mon.columns = (
    mon.columns.astype(str)
    .str.replace("\ufeff", "", regex=False)
    .str.replace("\t", " ", regex=False)
    .str.strip()
    .str.replace(r"\s+", " ", regex=True)
)

needed = [
    "P1 (kW)", "Q1 (kvar)",
    "P2 (kW)", "Q2 (kvar)",
    "P3 (kW)", "Q3 (kvar)",
]
missing = [c for c in needed if c not in mon.columns]
if missing:
    raise ValueError(f"Missing monitor columns: {missing}\nDetected: {list(mon.columns)}")

for c in needed:
    mon[c] = pd.to_numeric(mon[c], errors="coerce")

if mon[needed].isna().any().any():
    bad = mon[needed].isna().sum()
    raise ValueError(f"NaN found after numeric conversion:\n{bad}")

# Totais trifásicos a partir do monitor bruto
mon["P_3f_S"] = mon["P1 (kW)"] + mon["P2 (kW)"] + mon["P3 (kW)"]
mon["Q_3f_S"] = mon["Q1 (kvar)"] + mon["Q2 (kvar)"] + mon["Q3 (kvar)"]

vals = mon[["P_3f_S", "Q_3f_S"]].to_numpy(copy=True)

if len(vals) != EXPECTED_N:
    raise ValueError(f"Unexpected length: {len(vals)} rows (expected {EXPECTED_N}).")

# Shift anual unico para a DIREITA:
# duplica a 1a linha e remove a ultima
vals = np.vstack([vals[0:1, :], vals[0:-1, :]])

df_out = pd.DataFrame({
    "Hora_decimal": hora,
    "P_3f_S": vals[:, 0],
    "Q_3f_S": vals[:, 1],
})

if len(df_out) != EXPECTED_N:
    raise ValueError(f"Tamanho inesperado da curva final: {len(df_out)}")

if abs(df_out["Hora_decimal"].iloc[0] - 0.0) > 1e-9:
    raise ValueError("Hora_decimal does not start at 0.0")
if abs(df_out["Hora_decimal"].iloc[-1] - 8759.75) > 1e-9:
    raise ValueError("Hora_decimal last time is not 8759.75")
if not np.allclose(np.diff(df_out["Hora_decimal"].values), DT_H, atol=1e-9):
    raise ValueError("Hora_decimal is not a uniform 0.25h grid after cleaning.")

df_out.to_csv(out_fp, index=False, encoding="utf-8-sig")

try:
    mon_fp.unlink()
except Exception as e:
    raise RuntimeError(f"Could not delete monitor CSV: {e}")

print("DONE. Saved:", out_fp)
print("DONE. Deleted:", mon_fp)
print("[INFO] Shift anual unico aplicado para a DIREITA.")

# %% Celula 028 - Estatísticas comparativas RGE vs SIM1 (2025)  [SAÍDA EM: Simulacao 001]

from pathlib import Path
import numpy as np
import pandas as pd

WORK_DIR = Path(r"C:\GitHub\determinar_modelo")

# --- pasta da Simulação I ---
SIM1_DIR = WORK_DIR / "Simulacao 001"
SIM1_DIR.mkdir(parents=True, exist_ok=True)

RGE_FP = WORK_DIR / "00_memoria_de_massa_RGE_15min_2025.csv"
SIM_FP = SIM1_DIR / "Curva_de_Carga_sim_1.csv"

OUT_RESUMO = SIM1_DIR / "validacao_SIM1_resumo.csv"
OUT_PICOS  = SIM1_DIR / "validacao_SIM1_picos_mensais.csv"

DT_H = 0.25
N = 35040
grid = np.round(np.arange(0.0, 8760.0, 0.25), 2)

# ---------- leitura ----------
rge = pd.read_csv(RGE_FP, encoding="utf-8-sig", sep=None, engine="python")
sim = pd.read_csv(SIM_FP, encoding="utf-8-sig", sep=None, engine="python")

# ---------- normalização de colunas ----------
def _norm_cols(df):
    df.columns = (
        df.columns.astype(str)
        .str.replace("\ufeff", "", regex=False)
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
    )
    return df

rge = _norm_cols(rge)
sim = _norm_cols(sim)

# ---------- seleção ----------
rge = rge[["Hora_decimal", "P_3f", "Q_3f"]].rename(columns={"P_3f": "P_RGE", "Q_3f": "Q_RGE"})
sim = sim[["Hora_decimal", "P_3f_S", "Q_3f_S"]].rename(columns={"P_3f_S": "P_SIM", "Q_3f_S": "Q_SIM"})

# ---------- numéricos ----------
for c in ["Hora_decimal", "P_RGE", "Q_RGE"]:
    rge[c] = pd.to_numeric(rge[c], errors="coerce")

for c in ["Hora_decimal", "P_SIM", "Q_SIM"]:
    sim[c] = pd.to_numeric(sim[c], errors="coerce")

rge = rge.dropna(subset=["Hora_decimal"]).drop_duplicates("Hora_decimal").sort_values("Hora_decimal")
sim = sim.dropna(subset=["Hora_decimal"]).drop_duplicates("Hora_decimal").sort_values("Hora_decimal")

# ---------- alinhamento ----------
base = pd.DataFrame({"Hora_decimal": grid})
df = base.merge(rge, on="Hora_decimal", how="left").merge(sim, on="Hora_decimal", how="left")

# HOLD forward
for c in ["P_RGE", "Q_RGE", "P_SIM", "Q_SIM"]:
    if pd.isna(df[c].iloc[0]):
        first = df[c].first_valid_index()
        if first is None:
            raise ValueError(f"Série inteira vazia para {c}")
        df.loc[0, c] = df.loc[first, c]
    df[c] = df[c].ffill()

if len(df) != N:
    raise ValueError(f"Tamanho inesperado após alinhamento: {len(df)} (esperado {N})")

# ---------- métricas ----------
def calc_stats(sim_s, ref_s):
    e = sim_s - ref_s

    NMAE = np.nan if ref_s.abs().sum() == 0 else float(e.abs().sum() / ref_s.abs().sum())

    RMSE = float(np.sqrt(np.mean(e.values ** 2)))
    rng = float(ref_s.max() - ref_s.min())
    NRMSE = np.nan if rng == 0 else float(RMSE / rng)

    E_sim = float(sim_s.sum() * DT_H)
    E_ref = float(ref_s.sum() * DT_H)
    eps_E = np.nan if E_ref == 0 else float(abs(E_sim - E_ref) / abs(E_ref))

    return NMAE, NRMSE, E_sim, E_ref, eps_E

NMAE_P, NRMSE_P, E_P_sim, E_P_rge, eps_E_P = calc_stats(df["P_SIM"], df["P_RGE"])
NMAE_Q, NRMSE_Q, E_Q_sim, E_Q_rge, eps_E_Q = calc_stats(df["Q_SIM"], df["Q_RGE"])

# ---------- picos mensais ----------
ts = pd.date_range("2025-01-01", periods=N, freq="15min")
dft = df.copy()
dft["timestamp"] = ts
dft = dft.set_index("timestamp")

mensal = pd.DataFrame({
    "P_SIM_max": dft["P_SIM"].resample("ME").max(),
    "P_RGE_max": dft["P_RGE"].resample("ME").max(),
    "Q_SIM_max": dft["Q_SIM"].resample("ME").max(),
    "Q_RGE_max": dft["Q_RGE"].resample("ME").max(),
})

mensal["Delta_Pmax"] = mensal["P_SIM_max"] - mensal["P_RGE_max"]
mensal["Delta_Qmax"] = mensal["Q_SIM_max"] - mensal["Q_RGE_max"]

mensal = mensal.reset_index()
mensal["Mes"] = mensal["timestamp"].dt.to_period("M").astype(str)

mensal = mensal[[
    "Mes",
    "P_SIM_max", "P_RGE_max", "Delta_Pmax",
    "Q_SIM_max", "Q_RGE_max", "Delta_Qmax"
]]

# ---------- resumo ----------
resumo = pd.DataFrame([
    ["P", "NMAE",              NMAE_P],
    ["P", "NRMSE",             NRMSE_P],
    ["P", "Energia_SIM_kWh",   E_P_sim],
    ["P", "Energia_RGE_kWh",   E_P_rge],
    ["P", "Erro_rel_energia",  eps_E_P],

    ["Q", "NMAE",              NMAE_Q],
    ["Q", "NRMSE",             NRMSE_Q],
    ["Q", "Energia_SIM_kVArh", E_Q_sim],
    ["Q", "Energia_RGE_kVArh", E_Q_rge],
    ["Q", "Erro_rel_energia",  eps_E_Q],
], columns=["Grandeza", "Metrica", "Valor"])

# ---------- salvar ----------
resumo.to_csv(OUT_RESUMO, index=False, float_format="%.6g", encoding="utf-8")
mensal.to_csv(OUT_PICOS, index=False, float_format="%.6g", encoding="utf-8")

print("✔ Resumo salvo em:", OUT_RESUMO)
print("✔ Picos mensais salvos em:", OUT_PICOS)

# %% Celula 029 - Calcular Curva_residuo_BT_sim_1 = RGE (raiz) - SIM (Simulacao 001)

import os
from pathlib import Path
import numpy as np
import pandas as pd

WORK_DIR = Path(r"C:\GitHub\determinar_modelo")
SIM_DIR  = WORK_DIR / "Simulacao 001"
os.chdir(WORK_DIR)

# RGE fica na raiz
RGE_FP = WORK_DIR / "00_memoria_de_massa_RGE_15min_2025.csv"

# SIM e saídas ficam na subpasta
SIM_FP = SIM_DIR / "Curva_de_Carga_sim_1.csv"
OUT_FP = SIM_DIR / "Curva_residuo_BT_sim_1.csv"

for fp in [RGE_FP, SIM_FP]:
    if not fp.exists():
        raise FileNotFoundError(f"File not found: {fp}")

expected_n = 35040
grid = np.round(np.arange(0.0, 8760.0, 0.25), 2)

def _read(fp: Path) -> pd.DataFrame:
    df = pd.read_csv(fp, encoding="utf-8-sig", sep=None, engine="python")
    df.columns = (
        df.columns.astype(str)
        .str.replace("\ufeff", "", regex=False)
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
    )
    return df

def _to_grid(df: pd.DataFrame, hcol: str, pcol: str, qcol: str, tag: str) -> pd.DataFrame:
    out = df[[hcol, pcol, qcol]].copy()
    out[hcol] = pd.to_numeric(out[hcol], errors="coerce")
    out[pcol] = pd.to_numeric(out[pcol], errors="coerce")
    out[qcol] = pd.to_numeric(out[qcol], errors="coerce")

    out = out.dropna(subset=[hcol]).drop_duplicates(subset=[hcol]).sort_values(hcol).reset_index(drop=True)
    out = out[out[hcol] < 8760.0].copy()

    base = pd.DataFrame({"Hora_decimal": grid})
    out = base.merge(out, left_on="Hora_decimal", right_on=hcol, how="left")

    # HOLD inicial
    if pd.isna(out[pcol].iloc[0]) or pd.isna(out[qcol].iloc[0]):
        first_idx = out[pcol].first_valid_index()
        if first_idx is None:
            raise ValueError(f"[{tag}] Série inteira sem valores válidos.")
        out.loc[0, pcol] = out.loc[first_idx, pcol]
        out.loc[0, qcol] = out.loc[first_idx, qcol]

    out[pcol] = out[pcol].ffill()
    out[qcol] = out[qcol].ffill()

    if len(out) != expected_n:
        raise ValueError(f"[{tag}] Tamanho inesperado: {len(out)} (esperado {expected_n}).")

    return out[["Hora_decimal", pcol, qcol]].rename(columns={pcol: "P", qcol: "Q"})

rge_raw = _read(RGE_FP)
sim_raw = _read(SIM_FP)

req_rge = ["Hora_decimal", "P_3f", "Q_3f"]
req_sim = ["Hora_decimal", "P_3f_S", "Q_3f_S"]

for name, df, req in [("RGE", rge_raw, req_rge), ("SIM", sim_raw, req_sim)]:
    miss = [c for c in req if c not in df.columns]
    if miss:
        raise ValueError(f"Colunas faltando em {name}: {miss}. Disponíveis: {list(df.columns)}")

rge = _to_grid(rge_raw, "Hora_decimal", "P_3f", "Q_3f", "RGE")
sim = _to_grid(sim_raw, "Hora_decimal", "P_3f_S", "Q_3f_S", "SIM")

res = pd.DataFrame({"Hora_decimal": grid})
res["P_residuo_BT_kW"]   = rge["P"] - sim["P"]
res["Q_residuo_BT_kVAr"] = rge["Q"] - sim["Q"]

# garante pasta
SIM_DIR.mkdir(parents=True, exist_ok=True)

res.to_csv(OUT_FP, index=False, encoding="utf-8-sig")
print("DONE. Saved:", OUT_FP)

print("P_residuo_BT_kW   min/mean/max =",
      float(res["P_residuo_BT_kW"].min()),
      float(res["P_residuo_BT_kW"].mean()),
      float(res["P_residuo_BT_kW"].max()))

print("Q_residuo_BT_kVAr min/mean/max =",
      float(res["Q_residuo_BT_kVAr"].min()),
      float(res["Q_residuo_BT_kVAr"].mean()),
      float(res["Q_residuo_BT_kVAr"].max()))

# %% Celula 030 - Criar Curva_residuo_BT_por_kVA_sim_1 (fatores por soma das demandas estimadas)

import os
from pathlib import Path
import numpy as np
import pandas as pd

WORK_DIR = Path(r"C:\GitHub\determinar_modelo")
SIM_DIR  = WORK_DIR / "Simulacao 001"
os.chdir(WORK_DIR)

RES_FP  = SIM_DIR  / "Curva_residuo_BT_sim_1.csv"                 
EST_DIR = WORK_DIR / "15 Memoria de massa estimada para simulacao I dos trafos nao medidos 2025"
OUT_FP  = SIM_DIR  / "Curva_residuo_BT_por_kVA_sim_1.csv"         

SIM_DIR.mkdir(parents=True, exist_ok=True)

if not RES_FP.exists():  raise FileNotFoundError(RES_FP)
if not EST_DIR.exists(): raise FileNotFoundError(EST_DIR)

expected_n = 35040
grid = np.round(np.arange(0.0, 8760.0, 0.25), 2)

res = pd.read_csv(RES_FP, encoding="utf-8-sig", sep=None, engine="python")
res.columns = res.columns.astype(str).str.replace("\ufeff","",regex=False).str.strip().str.replace(r"\s+"," ",regex=True)

need_res = ["Hora_decimal", "P_residuo_BT_kW", "Q_residuo_BT_kVAr"]
miss = [c for c in need_res if c not in res.columns]
if miss:
    raise ValueError(f"Colunas faltando em {RES_FP.name}: {miss}")

for c in need_res:
    res[c] = pd.to_numeric(res[c], errors="coerce")

res = res.dropna(subset=["Hora_decimal"]).drop_duplicates("Hora_decimal", keep="first").sort_values("Hora_decimal").reset_index(drop=True)
res = res[res["Hora_decimal"] < 8760.0].copy()

if len(res) != expected_n:
    raise ValueError(f"{RES_FP.name}: tamanho {len(res)} != {expected_n}")
if not np.allclose(res["Hora_decimal"].to_numpy(dtype=float), grid, atol=1e-9):
    raise ValueError(f"{RES_FP.name}: Hora_decimal desalinhado")

csvs = sorted(EST_DIR.glob("*.csv"))
if not csvs:
    raise FileNotFoundError(f"Nenhum CSV em {EST_DIR}")

sumP = np.zeros(expected_n, dtype=float)
sumAbsQ = np.zeros(expected_n, dtype=float)

def _read_curve(fp: Path) -> pd.DataFrame:
    df = pd.read_csv(fp, encoding="utf-8-sig", sep=None, engine="python")
    df.columns = df.columns.astype(str).str.replace("\ufeff","",regex=False).str.strip().str.replace(r"\s+"," ",regex=True)
    needed = ["Hora_decimal","P_3f","Q_3f"]
    miss = [c for c in needed if c not in df.columns]
    if miss:
        raise ValueError(f"{fp.name}: colunas faltando {miss}")

    for c in needed:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=["Hora_decimal"]).drop_duplicates("Hora_decimal", keep="first").sort_values("Hora_decimal").reset_index(drop=True)
    df = df[df["Hora_decimal"] < 8760.0].copy()

    # garante 0.0 (HOLD do primeiro)
    if not (df["Hora_decimal"] == 0.0).any():
        first = df.iloc[0]
        df = pd.concat([pd.DataFrame([{
            "Hora_decimal": 0.0,
            "P_3f": float(first["P_3f"]),
            "Q_3f": float(first["Q_3f"]),
        }]), df], ignore_index=True).sort_values("Hora_decimal").drop_duplicates("Hora_decimal", keep="first").reset_index(drop=True)

    if len(df) != expected_n:
        raise ValueError(f"{fp.name}: tamanho {len(df)} != {expected_n}")
    if not np.allclose(df["Hora_decimal"].to_numpy(dtype=float), grid, atol=1e-9):
        raise ValueError(f"{fp.name}: Hora_decimal desalinhado")

    return df[["Hora_decimal","P_3f","Q_3f"]]

for fp in csvs:
    dfc = _read_curve(fp)
    sumP += dfc["P_3f"].to_numpy(dtype=float)
    sumAbsQ += np.abs(dfc["Q_3f"].to_numpy(dtype=float))

EPS = 1e-9
resP = res["P_residuo_BT_kW"].to_numpy(dtype=float)
resQ = res["Q_residuo_BT_kVAr"].to_numpy(dtype=float)

fP = np.zeros_like(resP)
maskP = np.abs(sumP) > EPS
fP[maskP] = resP[maskP] / sumP[maskP]

fQ = np.zeros_like(resQ)
maskQ = sumAbsQ > EPS
fQ[maskQ] = resQ[maskQ] / sumAbsQ[maskQ]

out = pd.DataFrame({
    "Hora_decimal": grid,
    "P_residuo_BT_kW": resP,
    "Q_residuo_BT_kVAr": resQ,
    "sumP_est_kW": sumP,
    "sumAbsQ_est_kVAr": sumAbsQ,
    "fatorP_por_sumP": fP,
    "fatorQ_por_sumAbsQ": fQ,
})

out.to_csv(OUT_FP, index=False, encoding="utf-8-sig")
print("DONE. Saved:", OUT_FP)
print("Curvas estimadas lidas:", len(csvs))

# %% Celula 031 - Aplicar resíduo proporcional nas curvas estimadas e salvar em 22... (NA RAIZ)

import os
from pathlib import Path
import numpy as np
import pandas as pd

WORK_DIR = Path(r"C:\GitHub\determinar_modelo")
SIM_DIR  = WORK_DIR / "Simulacao 001"
os.chdir(WORK_DIR)

# FATOR vem da subpasta
FACT_FP = SIM_DIR / "Curva_residuo_BT_por_kVA_sim_1.csv"

# Curvas base continuam na raiz
SRC_DIR = WORK_DIR / "15 Memoria de massa estimada para simulacao I dos trafos nao medidos 2025"

# Saída 22 continua na raiz
OUT_DIR = WORK_DIR / "22 Memoria de massa estimada com residuo para simulacao II dos trafos nao medidos 2025"
OUT_DIR.mkdir(parents=True, exist_ok=True)

if not FACT_FP.exists(): raise FileNotFoundError(FACT_FP)
if not SRC_DIR.exists(): raise FileNotFoundError(SRC_DIR)

expected_n = 35040
grid = np.round(np.arange(0.0, 8760.0, 0.25), 2)

fact = pd.read_csv(FACT_FP, encoding="utf-8-sig", sep=None, engine="python")
fact.columns = fact.columns.astype(str).str.replace("\ufeff","",regex=False).str.strip().str.replace(r"\s+"," ",regex=True)

need = ["Hora_decimal","fatorP_por_sumP","fatorQ_por_sumAbsQ"]
miss = [c for c in need if c not in fact.columns]
if miss:
    raise ValueError(f"Colunas faltando em {FACT_FP.name}: {miss}")

for c in need:
    fact[c] = pd.to_numeric(fact[c], errors="coerce")

fact = fact.dropna(subset=["Hora_decimal"]).drop_duplicates("Hora_decimal").sort_values("Hora_decimal")
fact = fact[fact["Hora_decimal"] < 8760.0].reset_index(drop=True)

if len(fact) != expected_n:
    raise ValueError(f"{FACT_FP.name}: tamanho {len(fact)} != {expected_n}")
if not np.allclose(fact["Hora_decimal"].to_numpy(dtype=float), grid, atol=1e-9):
    raise ValueError(f"{FACT_FP.name}: Hora_decimal desalinhado")

fP = fact["fatorP_por_sumP"].to_numpy(dtype=float)
fQ = fact["fatorQ_por_sumAbsQ"].to_numpy(dtype=float)

def _read_curve(fp: Path) -> pd.DataFrame:
    df = pd.read_csv(fp, encoding="utf-8-sig", sep=None, engine="python")
    df.columns = df.columns.astype(str).str.replace("\ufeff","",regex=False).str.strip().str.replace(r"\s+"," ",regex=True)

    for c in ["Hora_decimal","P_3f","Q_3f"]:
        if c not in df.columns:
            raise ValueError(f"{fp.name}: coluna faltando {c}")
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=["Hora_decimal"]).drop_duplicates("Hora_decimal").sort_values("Hora_decimal")
    df = df[df["Hora_decimal"] < 8760.0].reset_index(drop=True)

    if not (df["Hora_decimal"] == 0.0).any():
        first = df.iloc[0]
        df = pd.concat([pd.DataFrame([{
            "Hora_decimal": 0.0,
            "P_3f": float(first["P_3f"]),
            "Q_3f": float(first["Q_3f"]),
        }]), df], ignore_index=True).sort_values("Hora_decimal").drop_duplicates("Hora_decimal").reset_index(drop=True)

    if len(df) != expected_n:
        raise ValueError(f"{fp.name}: tamanho {len(df)} != {expected_n}")
    if not np.allclose(df["Hora_decimal"].to_numpy(dtype=float), grid, atol=1e-9):
        raise ValueError(f"{fp.name}: Hora_decimal desalinhado")

    return df[["Hora_decimal","P_3f","Q_3f"]]

csvs = sorted(SRC_DIR.glob("*.csv"))
if not csvs:
    raise FileNotFoundError(f"Nenhum CSV em {SRC_DIR}")

p_alocado_total = np.zeros(expected_n)
q_alocado_total = np.zeros(expected_n)
ok, fail = 0, 0
for fp in csvs:
    try:
        base = _read_curve(fp)
        Pi = base["P_3f"].to_numpy(dtype=float)
        Qi = base["Q_3f"].to_numpy(dtype=float)

        dP = Pi * fP

        # fQ ja contem o sinal do residuo RGE - SIM.
        # Multiplicar por sign(Qi) invertia a correcao nas cargas capacitivas.
        dQ = np.abs(Qi) * fQ
        q_alvo = Qi + dQ
        # Preserva a natureza indutiva/capacitiva; saturacao em zero.
        # A parcela nao alocada fica registrada para posterior verificacao.
        q_corr = np.where(Qi > 0, np.maximum(q_alvo, 0.0),
                          np.where(Qi < 0, np.minimum(q_alvo, 0.0), 0.0))
        p_corr = np.maximum(Pi + dP, 0.0)
        p_alocado_total += p_corr - Pi
        q_alocado_total += q_corr - Qi
        base["P_3f"] = p_corr
        base["Q_3f"] = q_corr

        out_fp = OUT_DIR / (fp.stem + "_com_residuo.csv")
        base.to_csv(out_fp, index=False, encoding="utf-8-sig")
        ok += 1
    except Exception as e:
        print("[FAIL]", fp.name, "->", e)
        fail += 1

print("DONE. OK:", ok, "FAIL:", fail)
print("Saved in:", OUT_DIR)

# Diagnostico da primeira correcao: nao representa ainda o residuo no PAC.
if fail:
    raise RuntimeError("Falha na correcao de curvas. Nao prossiga para a simulacao II.")
res_original = pd.read_csv(SIM_DIR / "Curva_residuo_BT_sim_1.csv", encoding="utf-8-sig")
diag1 = pd.DataFrame({"Hora_decimal": grid, "P_alocado_kW": p_alocado_total,
                      "Q_alocado_kVAr": q_alocado_total})
diag1["P_nao_alocado_kW"] = res_original["P_residuo_BT_kW"].to_numpy() - p_alocado_total
diag1["Q_nao_alocado_kVAr"] = res_original["Q_residuo_BT_kVAr"].to_numpy() - q_alocado_total
diag1.to_csv(SIM_DIR / "Correcao_residuo_sim_1_diagnostico.csv", index=False, encoding="utf-8-sig")

# %% Celula 032 - Converter curvas com resíduo para pu

import os, re
from pathlib import Path
import pandas as pd
import numpy as np

WORK_DIR = Path(r"C:\GitHub\determinar_modelo")
os.chdir(WORK_DIR)

IN_DIR  = WORK_DIR / "22 Memoria de massa estimada com residuo para simulacao II dos trafos nao medidos 2025"
OUT_DIR = WORK_DIR / "Cargas_Estimadas_com_residuo_sim_2"
OUT_DIR.mkdir(parents=True, exist_ok=True)

csv_files = sorted(IN_DIR.glob("*.csv"))
if not csv_files:
    raise FileNotFoundError(f"Nenhum CSV em {IN_DIR}")

re_kva = re.compile(r"_(\d+(?:\.\d+)?)kVA", re.I)

def kva_do_nome(nome: str) -> float:
    m = re_kva.search(nome)
    if not m:
        raise ValueError(f"kVA não encontrado no nome: {nome}")
    kva = float(m.group(1))
    if kva <= 0:
        raise ValueError(f"kVA inválido no nome: {nome}")
    return kva

expected_n = 35040
grid = np.round(np.arange(0.0, 8760.0, 0.25), 2)

n_ok, n_fail = 0, 0

for fp in csv_files:
    try:
        kva = kva_do_nome(fp.name)

        df = pd.read_csv(fp, encoding="utf-8", sep=None, engine="python")
        df.columns = (
            df.columns.astype(str)
            .str.replace("\ufeff", "", regex=False)
            .str.strip()
            .str.replace(r"\s+", " ", regex=True)
        )

        for c in ["Hora_decimal", "P_3f", "Q_3f"]:
            if c not in df.columns:
                raise ValueError(f"{fp.name}: coluna faltando {c}")
            df[c] = pd.to_numeric(df[c], errors="coerce")

        df = (
            df.dropna(subset=["Hora_decimal", "P_3f", "Q_3f"])
              .query("Hora_decimal < 8760.0")
              .sort_values("Hora_decimal")
              .drop_duplicates("Hora_decimal")
              .reset_index(drop=True)
        )

        if len(df) != expected_n:
            raise ValueError(f"{fp.name}: tamanho {len(df)} != {expected_n}")

        if not np.allclose(df["Hora_decimal"].to_numpy(dtype=float), grid, atol=1e-9):
            raise ValueError(f"{fp.name}: Hora_decimal desalinhado")

        # ---- conversão para pu ----
        df["P_pu"] = df["P_3f"] / kva
        df["Q_pu"] = df["Q_3f"] / kva

        # ---- saída compatível OpenDSS ----
        out_fp = OUT_DIR / (fp.stem + "_pu.csv")

        df_out = df[["Hora_decimal", "P_pu", "Q_pu"]].copy()

        # força ponto decimal e precisão fixa
        for col in df_out.columns:
            df_out[col] = df_out[col].map(lambda x: f"{x:.6f}")
       
        df_out.to_csv(
            out_fp,
            index=False,
            header=False,
            encoding="utf-8",
            lineterminator="\n"
        )


        n_ok += 1

    except Exception as e:
        print("[FAIL]", fp.name, "->", e)
        n_fail += 1

print("DONE. Gerados:", n_ok, "Falhas:", n_fail)
print("Saída em:", OUT_DIR)

if n_fail:
    raise RuntimeError("Falha na conversao PU. Corrija antes da simulacao II.")


# Gerar o DSS da SIM2 a partir do DSS utilizado na SIM1.
# A celula 030 acrescenta _com_residuo aos CSVs: atualizar pasta e nome.
# Os nomes dos objetos Load/LoadShape e os parametros eletricos sao preservados.
DSS2_FP = WORK_DIR / "UFSM_cargas_estimadas_com_residuo_sim_2.dss"
pu_gerados = {(fp.stem + "_pu.csv").casefold(): OUT_DIR / (fp.stem + "_pu.csv") for fp in csv_files}
template_fp = WORK_DIR / "UFSM_cargas_estimadas.dss"
if not template_fp.is_file():
    raise FileNotFoundError(
        f"DSS de entrada da SIM1 ausente: {template_fp}. "
        "A celula 025 gera os CSVs PU; o DSS com LoadShapes e cargas "
        "deve estar disponivel entre os arquivos de entrada do projeto."
    )
# Referencia SIM1: <nome>_pu.csv -> SIM2: <nome>_com_residuo_pu.csv.
# O mapeamento e construido somente com os arquivos desta conversao.
mapa_sim1_sim2 = {}
for fp in csv_files:
    if not fp.stem.endswith("_com_residuo"):
        raise ValueError(f"Nome inesperado na pasta 22: {fp.name}; reexecute 030.")
    nome_sim1 = (fp.stem[:-len("_com_residuo")] + "_pu.csv").casefold()
    if nome_sim1 in mapa_sim1_sim2:
        raise ValueError(f"Referencia ambigua para a SIM1: {nome_sim1}")
    mapa_sim1_sim2[nome_sim1] = (fp.stem + "_pu.csv").casefold()
try:
    texto_dss = template_fp.read_text(encoding="utf-8-sig")
except UnicodeDecodeError:
    texto_dss = template_fp.read_text(encoding="cp1252")
refs_usadas = set()


def trocar_csv2(m):
    caminho = m[2].strip('"\'').replace("\\", "/")
    if not caminho.lower().endswith(".csv"):
        return m[0]
    nome_sim1 = caminho.rsplit("/", 1)[-1].casefold()
    if nome_sim1 not in mapa_sim1_sim2:
        raise FileNotFoundError(f"CSV do DSS da SIM1 sem correspondente na SIM2: {caminho}")
    nome = mapa_sim1_sim2[nome_sim1]
    refs_usadas.add(nome)
    return m[1] + '"' + pu_gerados[nome].resolve().as_posix() + '"'


padrao_csv2 = r'''(\b(?:csvfile|file|pqcsvfile)\s*=\s*)("[^"]*"|'[^']*'|[^,\s)]+)'''
texto_dss = re.sub(padrao_csv2, trocar_csv2, texto_dss, flags=re.I)
if refs_usadas != set(pu_gerados):
    raise ValueError("DSS nao referencia todas as curvas geradas: " + str(set(pu_gerados) - refs_usadas))
DSS2_FP.write_text(texto_dss, encoding="utf-8")
print("DSS da segunda simulacao:", DSS2_FP)


# %% Celula 033 – SEGUNDA SIMULACAO OPEN-DSS (UFSM 2025)

import os
import shutil
from pathlib import Path
from py_dss_interface import DSS

WORK_DIR = Path(r"C:\GitHub\determinar_modelo")
SIM_DIR  = WORK_DIR / "Simulacao 002"
SIM_DIR.mkdir(parents=True, exist_ok=True)

os.chdir(WORK_DIR)

MON_NAMES = ["GERAL"]

def find_exported_monitor_file(export_dir: Path, mon_name: str) -> Path:
    # Comparacao exata sem diferenciar maiusculas/minusculas (Windows/Linux).
    wanted = f"ufsm_mon_{mon_name}_1.csv".casefold()
    encontrados = [p for p in export_dir.iterdir() if p.name.casefold() == wanted]
    if len(encontrados) != 1:
        raise FileNotFoundError(f"Exportacao ausente/ambigua: {wanted}: {encontrados}")
    return encontrados[0]

if not (WORK_DIR / "UFSM_cargas_estimadas_com_residuo_sim_2.dss").is_file():
    raise FileNotFoundError("Execute a celula 031 antes da segunda simulacao.")

dss = DSS()
dss.text("Clear")
dss.text(f'cd "{WORK_DIR}"')

# arquivos de entrada com caminho absoluto
dss.text(
    "New Circuit.UFSM bus1=0010 basekv=13.8 phases=3 "
    "puZ0=[1.24 2.50] puZ1=[0.43 0.98] puZ2=[0.43 0.98]"
)
dss.text(f'Redirect "{WORK_DIR / "UFSM_wiredata.dss"}"')
dss.text(f'Redirect "{WORK_DIR / "UFSM_linhas.dss"}"')
dss.text(f'Redirect "{WORK_DIR / "UFSM_chaves.dss"}"')
dss.text(f'Redirect "{WORK_DIR / "UFSM_caps.dss"}"')
dss.text(f'Redirect "{WORK_DIR / "UFSM_trafos_medidos.dss"}"')
dss.text(f'Redirect "{WORK_DIR / "UFSM_trafos_cargas_especiais.dss"}"')
dss.text(f'Redirect "{WORK_DIR / "UFSM_trafos_estimados.dss"}"')
dss.text(f'Redirect "{WORK_DIR / "UFSM_cargas_medidas.dss"}"')
dss.text(f'Redirect "{WORK_DIR / "UFSM_cargas_especiais.dss"}"')
dss.text(f'Redirect "{WORK_DIR / "UFSM_cargas_estimadas_com_residuo_sim_2.dss"}"')

# pasta de exportacao dos monitores e meter
dss.text(f'Set DataPath="{SIM_DIR}"')

dss.text("New Monitor.GERAL element=line.0015_0016 terminal=1 mode=1 ppolar=no")
dss.text("New Energymeter.GERAL element=line.0015_0016 terminal=1")

dss.text("Set VoltageBases=[13.8,0.38,0.22]")
dss.text("CalcVoltageBases")
dss.text("Set Mode=Yearly Hour=0 Sec=0 StepSize=0.25h Number=35040")
dss.text("Solve")

for mon_name in MON_NAMES:
    dss.text(f"Export Monitors {mon_name}")

    fp = find_exported_monitor_file(SIM_DIR, mon_name)
    dst = SIM_DIR / f"UFSM_Mon_{mon_name}_1.csv"

    if fp.resolve() != dst.resolve():
        if dst.exists():
            dst.unlink()
        shutil.move(str(fp), str(dst))

dss.text("Export Meter /m")
print("Concluido. Monitores exportados em:", SIM_DIR)

# %% Celula 034 – Unificar fases (P/Q 3f) de TODOS os Monitores e salvar em "Simulacao 002"
# =============================================================================
# Lê em:  Simulacao 002/UFSM_Mon_<MON_NAME>_1.csv
# Gera em: Simulacao 002/Curva_de_Carga_<MON_NAME>_sim_2.csv
# Aplica shift anual unico para a DIREITA
# =============================================================================

import os
from pathlib import Path
import numpy as np
import pandas as pd

WORK_DIR = Path(r"C:\GitHub\determinar_modelo")
SIM_DIR  = WORK_DIR / "Simulacao 002"
SIM_DIR.mkdir(parents=True, exist_ok=True)
os.chdir(WORK_DIR)

MON_NAMES = ["GERAL"]

EXPECTED_N = 35040
DT_H = 0.25
hora = np.round(np.arange(0.0, 8760.0, DT_H), 10)

def _clean_columns(cols):
    s = pd.Index(cols).astype(str)
    return (
        s.str.replace("\ufeff", "", regex=False)
         .str.replace("\t", " ", regex=False)
         .str.strip()
         .str.replace(r"\s+", " ", regex=True)
    )

def process_monitor(mon_name: str) -> Path:
    mon_fp = SIM_DIR / f"UFSM_Mon_{mon_name}_1.csv"
    out_fp = SIM_DIR / f"Curva_de_Carga_{mon_name}_sim_2.csv"

    if not mon_fp.exists():
        raise FileNotFoundError(f"Monitor CSV not found: {mon_fp}")

    mon = pd.read_csv(mon_fp, encoding="utf-8-sig", sep=None, engine="python")
    mon.columns = _clean_columns(mon.columns)

    needed = [
        "P1 (kW)", "Q1 (kvar)",
        "P2 (kW)", "Q2 (kvar)",
        "P3 (kW)", "Q3 (kvar)",
    ]
    missing = [c for c in needed if c not in mon.columns]
    if missing:
        raise ValueError(f"[{mon_name}] Missing monitor columns: {missing}\nDetected: {list(mon.columns)}")

    for c in needed:
        mon[c] = pd.to_numeric(mon[c], errors="coerce")

    if mon[needed].isna().any().any():
        bad = mon[needed].isna().sum()
        raise ValueError(f"[{mon_name}] NaN found after numeric conversion:\n{bad}")

    vals = pd.DataFrame({
        "P_3f_S": mon["P1 (kW)"] + mon["P2 (kW)"] + mon["P3 (kW)"],
        "Q_3f_S": mon["Q1 (kvar)"] + mon["Q2 (kvar)"] + mon["Q3 (kvar)"],
    }).to_numpy(copy=True)

    if len(vals) != EXPECTED_N:
        raise ValueError(f"[{mon_name}] Unexpected length: {len(vals)} rows (expected {EXPECTED_N}).")

    # Shift anual unico para a DIREITA:
    # duplica a 1a linha e remove a ultima
    vals = np.vstack([vals[0:1, :], vals[0:-1, :]])

    df_out = pd.DataFrame({
        "Hora_decimal": hora,
        "P_3f_S": vals[:, 0],
        "Q_3f_S": vals[:, 1],
    })

    if len(df_out) != EXPECTED_N:
        raise ValueError(f"[{mon_name}] Tamanho inesperado da curva final: {len(df_out)}")

    if abs(df_out["Hora_decimal"].iloc[0] - 0.0) > 1e-9:
        raise ValueError(f"[{mon_name}] Hora_decimal does not start at 0.0")
    if abs(df_out["Hora_decimal"].iloc[-1] - 8759.75) > 1e-9:
        raise ValueError(f"[{mon_name}] Hora_decimal last time is not 8759.75")
    if not np.allclose(np.diff(df_out["Hora_decimal"].values), DT_H, atol=1e-9):
        raise ValueError(f"[{mon_name}] Hora_decimal is not a uniform 0.25h grid after cleaning.")

    df_out.to_csv(out_fp, index=False, encoding="utf-8-sig")

    try:
        mon_fp.unlink()
    except Exception as e:
        raise RuntimeError(f"[{mon_name}] Could not delete monitor CSV: {e}")

    return out_fp

outs = []
for name in MON_NAMES:
    out_fp = process_monitor(name)
    outs.append(out_fp)
    print(f"[OK] {name} -> {out_fp.name}")

print("\nCONCLUIDO. Arquivos gerados em:", SIM_DIR)
print("Total:", len(outs))
print("[INFO] Shift anual unico aplicado para a DIREITA em todos os monitores.")

# %% Celula 035 - Estatísticas comparativas RGE vs SIM2 (2025)  [SAÍDA EM: Simulacao 002]

from pathlib import Path
import numpy as np
import pandas as pd

WORK_DIR = Path(r"C:\GitHub\determinar_modelo")

# --- pasta da Simulação II ---
SIM2_DIR = WORK_DIR / "Simulacao 002"
SIM2_DIR.mkdir(parents=True, exist_ok=True)

RGE_FP = WORK_DIR / "00_memoria_de_massa_RGE_15min_2025.csv"
SIM_FP = SIM2_DIR / "Curva_de_Carga_GERAL_sim_2.csv"

OUT_RESUMO = SIM2_DIR / "validacao_SIM2_resumo.csv"
OUT_PICOS  = SIM2_DIR / "validacao_SIM2_picos_mensais.csv"

DT_H = 0.25
N = 35040
grid = np.round(np.arange(0.0, 8760.0, 0.25), 2)

# ---------- leitura ----------
rge = pd.read_csv(RGE_FP, encoding="utf-8-sig", sep=None, engine="python")
sim = pd.read_csv(SIM_FP, encoding="utf-8-sig", sep=None, engine="python")

# ---------- normalização de colunas ----------
def _norm_cols(df):
    df.columns = (
        df.columns.astype(str)
        .str.replace("\ufeff", "", regex=False)
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
    )
    return df

rge = _norm_cols(rge)
sim = _norm_cols(sim)

# ---------- seleção ----------
rge = rge[["Hora_decimal", "P_3f", "Q_3f"]].rename(columns={"P_3f": "P_RGE", "Q_3f": "Q_RGE"})
sim = sim[["Hora_decimal", "P_3f_S", "Q_3f_S"]].rename(columns={"P_3f_S": "P_SIM", "Q_3f_S": "Q_SIM"})

# ---------- numéricos ----------
for c in ["Hora_decimal", "P_RGE", "Q_RGE"]:
    rge[c] = pd.to_numeric(rge[c], errors="coerce")

for c in ["Hora_decimal", "P_SIM", "Q_SIM"]:
    sim[c] = pd.to_numeric(sim[c], errors="coerce")

rge = rge.dropna(subset=["Hora_decimal"]).drop_duplicates("Hora_decimal").sort_values("Hora_decimal")
sim = sim.dropna(subset=["Hora_decimal"]).drop_duplicates("Hora_decimal").sort_values("Hora_decimal")

# ---------- alinhamento ----------
base = pd.DataFrame({"Hora_decimal": grid})
df = base.merge(rge, on="Hora_decimal", how="left").merge(sim, on="Hora_decimal", how="left")

# HOLD forward
for c in ["P_RGE", "Q_RGE", "P_SIM", "Q_SIM"]:
    if pd.isna(df[c].iloc[0]):
        first = df[c].first_valid_index()
        if first is None:
            raise ValueError(f"Série inteira vazia para {c}")
        df.loc[0, c] = df.loc[first, c]
    df[c] = df[c].ffill()

if len(df) != N:
    raise ValueError(f"Tamanho inesperado após alinhamento: {len(df)} (esperado {N})")

# ---------- métricas ----------
def calc_stats(sim_s, ref_s):
    e = sim_s - ref_s

    NMAE = np.nan if ref_s.abs().sum() == 0 else float(e.abs().sum() / ref_s.abs().sum())

    RMSE = float(np.sqrt(np.mean(e.values ** 2)))
    rng = float(ref_s.max() - ref_s.min())
    NRMSE = np.nan if rng == 0 else float(RMSE / rng)

    E_sim = float(sim_s.sum() * DT_H)
    E_ref = float(ref_s.sum() * DT_H)
    eps_E = np.nan if E_ref == 0 else float(abs(E_sim - E_ref) / abs(E_ref))

    return NMAE, NRMSE, E_sim, E_ref, eps_E

NMAE_P, NRMSE_P, E_P_sim, E_P_rge, eps_E_P = calc_stats(df["P_SIM"], df["P_RGE"])
NMAE_Q, NRMSE_Q, E_Q_sim, E_Q_rge, eps_E_Q = calc_stats(df["Q_SIM"], df["Q_RGE"])

# ---------- picos mensais ----------
ts = pd.date_range("2025-01-01", periods=N, freq="15min")
dft = df.copy()
dft["timestamp"] = ts
dft = dft.set_index("timestamp")

mensal = pd.DataFrame({
    "P_SIM_max": dft["P_SIM"].resample("ME").max(),
    "P_RGE_max": dft["P_RGE"].resample("ME").max(),
    "Q_SIM_max": dft["Q_SIM"].resample("ME").max(),
    "Q_RGE_max": dft["Q_RGE"].resample("ME").max(),
})

mensal["Delta_Pmax"] = mensal["P_SIM_max"] - mensal["P_RGE_max"]
mensal["Delta_Qmax"] = mensal["Q_SIM_max"] - mensal["Q_RGE_max"]

mensal = mensal.reset_index()
mensal["Mes"] = mensal["timestamp"].dt.to_period("M").astype(str)

mensal = mensal[[
    "Mes",
    "P_SIM_max", "P_RGE_max", "Delta_Pmax",
    "Q_SIM_max", "Q_RGE_max", "Delta_Qmax"
]]

# ---------- resumo ----------
resumo = pd.DataFrame([
    ["P", "NMAE",              NMAE_P],
    ["P", "NRMSE",             NRMSE_P],
    ["P", "Energia_SIM_kWh",   E_P_sim],
    ["P", "Energia_RGE_kWh",   E_P_rge],
    ["P", "Erro_rel_energia",  eps_E_P],

    ["Q", "NMAE",              NMAE_Q],
    ["Q", "NRMSE",             NRMSE_Q],
    ["Q", "Energia_SIM_kVArh", E_Q_sim],
    ["Q", "Energia_RGE_kVArh", E_Q_rge],
    ["Q", "Erro_rel_energia",  eps_E_Q],
], columns=["Grandeza", "Metrica", "Valor"])

# ---------- salvar ----------
resumo.to_csv(OUT_RESUMO, index=False, float_format="%.6g", encoding="utf-8")
mensal.to_csv(OUT_PICOS, index=False, float_format="%.6g", encoding="utf-8")

print("✔ Resumo salvo em:", OUT_RESUMO)
print("✔ Picos mensais salvos em:", OUT_PICOS)



# %% Celula 036 - Calcular Curva_residuo_BT_sim_2 = RGE (raiz) - SIM (Simulacao 002)

import os
from pathlib import Path
import numpy as np
import pandas as pd

WORK_DIR = Path(r"C:\GitHub\determinar_modelo")
SIM_DIR  = WORK_DIR / "Simulacao 002"
os.chdir(WORK_DIR)

# RGE fica na raiz
RGE_FP = WORK_DIR / "00_memoria_de_massa_RGE_15min_2025.csv"

# SIM e saídas ficam na subpasta
SIM_FP = SIM_DIR / "Curva_de_Carga_GERAL_sim_2.csv"
OUT_FP = SIM_DIR / "Curva_residuo_BT_sim_2.csv"

for fp in [RGE_FP, SIM_FP]:
    if not fp.exists():
        raise FileNotFoundError(f"File not found: {fp}")

expected_n = 35040
grid = np.round(np.arange(0.0, 8760.0, 0.25), 2)

def _read(fp: Path) -> pd.DataFrame:
    df = pd.read_csv(fp, encoding="utf-8-sig", sep=None, engine="python")
    df.columns = (
        df.columns.astype(str)
        .str.replace("\ufeff", "", regex=False)
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
    )
    return df

def _to_grid(df: pd.DataFrame, hcol: str, pcol: str, qcol: str, tag: str) -> pd.DataFrame:
    out = df[[hcol, pcol, qcol]].copy()
    out[hcol] = pd.to_numeric(out[hcol], errors="coerce")
    out[pcol] = pd.to_numeric(out[pcol], errors="coerce")
    out[qcol] = pd.to_numeric(out[qcol], errors="coerce")

    out = out.dropna(subset=[hcol]).drop_duplicates(subset=[hcol]).sort_values(hcol).reset_index(drop=True)
    out = out[out[hcol] < 8760.0].copy()

    base = pd.DataFrame({"Hora_decimal": grid})
    out = base.merge(out, left_on="Hora_decimal", right_on=hcol, how="left")

    # HOLD inicial
    if pd.isna(out[pcol].iloc[0]) or pd.isna(out[qcol].iloc[0]):
        first_idx = out[pcol].first_valid_index()
        if first_idx is None:
            raise ValueError(f"[{tag}] Série inteira sem valores válidos.")
        out.loc[0, pcol] = out.loc[first_idx, pcol]
        out.loc[0, qcol] = out.loc[first_idx, qcol]

    out[pcol] = out[pcol].ffill()
    out[qcol] = out[qcol].ffill()

    if len(out) != expected_n:
        raise ValueError(f"[{tag}] Tamanho inesperado: {len(out)} (esperado {expected_n}).")

    return out[["Hora_decimal", pcol, qcol]].rename(columns={pcol: "P", qcol: "Q"})

rge_raw = _read(RGE_FP)
sim_raw = _read(SIM_FP)

req_rge = ["Hora_decimal", "P_3f", "Q_3f"]
req_sim = ["Hora_decimal", "P_3f_S", "Q_3f_S"]

for name, df, req in [("RGE", rge_raw, req_rge), ("SIM", sim_raw, req_sim)]:
    miss = [c for c in req if c not in df.columns]
    if miss:
        raise ValueError(f"Colunas faltando em {name}: {miss}. Disponíveis: {list(df.columns)}")

rge = _to_grid(rge_raw, "Hora_decimal", "P_3f", "Q_3f", "RGE")
sim = _to_grid(sim_raw, "Hora_decimal", "P_3f_S", "Q_3f_S", "SIM")

res = pd.DataFrame({"Hora_decimal": grid})
res["P_residuo_BT_kW"]   = rge["P"] - sim["P"]
res["Q_residuo_BT_kVAr"] = rge["Q"] - sim["Q"]

# garante pasta
SIM_DIR.mkdir(parents=True, exist_ok=True)

res.to_csv(OUT_FP, index=False, encoding="utf-8-sig")
print("DONE. Saved:", OUT_FP)

print("P_residuo_BT_kW   min/mean/max =",
      float(res["P_residuo_BT_kW"].min()),
      float(res["P_residuo_BT_kW"].mean()),
      float(res["P_residuo_BT_kW"].max()))

print("Q_residuo_BT_kVAr min/mean/max =",
      float(res["Q_residuo_BT_kVAr"].min()),
      float(res["Q_residuo_BT_kVAr"].mean()),
      float(res["Q_residuo_BT_kVAr"].max()))

# %% Celula 037 - Criar Curva_residuo_BT_por_kVA_sim_2 (fatores por soma das demandas estimadas)

import os
from pathlib import Path
import numpy as np
import pandas as pd

WORK_DIR = Path(r"C:\GitHub\determinar_modelo")
SIM_DIR  = WORK_DIR / "Simulacao 002"
os.chdir(WORK_DIR)

RES_FP  = SIM_DIR  / "Curva_residuo_BT_sim_2.csv"                 
EST_DIR = WORK_DIR / "22 Memoria de massa estimada com residuo para simulacao II dos trafos nao medidos 2025"
OUT_FP  = SIM_DIR  / "Curva_residuo_BT_por_kVA_sim_2.csv"         

SIM_DIR.mkdir(parents=True, exist_ok=True)

if not RES_FP.exists():  raise FileNotFoundError(RES_FP)
if not EST_DIR.exists(): raise FileNotFoundError(EST_DIR)

expected_n = 35040
grid = np.round(np.arange(0.0, 8760.0, 0.25), 2)

res = pd.read_csv(RES_FP, encoding="utf-8-sig", sep=None, engine="python")
res.columns = res.columns.astype(str).str.replace("\ufeff","",regex=False).str.strip().str.replace(r"\s+"," ",regex=True)

need_res = ["Hora_decimal", "P_residuo_BT_kW", "Q_residuo_BT_kVAr"]
miss = [c for c in need_res if c not in res.columns]
if miss:
    raise ValueError(f"Colunas faltando em {RES_FP.name}: {miss}")

for c in need_res:
    res[c] = pd.to_numeric(res[c], errors="coerce")

res = res.dropna(subset=["Hora_decimal"]).drop_duplicates("Hora_decimal", keep="first").sort_values("Hora_decimal").reset_index(drop=True)
res = res[res["Hora_decimal"] < 8760.0].copy()

if len(res) != expected_n:
    raise ValueError(f"{RES_FP.name}: tamanho {len(res)} != {expected_n}")
if not np.allclose(res["Hora_decimal"].to_numpy(dtype=float), grid, atol=1e-9):
    raise ValueError(f"{RES_FP.name}: Hora_decimal desalinhado")

csvs = sorted(EST_DIR.glob("*.csv"))
if not csvs:
    raise FileNotFoundError(f"Nenhum CSV em {EST_DIR}")

sumP = np.zeros(expected_n, dtype=float)
sumAbsQ = np.zeros(expected_n, dtype=float)

def _read_curve(fp: Path) -> pd.DataFrame:
    df = pd.read_csv(fp, encoding="utf-8-sig", sep=None, engine="python")
    df.columns = df.columns.astype(str).str.replace("\ufeff","",regex=False).str.strip().str.replace(r"\s+"," ",regex=True)
    needed = ["Hora_decimal","P_3f","Q_3f"]
    miss = [c for c in needed if c not in df.columns]
    if miss:
        raise ValueError(f"{fp.name}: colunas faltando {miss}")

    for c in needed:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=["Hora_decimal"]).drop_duplicates("Hora_decimal", keep="first").sort_values("Hora_decimal").reset_index(drop=True)
    df = df[df["Hora_decimal"] < 8760.0].copy()

    # garante 0.0 (HOLD do primeiro)
    if not (df["Hora_decimal"] == 0.0).any():
        first = df.iloc[0]
        df = pd.concat([pd.DataFrame([{
            "Hora_decimal": 0.0,
            "P_3f": float(first["P_3f"]),
            "Q_3f": float(first["Q_3f"]),
        }]), df], ignore_index=True).sort_values("Hora_decimal").drop_duplicates("Hora_decimal", keep="first").reset_index(drop=True)

    if len(df) != expected_n:
        raise ValueError(f"{fp.name}: tamanho {len(df)} != {expected_n}")
    if not np.allclose(df["Hora_decimal"].to_numpy(dtype=float), grid, atol=1e-9):
        raise ValueError(f"{fp.name}: Hora_decimal desalinhado")

    return df[["Hora_decimal","P_3f","Q_3f"]]

for fp in csvs:
    dfc = _read_curve(fp)
    sumP += dfc["P_3f"].to_numpy(dtype=float)
    sumAbsQ += np.abs(dfc["Q_3f"].to_numpy(dtype=float))

EPS = 1e-9
resP = res["P_residuo_BT_kW"].to_numpy(dtype=float)
resQ = res["Q_residuo_BT_kVAr"].to_numpy(dtype=float)

fP = np.zeros_like(resP)
maskP = np.abs(sumP) > EPS
fP[maskP] = resP[maskP] / sumP[maskP]

fQ = np.zeros_like(resQ)
maskQ = sumAbsQ > EPS
fQ[maskQ] = resQ[maskQ] / sumAbsQ[maskQ]

out = pd.DataFrame({
    "Hora_decimal": grid,
    "P_residuo_BT_kW": resP,
    "Q_residuo_BT_kVAr": resQ,
    "sumP_est_kW": sumP,
    "sumAbsQ_est_kVAr": sumAbsQ,
    "fatorP_por_sumP": fP,
    "fatorQ_por_sumAbsQ": fQ,
})

out.to_csv(OUT_FP, index=False, encoding="utf-8-sig")
print("DONE. Saved:", OUT_FP)
print("Curvas estimadas lidas:", len(csvs))

# %% Celula 038 - Aplicar resíduo proporcional nas curvas estimadas e salvar em 23... (NA RAIZ)

import os
from pathlib import Path
import numpy as np
import pandas as pd

WORK_DIR = Path(r"C:\GitHub\determinar_modelo")
SIM_DIR  = WORK_DIR / "Simulacao 002"
os.chdir(WORK_DIR)

# FATOR vem da subpasta
FACT_FP = SIM_DIR / "Curva_residuo_BT_por_kVA_sim_2.csv"

# Curvas usadas na segunda simulacao
SRC_DIR = WORK_DIR / "22 Memoria de massa estimada com residuo para simulacao II dos trafos nao medidos 2025"

# Saida 23 na raiz
OUT_DIR = WORK_DIR / "23 Memoria de massa estimada com residuo para simulacao III dos trafos nao medidos 2025"
OUT_DIR.mkdir(parents=True, exist_ok=True)

if not FACT_FP.exists(): raise FileNotFoundError(FACT_FP)
if not SRC_DIR.exists(): raise FileNotFoundError(SRC_DIR)

expected_n = 35040
grid = np.round(np.arange(0.0, 8760.0, 0.25), 2)

fact = pd.read_csv(FACT_FP, encoding="utf-8-sig", sep=None, engine="python")
fact.columns = fact.columns.astype(str).str.replace("\ufeff","",regex=False).str.strip().str.replace(r"\s+"," ",regex=True)

need = ["Hora_decimal","fatorP_por_sumP","fatorQ_por_sumAbsQ"]
miss = [c for c in need if c not in fact.columns]
if miss:
    raise ValueError(f"Colunas faltando em {FACT_FP.name}: {miss}")

for c in need:
    fact[c] = pd.to_numeric(fact[c], errors="coerce")

fact = fact.dropna(subset=["Hora_decimal"]).drop_duplicates("Hora_decimal").sort_values("Hora_decimal")
fact = fact[fact["Hora_decimal"] < 8760.0].reset_index(drop=True)

if len(fact) != expected_n:
    raise ValueError(f"{FACT_FP.name}: tamanho {len(fact)} != {expected_n}")
if not np.allclose(fact["Hora_decimal"].to_numpy(dtype=float), grid, atol=1e-9):
    raise ValueError(f"{FACT_FP.name}: Hora_decimal desalinhado")

fP = fact["fatorP_por_sumP"].to_numpy(dtype=float)
fQ = fact["fatorQ_por_sumAbsQ"].to_numpy(dtype=float)

def _read_curve(fp: Path) -> pd.DataFrame:
    df = pd.read_csv(fp, encoding="utf-8-sig", sep=None, engine="python")
    df.columns = df.columns.astype(str).str.replace("\ufeff","",regex=False).str.strip().str.replace(r"\s+"," ",regex=True)

    for c in ["Hora_decimal","P_3f","Q_3f"]:
        if c not in df.columns:
            raise ValueError(f"{fp.name}: coluna faltando {c}")
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=["Hora_decimal"]).drop_duplicates("Hora_decimal").sort_values("Hora_decimal")
    df = df[df["Hora_decimal"] < 8760.0].reset_index(drop=True)

    if not (df["Hora_decimal"] == 0.0).any():
        first = df.iloc[0]
        df = pd.concat([pd.DataFrame([{
            "Hora_decimal": 0.0,
            "P_3f": float(first["P_3f"]),
            "Q_3f": float(first["Q_3f"]),
        }]), df], ignore_index=True).sort_values("Hora_decimal").drop_duplicates("Hora_decimal").reset_index(drop=True)

    if len(df) != expected_n:
        raise ValueError(f"{fp.name}: tamanho {len(df)} != {expected_n}")
    if not np.allclose(df["Hora_decimal"].to_numpy(dtype=float), grid, atol=1e-9):
        raise ValueError(f"{fp.name}: Hora_decimal desalinhado")

    return df[["Hora_decimal","P_3f","Q_3f"]]

csvs = sorted(SRC_DIR.glob("*.csv"))
if not csvs:
    raise FileNotFoundError(f"Nenhum CSV em {SRC_DIR}")

p_alocado_total = np.zeros(expected_n)
q_alocado_total = np.zeros(expected_n)
ok, fail = 0, 0
for fp in csvs:
    try:
        base = _read_curve(fp)
        Pi = base["P_3f"].to_numpy(dtype=float)
        Qi = base["Q_3f"].to_numpy(dtype=float)

        dP = Pi * fP

        # fQ ja contem o sinal do residuo RGE - SIM.
        # Multiplicar por sign(Qi) invertia a correcao nas cargas capacitivas.
        dQ = np.abs(Qi) * fQ
        q_alvo = Qi + dQ
        # Preserva a natureza indutiva/capacitiva; saturacao em zero.
        # A parcela nao alocada fica registrada para posterior verificacao.
        q_corr = np.where(Qi > 0, np.maximum(q_alvo, 0.0),
                          np.where(Qi < 0, np.minimum(q_alvo, 0.0), 0.0))
        p_corr = np.maximum(Pi + dP, 0.0)
        p_alocado_total += p_corr - Pi
        q_alocado_total += q_corr - Qi
        base["P_3f"] = p_corr
        base["Q_3f"] = q_corr

        out_fp = OUT_DIR / fp.name
        base.to_csv(out_fp, index=False, encoding="utf-8-sig")
        ok += 1
    except Exception as e:
        print("[FAIL]", fp.name, "->", e)
        fail += 1

print("DONE. OK:", ok, "FAIL:", fail)
print("Saved in:", OUT_DIR)

# Diagnostico da segunda correcao: nao representa ainda o residuo no PAC.
if fail:
    raise RuntimeError("Falha na correcao de curvas. Nao prossiga para a simulacao III.")
res_original = pd.read_csv(SIM_DIR / "Curva_residuo_BT_sim_2.csv", encoding="utf-8-sig")
diag1 = pd.DataFrame({"Hora_decimal": grid, "P_alocado_kW": p_alocado_total,
                      "Q_alocado_kVAr": q_alocado_total})
diag1["P_nao_alocado_kW"] = res_original["P_residuo_BT_kW"].to_numpy() - p_alocado_total
diag1["Q_nao_alocado_kVAr"] = res_original["Q_residuo_BT_kVAr"].to_numpy() - q_alocado_total
diag1.to_csv(SIM_DIR / "Correcao_residuo_sim_2_diagnostico.csv", index=False, encoding="utf-8-sig")

# %% Celula 039 - Converter curvas com resíduo para pu

import os, re
from pathlib import Path
import pandas as pd
import numpy as np

WORK_DIR = Path(r"C:\GitHub\determinar_modelo")
os.chdir(WORK_DIR)

IN_DIR  = WORK_DIR / "23 Memoria de massa estimada com residuo para simulacao III dos trafos nao medidos 2025"
OUT_DIR = WORK_DIR / "Cargas_Estimadas_com_residuo_sim_3"
OUT_DIR.mkdir(parents=True, exist_ok=True)

csv_files = sorted(IN_DIR.glob("*.csv"))
if not csv_files:
    raise FileNotFoundError(f"Nenhum CSV em {IN_DIR}")

re_kva = re.compile(r"_(\d+(?:\.\d+)?)kVA", re.I)

def kva_do_nome(nome: str) -> float:
    m = re_kva.search(nome)
    if not m:
        raise ValueError(f"kVA não encontrado no nome: {nome}")
    kva = float(m.group(1))
    if kva <= 0:
        raise ValueError(f"kVA inválido no nome: {nome}")
    return kva

expected_n = 35040
grid = np.round(np.arange(0.0, 8760.0, 0.25), 2)

n_ok, n_fail = 0, 0

for fp in csv_files:
    try:
        kva = kva_do_nome(fp.name)

        df = pd.read_csv(fp, encoding="utf-8", sep=None, engine="python")
        df.columns = (
            df.columns.astype(str)
            .str.replace("\ufeff", "", regex=False)
            .str.strip()
            .str.replace(r"\s+", " ", regex=True)
        )

        for c in ["Hora_decimal", "P_3f", "Q_3f"]:
            if c not in df.columns:
                raise ValueError(f"{fp.name}: coluna faltando {c}")
            df[c] = pd.to_numeric(df[c], errors="coerce")

        df = (
            df.dropna(subset=["Hora_decimal", "P_3f", "Q_3f"])
              .query("Hora_decimal < 8760.0")
              .sort_values("Hora_decimal")
              .drop_duplicates("Hora_decimal")
              .reset_index(drop=True)
        )

        if len(df) != expected_n:
            raise ValueError(f"{fp.name}: tamanho {len(df)} != {expected_n}")

        if not np.allclose(df["Hora_decimal"].to_numpy(dtype=float), grid, atol=1e-9):
            raise ValueError(f"{fp.name}: Hora_decimal desalinhado")

        # ---- conversão para pu ----
        df["P_pu"] = df["P_3f"] / kva
        df["Q_pu"] = df["Q_3f"] / kva

        # ---- saída compatível OpenDSS ----
        out_fp = OUT_DIR / (fp.stem + "_pu.csv")

        df_out = df[["Hora_decimal", "P_pu", "Q_pu"]].copy()

        # força ponto decimal e precisão fixa
        for col in df_out.columns:
            df_out[col] = df_out[col].map(lambda x: f"{x:.6f}")
       
        df_out.to_csv(
            out_fp,
            index=False,
            header=False,
            encoding="utf-8",
            lineterminator="\n"
        )


        n_ok += 1

    except Exception as e:
        print("[FAIL]", fp.name, "->", e)
        n_fail += 1

print("DONE. Gerados:", n_ok, "Falhas:", n_fail)
print("Saída em:", OUT_DIR)

if n_fail:
    raise RuntimeError("Falha na conversao PU. Corrija antes da simulacao III.")


# Gerar o DSS da terceira simulacao a partir das declaracoes da segunda.
# Mantem os nomes das curvas; troca somente a pasta dos CSVs PU.
DSS3_FP = WORK_DIR / "UFSM_cargas_estimadas_com_residuo_sim_3.dss"
pu_gerados = {(fp.stem + "_pu.csv").casefold(): OUT_DIR / (fp.stem + "_pu.csv") for fp in csv_files}
template_fp = WORK_DIR / "UFSM_cargas_estimadas_com_residuo_sim_2.dss"
try:
    texto_dss = template_fp.read_text(encoding="utf-8-sig")
except UnicodeDecodeError:
    texto_dss = template_fp.read_text(encoding="cp1252")
refs_usadas = set()


def trocar_csv3(m):
    caminho = m[2].strip('"\'').replace("\\", "/")
    if not caminho.lower().endswith(".csv"):
        return m[0]
    nome = caminho.rsplit("/", 1)[-1].casefold()
    if nome not in pu_gerados:
        raise FileNotFoundError(f"CSV do DSS sem correspondente na SIM3: {caminho}")
    refs_usadas.add(nome)
    return m[1] + '"' + pu_gerados[nome].resolve().as_posix() + '"'


padrao_csv3 = r'''(\b(?:csvfile|file|pqcsvfile)\s*=\s*)("[^"]*"|'[^']*'|[^,\s)]+)'''
texto_dss = re.sub(padrao_csv3, trocar_csv3, texto_dss, flags=re.I)
if refs_usadas != set(pu_gerados):
    raise ValueError("DSS nao referencia todas as curvas geradas: " + str(set(pu_gerados) - refs_usadas))
DSS3_FP.write_text(texto_dss, encoding="utf-8")
print("DSS da terceira simulacao:", DSS3_FP)


# %% Celula 040 – TERCEIRA SIMULACAO OPEN-DSS (UFSM 2025)

import os
import shutil
from pathlib import Path
from py_dss_interface import DSS

WORK_DIR = Path(r"C:\GitHub\determinar_modelo")
SIM_DIR  = WORK_DIR / "Simulacao 003"
SIM_DIR.mkdir(parents=True, exist_ok=True)

os.chdir(WORK_DIR)

MON_NAMES = ["GERAL"]

def find_exported_monitor_file(export_dir: Path, mon_name: str) -> Path:
    # Comparacao exata sem diferenciar maiusculas/minusculas (Windows/Linux).
    wanted = f"ufsm_mon_{mon_name}_1.csv".casefold()
    encontrados = [p for p in export_dir.iterdir() if p.name.casefold() == wanted]
    if len(encontrados) != 1:
        raise FileNotFoundError(f"Exportacao ausente/ambigua: {wanted}: {encontrados}")
    return encontrados[0]

if not (WORK_DIR / "UFSM_cargas_estimadas_com_residuo_sim_3.dss").exists():
    raise FileNotFoundError("Execute a celula 038 antes da terceira simulacao.")

for raw in SIM_DIR.glob("*.csv"):
    if raw.name.casefold() in {f"ufsm_mon_{m}_1.csv".casefold() for m in MON_NAMES}:
        raw.unlink()

dss = DSS()
dss.text("Clear")
dss.text(f'cd "{WORK_DIR}"')

# arquivos de entrada com caminho absoluto
dss.text(
    "New Circuit.UFSM bus1=0010 basekv=13.8 phases=3 "
    "puZ0=[1.24 2.50] puZ1=[0.43 0.98] puZ2=[0.43 0.98]"
)
dss.text(f'Redirect "{WORK_DIR / "UFSM_wiredata.dss"}"')
dss.text(f'Redirect "{WORK_DIR / "UFSM_linhas.dss"}"')
dss.text(f'Redirect "{WORK_DIR / "UFSM_chaves.dss"}"')
dss.text(f'Redirect "{WORK_DIR / "UFSM_caps.dss"}"')
dss.text(f'Redirect "{WORK_DIR / "UFSM_trafos_medidos.dss"}"')
dss.text(f'Redirect "{WORK_DIR / "UFSM_trafos_cargas_especiais.dss"}"')
dss.text(f'Redirect "{WORK_DIR / "UFSM_trafos_estimados.dss"}"')
dss.text(f'Redirect "{WORK_DIR / "UFSM_cargas_medidas.dss"}"')
dss.text(f'Redirect "{WORK_DIR / "UFSM_cargas_especiais.dss"}"')
dss.text(f'Redirect "{WORK_DIR / "UFSM_cargas_estimadas_com_residuo_sim_3.dss"}"')

# pasta de exportacao dos monitores e meter
dss.text(f'Set DataPath="{SIM_DIR}"')

dss.text("New Monitor.GERAL element=line.0015_0016 terminal=1 mode=1 ppolar=no")
dss.text("New Energymeter.GERAL element=line.0015_0016 terminal=1")

dss.text("Set VoltageBases=[13.8,0.38,0.22]")
dss.text("CalcVoltageBases")
dss.text("Set Mode=Yearly Hour=0 Sec=0 StepSize=0.25h Number=35040")
dss.text("Solve")

for mon_name in MON_NAMES:
    dss.text(f"Export Monitors {mon_name}")

    fp = find_exported_monitor_file(SIM_DIR, mon_name)
    dst = SIM_DIR / f"UFSM_Mon_{mon_name}_1.csv"

    if fp.resolve() != dst.resolve():
        if dst.exists():
            dst.unlink()
        shutil.move(str(fp), str(dst))

dss.text("Export Meter /m")
print("Concluido. Monitores exportados em:", SIM_DIR)


# %% Celula 041 – Unificar fases (P/Q 3f) de TODOS os Monitores e salvar em "Simulacao 003"
# =============================================================================
# Lê em:  Simulacao 003/UFSM_Mon_<MON_NAME>_1.csv
# Gera em: Simulacao 003/Curva_de_Carga_<MON_NAME>_sim_3.csv
# Aplica shift anual unico para a DIREITA
# =============================================================================

import os
from pathlib import Path
import numpy as np
import pandas as pd

WORK_DIR = Path(r"C:\GitHub\determinar_modelo")
SIM_DIR  = WORK_DIR / "Simulacao 003"
SIM_DIR.mkdir(parents=True, exist_ok=True)
os.chdir(WORK_DIR)

MON_NAMES = ["GERAL"]

EXPECTED_N = 35040
DT_H = 0.25
hora = np.round(np.arange(0.0, 8760.0, DT_H), 10)

def _clean_columns(cols):
    s = pd.Index(cols).astype(str)
    return (
        s.str.replace("\ufeff", "", regex=False)
         .str.replace("\t", " ", regex=False)
         .str.strip()
         .str.replace(r"\s+", " ", regex=True)
    )

def process_monitor(mon_name: str) -> Path:
    mon_fp = SIM_DIR / f"UFSM_Mon_{mon_name}_1.csv"
    out_fp = SIM_DIR / f"Curva_de_Carga_{mon_name}_sim_3.csv"

    if not mon_fp.exists():
        raise FileNotFoundError(f"Monitor CSV not found: {mon_fp}")

    mon = pd.read_csv(mon_fp, encoding="utf-8-sig", sep=None, engine="python")
    mon.columns = _clean_columns(mon.columns)

    needed = [
        "P1 (kW)", "Q1 (kvar)",
        "P2 (kW)", "Q2 (kvar)",
        "P3 (kW)", "Q3 (kvar)",
    ]
    missing = [c for c in needed if c not in mon.columns]
    if missing:
        raise ValueError(f"[{mon_name}] Missing monitor columns: {missing}\nDetected: {list(mon.columns)}")

    for c in needed:
        mon[c] = pd.to_numeric(mon[c], errors="coerce")

    if mon[needed].isna().any().any():
        bad = mon[needed].isna().sum()
        raise ValueError(f"[{mon_name}] NaN found after numeric conversion:\n{bad}")

    vals = pd.DataFrame({
        "P_3f_S": mon["P1 (kW)"] + mon["P2 (kW)"] + mon["P3 (kW)"],
        "Q_3f_S": mon["Q1 (kvar)"] + mon["Q2 (kvar)"] + mon["Q3 (kvar)"],
    }).to_numpy(copy=True)

    if len(vals) != EXPECTED_N:
        raise ValueError(f"[{mon_name}] Unexpected length: {len(vals)} rows (expected {EXPECTED_N}).")

    # Shift anual unico para a DIREITA:
    # duplica a 1a linha e remove a ultima
    vals = np.vstack([vals[0:1, :], vals[0:-1, :]])

    df_out = pd.DataFrame({
        "Hora_decimal": hora,
        "P_3f_S": vals[:, 0],
        "Q_3f_S": vals[:, 1],
    })

    if len(df_out) != EXPECTED_N:
        raise ValueError(f"[{mon_name}] Tamanho inesperado da curva final: {len(df_out)}")

    if abs(df_out["Hora_decimal"].iloc[0] - 0.0) > 1e-9:
        raise ValueError(f"[{mon_name}] Hora_decimal does not start at 0.0")
    if abs(df_out["Hora_decimal"].iloc[-1] - 8759.75) > 1e-9:
        raise ValueError(f"[{mon_name}] Hora_decimal last time is not 8759.75")
    if not np.allclose(np.diff(df_out["Hora_decimal"].values), DT_H, atol=1e-9):
        raise ValueError(f"[{mon_name}] Hora_decimal is not a uniform 0.25h grid after cleaning.")

    df_out.to_csv(out_fp, index=False, encoding="utf-8-sig")

    # Preserva o monitor bruto para auditoria e reexecucao da celula.

    return out_fp

outs = []
for name in MON_NAMES:
    out_fp = process_monitor(name)
    outs.append(out_fp)
    print(f"[OK] {name} -> {out_fp.name}")

print("\nCONCLUIDO. Arquivos gerados em:", SIM_DIR)
print("Total:", len(outs))
print("[INFO] Shift anual unico aplicado para a DIREITA em todos os monitores.")


# %% Celula 042 - Estatísticas comparativas RGE vs SIM3 (2025)  [SAÍDA EM: Simulacao 003]

from pathlib import Path
import numpy as np
import pandas as pd

WORK_DIR = Path(r"C:\GitHub\determinar_modelo")

# --- pasta da Simulação III ---
SIM3_DIR = WORK_DIR / "Simulacao 003"
SIM3_DIR.mkdir(parents=True, exist_ok=True)

RGE_FP = WORK_DIR / "00_memoria_de_massa_RGE_15min_2025.csv"
SIM_FP = SIM3_DIR / "Curva_de_Carga_GERAL_sim_3.csv"

OUT_RESUMO = SIM3_DIR / "validacao_SIM3_resumo.csv"
OUT_PICOS  = SIM3_DIR / "validacao_SIM3_picos_mensais.csv"

DT_H = 0.25
N = 35040
grid = np.round(np.arange(0.0, 8760.0, 0.25), 2)

# ---------- leitura ----------
rge = pd.read_csv(RGE_FP, encoding="utf-8-sig", sep=None, engine="python")
sim = pd.read_csv(SIM_FP, encoding="utf-8-sig", sep=None, engine="python")

# ---------- normalização de colunas ----------
def _norm_cols(df):
    df.columns = (
        df.columns.astype(str)
        .str.replace("\ufeff", "", regex=False)
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
    )
    return df

rge = _norm_cols(rge)
sim = _norm_cols(sim)

# ---------- seleção ----------
rge = rge[["Hora_decimal", "P_3f", "Q_3f"]].rename(columns={"P_3f": "P_RGE", "Q_3f": "Q_RGE"})
sim = sim[["Hora_decimal", "P_3f_S", "Q_3f_S"]].rename(columns={"P_3f_S": "P_SIM", "Q_3f_S": "Q_SIM"})

# ---------- numéricos ----------
for c in ["Hora_decimal", "P_RGE", "Q_RGE"]:
    rge[c] = pd.to_numeric(rge[c], errors="coerce")

for c in ["Hora_decimal", "P_SIM", "Q_SIM"]:
    sim[c] = pd.to_numeric(sim[c], errors="coerce")

rge = rge.dropna(subset=["Hora_decimal"]).drop_duplicates("Hora_decimal").sort_values("Hora_decimal")
sim = sim.dropna(subset=["Hora_decimal"]).drop_duplicates("Hora_decimal").sort_values("Hora_decimal")

# ---------- alinhamento ----------
base = pd.DataFrame({"Hora_decimal": grid})
df = base.merge(rge, on="Hora_decimal", how="left").merge(sim, on="Hora_decimal", how="left")

# HOLD forward
for c in ["P_RGE", "Q_RGE", "P_SIM", "Q_SIM"]:
    if pd.isna(df[c].iloc[0]):
        first = df[c].first_valid_index()
        if first is None:
            raise ValueError(f"Série inteira vazia para {c}")
        df.loc[0, c] = df.loc[first, c]
    df[c] = df[c].ffill()

if len(df) != N:
    raise ValueError(f"Tamanho inesperado após alinhamento: {len(df)} (esperado {N})")

# ---------- métricas ----------
def calc_stats(sim_s, ref_s):
    e = sim_s - ref_s

    NMAE = np.nan if ref_s.abs().sum() == 0 else float(e.abs().sum() / ref_s.abs().sum())

    RMSE = float(np.sqrt(np.mean(e.values ** 2)))
    rng = float(ref_s.max() - ref_s.min())
    NRMSE = np.nan if rng == 0 else float(RMSE / rng)

    E_sim = float(sim_s.sum() * DT_H)
    E_ref = float(ref_s.sum() * DT_H)
    eps_E = np.nan if E_ref == 0 else float(abs(E_sim - E_ref) / abs(E_ref))

    return NMAE, NRMSE, E_sim, E_ref, eps_E

NMAE_P, NRMSE_P, E_P_sim, E_P_rge, eps_E_P = calc_stats(df["P_SIM"], df["P_RGE"])
NMAE_Q, NRMSE_Q, E_Q_sim, E_Q_rge, eps_E_Q = calc_stats(df["Q_SIM"], df["Q_RGE"])

# ---------- picos mensais ----------
ts = pd.date_range("2025-01-01", periods=N, freq="15min")
dft = df.copy()
dft["timestamp"] = ts
dft = dft.set_index("timestamp")

mensal = pd.DataFrame({
    "P_SIM_max": dft["P_SIM"].resample("ME").max(),
    "P_RGE_max": dft["P_RGE"].resample("ME").max(),
    "Q_SIM_max": dft["Q_SIM"].resample("ME").max(),
    "Q_RGE_max": dft["Q_RGE"].resample("ME").max(),
})

mensal["Delta_Pmax"] = mensal["P_SIM_max"] - mensal["P_RGE_max"]
mensal["Delta_Qmax"] = mensal["Q_SIM_max"] - mensal["Q_RGE_max"]

mensal = mensal.reset_index()
mensal["Mes"] = mensal["timestamp"].dt.to_period("M").astype(str)

mensal = mensal[[
    "Mes",
    "P_SIM_max", "P_RGE_max", "Delta_Pmax",
    "Q_SIM_max", "Q_RGE_max", "Delta_Qmax"
]]

# ---------- resumo ----------
resumo = pd.DataFrame([
    ["P", "NMAE",              NMAE_P],
    ["P", "NRMSE",             NRMSE_P],
    ["P", "Energia_SIM_kWh",   E_P_sim],
    ["P", "Energia_RGE_kWh",   E_P_rge],
    ["P", "Erro_rel_energia",  eps_E_P],

    ["Q", "NMAE",              NMAE_Q],
    ["Q", "NRMSE",             NRMSE_Q],
    ["Q", "Energia_SIM_kVArh", E_Q_sim],
    ["Q", "Energia_RGE_kVArh", E_Q_rge],
    ["Q", "Erro_rel_energia",  eps_E_Q],
], columns=["Grandeza", "Metrica", "Valor"])

# ---------- salvar ----------
resumo.to_csv(OUT_RESUMO, index=False, float_format="%.6g", encoding="utf-8")
mensal.to_csv(OUT_PICOS, index=False, float_format="%.6g", encoding="utf-8")

print("✔ Resumo salvo em:", OUT_RESUMO)
print("✔ Picos mensais salvos em:", OUT_PICOS)



TOLERANCIA = 0.05  # 5% em forma decimal.
# Complementos da celula 041: meta conjunta, comparacao e graficos.
criterios = resumo[resumo.Metrica.isin(["NMAE", "NRMSE", "Erro_rel_energia"])].copy()
criterios["Valor_percentual"] = criterios.Valor * 100
criterios["Limite_percentual"] = TOLERANCIA * 100
criterios["Atende"] = np.isfinite(criterios.Valor) & (criterios.Valor <= TOLERANCIA)
criterios.to_csv(SIM3_DIR / "validacao_SIM3_criterios_5pct.csv", index=False, encoding="utf-8-sig")
print(criterios.to_string(index=False))
print("Meta conjunta no PAC:", "ATENDIDA" if criterios.Atende.all() else "NAO ATENDIDA")
print("Aderencia agregada nao valida as curvas locais nem as tensoes internas.")
for grandeza in ["P", "Q"]:
    ref = mensal[f"{grandeza}_RGE_max"].abs()
    mensal[f"Erro_{grandeza}max_percentual"] = mensal[f"Delta_{grandeza}max"].abs().div(ref.where(ref > 0)) * 100
mensal.to_csv(OUT_PICOS, index=False, encoding="utf-8-sig")
comparacoes = []
for numero in (1, 2, 3):
    fp = WORK_DIR / f"Simulacao {numero:03d}" / f"validacao_SIM{numero}_resumo.csv"
    if fp.exists():
        tabela = pd.read_csv(fp)
        tabela = tabela[tabela.Metrica.isin(["NMAE", "NRMSE", "Erro_rel_energia"])].copy()
        tabela["Simulacao"] = numero
        tabela["Valor_percentual"] = tabela.Valor * 100
        comparacoes.append(tabela)
    else:
        print(f"[AVISO] Execute a analise estatistica da SIM{numero}: {fp}")
pd.concat(comparacoes, ignore_index=True).to_csv(
    SIM3_DIR / "Comparacao_SIM1_SIM2_SIM3.csv", index=False, encoding="utf-8-sig")

import matplotlib.pyplot as plt
fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
for ax, g, unidade in zip(axes, ["P", "Q"], ["kW", "kVAr"]):
    ax.plot(ts, df[f"{g}_RGE"], label="RGE", linewidth=0.6)
    ax.plot(ts, df[f"{g}_SIM"], label="Simulacao 3", linewidth=0.6, alpha=0.75)
    ax.set_ylabel(f"{g} ({unidade})")
    ax.grid(alpha=0.3)
    ax.legend()
axes[0].set_title("Comparacao no PAC - terceira simulacao")
fig.tight_layout()
fig.savefig(SIM3_DIR / "Comparacao_RGE_SIM3.png", dpi=180)
plt.close(fig)




# %% Celula 043 - Calcular Curva_residuo_BT_sim_3 = RGE (raiz) - SIM (Simulacao 003)

import os
from pathlib import Path
import numpy as np
import pandas as pd

WORK_DIR = Path(r"C:\GitHub\determinar_modelo")
SIM_DIR  = WORK_DIR / "Simulacao 003"
os.chdir(WORK_DIR)

# RGE fica na raiz
RGE_FP = WORK_DIR / "00_memoria_de_massa_RGE_15min_2025.csv"

# SIM e saídas ficam na subpasta
SIM_FP = SIM_DIR / "Curva_de_Carga_GERAL_sim_3.csv"
OUT_FP = SIM_DIR / "Curva_residuo_BT_sim_3.csv"

for fp in [RGE_FP, SIM_FP]:
    if not fp.exists():
        raise FileNotFoundError(f"File not found: {fp}")

expected_n = 35040
grid = np.round(np.arange(0.0, 8760.0, 0.25), 2)

def _read(fp: Path) -> pd.DataFrame:
    df = pd.read_csv(fp, encoding="utf-8-sig", sep=None, engine="python")
    df.columns = (
        df.columns.astype(str)
        .str.replace("\ufeff", "", regex=False)
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
    )
    return df

def _to_grid(df: pd.DataFrame, hcol: str, pcol: str, qcol: str, tag: str) -> pd.DataFrame:
    out = df[[hcol, pcol, qcol]].copy()
    out[hcol] = pd.to_numeric(out[hcol], errors="coerce")
    out[pcol] = pd.to_numeric(out[pcol], errors="coerce")
    out[qcol] = pd.to_numeric(out[qcol], errors="coerce")

    out = out.dropna(subset=[hcol]).drop_duplicates(subset=[hcol]).sort_values(hcol).reset_index(drop=True)
    out = out[out[hcol] < 8760.0].copy()

    base = pd.DataFrame({"Hora_decimal": grid})
    out = base.merge(out, left_on="Hora_decimal", right_on=hcol, how="left")

    # HOLD inicial
    if pd.isna(out[pcol].iloc[0]) or pd.isna(out[qcol].iloc[0]):
        first_idx = out[pcol].first_valid_index()
        if first_idx is None:
            raise ValueError(f"[{tag}] Série inteira sem valores válidos.")
        out.loc[0, pcol] = out.loc[first_idx, pcol]
        out.loc[0, qcol] = out.loc[first_idx, qcol]

    out[pcol] = out[pcol].ffill()
    out[qcol] = out[qcol].ffill()

    if len(out) != expected_n:
        raise ValueError(f"[{tag}] Tamanho inesperado: {len(out)} (esperado {expected_n}).")

    return out[["Hora_decimal", pcol, qcol]].rename(columns={pcol: "P", qcol: "Q"})

rge_raw = _read(RGE_FP)
sim_raw = _read(SIM_FP)

req_rge = ["Hora_decimal", "P_3f", "Q_3f"]
req_sim = ["Hora_decimal", "P_3f_S", "Q_3f_S"]

for name, df, req in [("RGE", rge_raw, req_rge), ("SIM", sim_raw, req_sim)]:
    miss = [c for c in req if c not in df.columns]
    if miss:
        raise ValueError(f"Colunas faltando em {name}: {miss}. Disponíveis: {list(df.columns)}")

rge = _to_grid(rge_raw, "Hora_decimal", "P_3f", "Q_3f", "RGE")
sim = _to_grid(sim_raw, "Hora_decimal", "P_3f_S", "Q_3f_S", "SIM")

res = pd.DataFrame({"Hora_decimal": grid})
res["P_residuo_BT_kW"]   = rge["P"] - sim["P"]
res["Q_residuo_BT_kVAr"] = rge["Q"] - sim["Q"]

# garante pasta
SIM_DIR.mkdir(parents=True, exist_ok=True)

res.to_csv(OUT_FP, index=False, encoding="utf-8-sig")
print("DONE. Saved:", OUT_FP)

print("P_residuo_BT_kW   min/mean/max =",
      float(res["P_residuo_BT_kW"].min()),
      float(res["P_residuo_BT_kW"].mean()),
      float(res["P_residuo_BT_kW"].max()))

print("Q_residuo_BT_kVAr min/mean/max =",
      float(res["Q_residuo_BT_kVAr"].min()),
      float(res["Q_residuo_BT_kVAr"].mean()),
      float(res["Q_residuo_BT_kVAr"].max()))

# %% Celula 044 - Criar Curva_residuo_BT_por_kVA_sim_3 (fatores por soma das demandas estimadas)

import os
from pathlib import Path
import numpy as np
import pandas as pd

WORK_DIR = Path(r"C:\GitHub\determinar_modelo")
SIM_DIR  = WORK_DIR / "Simulacao 003"
os.chdir(WORK_DIR)

RES_FP  = SIM_DIR  / "Curva_residuo_BT_sim_3.csv"                 
EST_DIR = WORK_DIR / "23 Memoria de massa estimada com residuo para simulacao III dos trafos nao medidos 2025"
OUT_FP  = SIM_DIR  / "Curva_residuo_BT_por_kVA_sim_3.csv"         

SIM_DIR.mkdir(parents=True, exist_ok=True)

if not RES_FP.exists():  raise FileNotFoundError(RES_FP)
if not EST_DIR.exists(): raise FileNotFoundError(EST_DIR)

expected_n = 35040
grid = np.round(np.arange(0.0, 8760.0, 0.25), 2)

res = pd.read_csv(RES_FP, encoding="utf-8-sig", sep=None, engine="python")
res.columns = res.columns.astype(str).str.replace("\ufeff","",regex=False).str.strip().str.replace(r"\s+"," ",regex=True)

need_res = ["Hora_decimal", "P_residuo_BT_kW", "Q_residuo_BT_kVAr"]
miss = [c for c in need_res if c not in res.columns]
if miss:
    raise ValueError(f"Colunas faltando em {RES_FP.name}: {miss}")

for c in need_res:
    res[c] = pd.to_numeric(res[c], errors="coerce")

res = res.dropna(subset=["Hora_decimal"]).drop_duplicates("Hora_decimal", keep="first").sort_values("Hora_decimal").reset_index(drop=True)
res = res[res["Hora_decimal"] < 8760.0].copy()

if len(res) != expected_n:
    raise ValueError(f"{RES_FP.name}: tamanho {len(res)} != {expected_n}")
if not np.allclose(res["Hora_decimal"].to_numpy(dtype=float), grid, atol=1e-9):
    raise ValueError(f"{RES_FP.name}: Hora_decimal desalinhado")

csvs = sorted(EST_DIR.glob("*.csv"))
if not csvs:
    raise FileNotFoundError(f"Nenhum CSV em {EST_DIR}")

sumP = np.zeros(expected_n, dtype=float)
sumAbsQ = np.zeros(expected_n, dtype=float)

def _read_curve(fp: Path) -> pd.DataFrame:
    df = pd.read_csv(fp, encoding="utf-8-sig", sep=None, engine="python")
    df.columns = df.columns.astype(str).str.replace("\ufeff","",regex=False).str.strip().str.replace(r"\s+"," ",regex=True)
    needed = ["Hora_decimal","P_3f","Q_3f"]
    miss = [c for c in needed if c not in df.columns]
    if miss:
        raise ValueError(f"{fp.name}: colunas faltando {miss}")

    for c in needed:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=["Hora_decimal"]).drop_duplicates("Hora_decimal", keep="first").sort_values("Hora_decimal").reset_index(drop=True)
    df = df[df["Hora_decimal"] < 8760.0].copy()

    # garante 0.0 (HOLD do primeiro)
    if not (df["Hora_decimal"] == 0.0).any():
        first = df.iloc[0]
        df = pd.concat([pd.DataFrame([{
            "Hora_decimal": 0.0,
            "P_3f": float(first["P_3f"]),
            "Q_3f": float(first["Q_3f"]),
        }]), df], ignore_index=True).sort_values("Hora_decimal").drop_duplicates("Hora_decimal", keep="first").reset_index(drop=True)

    if len(df) != expected_n:
        raise ValueError(f"{fp.name}: tamanho {len(df)} != {expected_n}")
    if not np.allclose(df["Hora_decimal"].to_numpy(dtype=float), grid, atol=1e-9):
        raise ValueError(f"{fp.name}: Hora_decimal desalinhado")

    return df[["Hora_decimal","P_3f","Q_3f"]]

for fp in csvs:
    dfc = _read_curve(fp)
    sumP += dfc["P_3f"].to_numpy(dtype=float)
    sumAbsQ += np.abs(dfc["Q_3f"].to_numpy(dtype=float))

EPS = 1e-9
resP = res["P_residuo_BT_kW"].to_numpy(dtype=float)
resQ = res["Q_residuo_BT_kVAr"].to_numpy(dtype=float)

fP = np.zeros_like(resP)
maskP = np.abs(sumP) > EPS
fP[maskP] = resP[maskP] / sumP[maskP]

fQ = np.zeros_like(resQ)
maskQ = sumAbsQ > EPS
fQ[maskQ] = resQ[maskQ] / sumAbsQ[maskQ]

out = pd.DataFrame({
    "Hora_decimal": grid,
    "P_residuo_BT_kW": resP,
    "Q_residuo_BT_kVAr": resQ,
    "sumP_est_kW": sumP,
    "sumAbsQ_est_kVAr": sumAbsQ,
    "fatorP_por_sumP": fP,
    "fatorQ_por_sumAbsQ": fQ,
})

out.to_csv(OUT_FP, index=False, encoding="utf-8-sig")
print("DONE. Saved:", OUT_FP)
print("Curvas estimadas lidas:", len(csvs))

# %% Celula 045 - Aplicar resíduo proporcional nas curvas estimadas e salvar em 24... (NA RAIZ)

import os
from pathlib import Path
import numpy as np
import pandas as pd

WORK_DIR = Path(r"C:\GitHub\determinar_modelo")
SIM_DIR  = WORK_DIR / "Simulacao 003"
os.chdir(WORK_DIR)

# FATOR vem da subpasta
FACT_FP = SIM_DIR / "Curva_residuo_BT_por_kVA_sim_3.csv"

# Curvas usadas na terceira simulacao
SRC_DIR = WORK_DIR / "23 Memoria de massa estimada com residuo para simulacao III dos trafos nao medidos 2025"

# Saida 24 na raiz
OUT_DIR = WORK_DIR / "24 Memoria de massa estimada com residuo para simulacao IV dos trafos nao medidos 2025"
OUT_DIR.mkdir(parents=True, exist_ok=True)

if not FACT_FP.exists(): raise FileNotFoundError(FACT_FP)
if not SRC_DIR.exists(): raise FileNotFoundError(SRC_DIR)

expected_n = 35040
grid = np.round(np.arange(0.0, 8760.0, 0.25), 2)

fact = pd.read_csv(FACT_FP, encoding="utf-8-sig", sep=None, engine="python")
fact.columns = fact.columns.astype(str).str.replace("\ufeff","",regex=False).str.strip().str.replace(r"\s+"," ",regex=True)

need = ["Hora_decimal","fatorP_por_sumP","fatorQ_por_sumAbsQ"]
miss = [c for c in need if c not in fact.columns]
if miss:
    raise ValueError(f"Colunas faltando em {FACT_FP.name}: {miss}")

for c in need:
    fact[c] = pd.to_numeric(fact[c], errors="coerce")

fact = fact.dropna(subset=["Hora_decimal"]).drop_duplicates("Hora_decimal").sort_values("Hora_decimal")
fact = fact[fact["Hora_decimal"] < 8760.0].reset_index(drop=True)

if len(fact) != expected_n:
    raise ValueError(f"{FACT_FP.name}: tamanho {len(fact)} != {expected_n}")
if not np.allclose(fact["Hora_decimal"].to_numpy(dtype=float), grid, atol=1e-9):
    raise ValueError(f"{FACT_FP.name}: Hora_decimal desalinhado")

fP = fact["fatorP_por_sumP"].to_numpy(dtype=float)
fQ = fact["fatorQ_por_sumAbsQ"].to_numpy(dtype=float)

def _read_curve(fp: Path) -> pd.DataFrame:
    df = pd.read_csv(fp, encoding="utf-8-sig", sep=None, engine="python")
    df.columns = df.columns.astype(str).str.replace("\ufeff","",regex=False).str.strip().str.replace(r"\s+"," ",regex=True)

    for c in ["Hora_decimal","P_3f","Q_3f"]:
        if c not in df.columns:
            raise ValueError(f"{fp.name}: coluna faltando {c}")
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=["Hora_decimal"]).drop_duplicates("Hora_decimal").sort_values("Hora_decimal")
    df = df[df["Hora_decimal"] < 8760.0].reset_index(drop=True)

    if not (df["Hora_decimal"] == 0.0).any():
        first = df.iloc[0]
        df = pd.concat([pd.DataFrame([{
            "Hora_decimal": 0.0,
            "P_3f": float(first["P_3f"]),
            "Q_3f": float(first["Q_3f"]),
        }]), df], ignore_index=True).sort_values("Hora_decimal").drop_duplicates("Hora_decimal").reset_index(drop=True)

    if len(df) != expected_n:
        raise ValueError(f"{fp.name}: tamanho {len(df)} != {expected_n}")
    if not np.allclose(df["Hora_decimal"].to_numpy(dtype=float), grid, atol=1e-9):
        raise ValueError(f"{fp.name}: Hora_decimal desalinhado")

    return df[["Hora_decimal","P_3f","Q_3f"]]

csvs = sorted(SRC_DIR.glob("*.csv"))
if not csvs:
    raise FileNotFoundError(f"Nenhum CSV em {SRC_DIR}")

p_alocado_total = np.zeros(expected_n)
q_alocado_total = np.zeros(expected_n)
ok, fail = 0, 0
for fp in csvs:
    try:
        base = _read_curve(fp)
        Pi = base["P_3f"].to_numpy(dtype=float)
        Qi = base["Q_3f"].to_numpy(dtype=float)

        dP = Pi * fP

        # fQ ja contem o sinal do residuo RGE - SIM.
        # Multiplicar por sign(Qi) invertia a correcao nas cargas capacitivas.
        dQ = np.abs(Qi) * fQ
        q_alvo = Qi + dQ
        # Preserva a natureza indutiva/capacitiva; saturacao em zero.
        # A parcela nao alocada fica registrada para posterior verificacao.
        q_corr = np.where(Qi > 0, np.maximum(q_alvo, 0.0),
                          np.where(Qi < 0, np.minimum(q_alvo, 0.0), 0.0))
        p_corr = np.maximum(Pi + dP, 0.0)
        p_alocado_total += p_corr - Pi
        q_alocado_total += q_corr - Qi
        base["P_3f"] = p_corr
        base["Q_3f"] = q_corr

        out_fp = OUT_DIR / fp.name
        base.to_csv(out_fp, index=False, encoding="utf-8-sig")
        ok += 1
    except Exception as e:
        print("[FAIL]", fp.name, "->", e)
        fail += 1

print("DONE. OK:", ok, "FAIL:", fail)
print("Saved in:", OUT_DIR)

# Diagnostico da terceira correcao: nao representa ainda o residuo no PAC.
if fail:
    raise RuntimeError("Falha na correcao de curvas. Nao prossiga para a simulacao IV.")
res_original = pd.read_csv(SIM_DIR / "Curva_residuo_BT_sim_3.csv", encoding="utf-8-sig")
diag1 = pd.DataFrame({"Hora_decimal": grid, "P_alocado_kW": p_alocado_total,
                      "Q_alocado_kVAr": q_alocado_total})
diag1["P_nao_alocado_kW"] = res_original["P_residuo_BT_kW"].to_numpy() - p_alocado_total
diag1["Q_nao_alocado_kVAr"] = res_original["Q_residuo_BT_kVAr"].to_numpy() - q_alocado_total
diag1.to_csv(SIM_DIR / "Correcao_residuo_sim_3_diagnostico.csv", index=False, encoding="utf-8-sig")

# %% Celula 046 - Converter curvas com resíduo para pu

import os, re
from pathlib import Path
import pandas as pd
import numpy as np

WORK_DIR = Path(r"C:\GitHub\determinar_modelo")
os.chdir(WORK_DIR)

IN_DIR  = WORK_DIR / "24 Memoria de massa estimada com residuo para simulacao IV dos trafos nao medidos 2025"
OUT_DIR = WORK_DIR / "Cargas_Estimadas_com_residuo_sim_4"
OUT_DIR.mkdir(parents=True, exist_ok=True)

csv_files = sorted(IN_DIR.glob("*.csv"))
if not csv_files:
    raise FileNotFoundError(f"Nenhum CSV em {IN_DIR}")

re_kva = re.compile(r"_(\d+(?:\.\d+)?)kVA", re.I)

def kva_do_nome(nome: str) -> float:
    m = re_kva.search(nome)
    if not m:
        raise ValueError(f"kVA não encontrado no nome: {nome}")
    kva = float(m.group(1))
    if kva <= 0:
        raise ValueError(f"kVA inválido no nome: {nome}")
    return kva

expected_n = 35040
grid = np.round(np.arange(0.0, 8760.0, 0.25), 2)

n_ok, n_fail = 0, 0

for fp in csv_files:
    try:
        kva = kva_do_nome(fp.name)

        df = pd.read_csv(fp, encoding="utf-8", sep=None, engine="python")
        df.columns = (
            df.columns.astype(str)
            .str.replace("\ufeff", "", regex=False)
            .str.strip()
            .str.replace(r"\s+", " ", regex=True)
        )

        for c in ["Hora_decimal", "P_3f", "Q_3f"]:
            if c not in df.columns:
                raise ValueError(f"{fp.name}: coluna faltando {c}")
            df[c] = pd.to_numeric(df[c], errors="coerce")

        df = (
            df.dropna(subset=["Hora_decimal", "P_3f", "Q_3f"])
              .query("Hora_decimal < 8760.0")
              .sort_values("Hora_decimal")
              .drop_duplicates("Hora_decimal")
              .reset_index(drop=True)
        )

        if len(df) != expected_n:
            raise ValueError(f"{fp.name}: tamanho {len(df)} != {expected_n}")

        if not np.allclose(df["Hora_decimal"].to_numpy(dtype=float), grid, atol=1e-9):
            raise ValueError(f"{fp.name}: Hora_decimal desalinhado")

        # ---- conversão para pu ----
        df["P_pu"] = df["P_3f"] / kva
        df["Q_pu"] = df["Q_3f"] / kva

        # ---- saída compatível OpenDSS ----
        out_fp = OUT_DIR / (fp.stem + "_pu.csv")

        df_out = df[["Hora_decimal", "P_pu", "Q_pu"]].copy()

        # força ponto decimal e precisão fixa
        for col in df_out.columns:
            df_out[col] = df_out[col].map(lambda x: f"{x:.6f}")
       
        df_out.to_csv(
            out_fp,
            index=False,
            header=False,
            encoding="utf-8",
            lineterminator="\n"
        )


        n_ok += 1

    except Exception as e:
        print("[FAIL]", fp.name, "->", e)
        n_fail += 1

print("DONE. Gerados:", n_ok, "Falhas:", n_fail)
print("Saída em:", OUT_DIR)

if n_fail:
    raise RuntimeError("Falha na conversao PU. Corrija antes da simulacao IV.")


# Gerar o DSS da quarta simulacao a partir das declaracoes da terceira.
# Mantem os nomes das curvas; troca somente a pasta dos CSVs PU.
DSS4_FP = WORK_DIR / "UFSM_cargas_estimadas_com_residuo_sim_4.dss"
pu_gerados = {(fp.stem + "_pu.csv").casefold(): OUT_DIR / (fp.stem + "_pu.csv") for fp in csv_files}
template_fp = WORK_DIR / "UFSM_cargas_estimadas_com_residuo_sim_3.dss"
try:
    texto_dss = template_fp.read_text(encoding="utf-8-sig")
except UnicodeDecodeError:
    texto_dss = template_fp.read_text(encoding="cp1252")
refs_usadas = set()


def trocar_csv4(m):
    caminho = m[2].strip('"\'').replace("\\", "/")
    if not caminho.lower().endswith(".csv"):
        return m[0]
    nome = caminho.rsplit("/", 1)[-1].casefold()
    if nome not in pu_gerados:
        raise FileNotFoundError(f"CSV do DSS sem correspondente na SIM4: {caminho}")
    refs_usadas.add(nome)
    return m[1] + '"' + pu_gerados[nome].resolve().as_posix() + '"'


padrao_csv4 = r'''(\b(?:csvfile|file|pqcsvfile)\s*=\s*)("[^"]*"|'[^']*'|[^,\s)]+)'''
texto_dss = re.sub(padrao_csv4, trocar_csv4, texto_dss, flags=re.I)
if refs_usadas != set(pu_gerados):
    raise ValueError("DSS nao referencia todas as curvas geradas: " + str(set(pu_gerados) - refs_usadas))
DSS4_FP.write_text(texto_dss, encoding="utf-8")
print("DSS da quarta simulacao:", DSS4_FP)


# %% Celula 047 – QUARTA E ULTIMA SIMULACAO OPEN-DSS (UFSM 2025)

import os
import shutil
from pathlib import Path
from py_dss_interface import DSS

WORK_DIR = Path(r"C:\GitHub\determinar_modelo")
SIM_DIR  = WORK_DIR / "Simulacao 004"
SIM_DIR.mkdir(parents=True, exist_ok=True)

os.chdir(WORK_DIR)

MON_NAMES = ["GERAL"]

def find_exported_monitor_file(export_dir: Path, mon_name: str) -> Path:
    # Comparacao exata sem diferenciar maiusculas/minusculas (Windows/Linux).
    wanted = f"ufsm_mon_{mon_name}_1.csv".casefold()
    encontrados = [p for p in export_dir.iterdir() if p.name.casefold() == wanted]
    if len(encontrados) != 1:
        raise FileNotFoundError(f"Exportacao ausente/ambigua: {wanted}: {encontrados}")
    return encontrados[0]

if not (WORK_DIR / "UFSM_cargas_estimadas_com_residuo_sim_4.dss").exists():
    raise FileNotFoundError("Execute a celula 045 antes da quarta simulacao.")

for raw in SIM_DIR.glob("*.csv"):
    if raw.name.casefold() in {f"ufsm_mon_{m}_1.csv".casefold() for m in MON_NAMES}:
        raw.unlink()

dss = DSS()
dss.text("Clear")
dss.text(f'cd "{WORK_DIR}"')

# arquivos de entrada com caminho absoluto
dss.text(
    "New Circuit.UFSM bus1=0010 basekv=13.8 phases=3 "
    "puZ0=[1.24 2.50] puZ1=[0.43 0.98] puZ2=[0.43 0.98]"
)
dss.text(f'Redirect "{WORK_DIR / "UFSM_wiredata.dss"}"')
dss.text(f'Redirect "{WORK_DIR / "UFSM_linhas.dss"}"')
dss.text(f'Redirect "{WORK_DIR / "UFSM_chaves.dss"}"')
dss.text(f'Redirect "{WORK_DIR / "UFSM_caps.dss"}"')
dss.text(f'Redirect "{WORK_DIR / "UFSM_trafos_medidos.dss"}"')
dss.text(f'Redirect "{WORK_DIR / "UFSM_trafos_cargas_especiais.dss"}"')
dss.text(f'Redirect "{WORK_DIR / "UFSM_trafos_estimados.dss"}"')
dss.text(f'Redirect "{WORK_DIR / "UFSM_cargas_medidas.dss"}"')
dss.text(f'Redirect "{WORK_DIR / "UFSM_cargas_especiais.dss"}"')
dss.text(f'Redirect "{WORK_DIR / "UFSM_cargas_estimadas_com_residuo_sim_4.dss"}"')

# pasta de exportacao dos monitores e meter
dss.text(f'Set DataPath="{SIM_DIR}"')

dss.text("New Monitor.GERAL element=line.0015_0016 terminal=1 mode=1 ppolar=no")
dss.text("New Energymeter.GERAL element=line.0015_0016 terminal=1")

dss.text("Set VoltageBases=[13.8,0.38,0.22]")
dss.text("CalcVoltageBases")
dss.text("Set Mode=Yearly Hour=0 Sec=0 StepSize=0.25h Number=35040")
dss.text("Solve")

for mon_name in MON_NAMES:
    dss.text(f"Export Monitors {mon_name}")

    fp = find_exported_monitor_file(SIM_DIR, mon_name)
    dst = SIM_DIR / f"UFSM_Mon_{mon_name}_1.csv"

    if fp.resolve() != dst.resolve():
        if dst.exists():
            dst.unlink()
        shutil.move(str(fp), str(dst))

dss.text("Export Meter /m")
print("Concluido. Monitores exportados em:", SIM_DIR)


# %% Celula 048 – Unificar fases (P/Q 3f) de TODOS os Monitores e salvar em "Simulacao 004"
# =============================================================================
# Lê em:  Simulacao 004/UFSM_Mon_<MON_NAME>_1.csv
# Gera em: Simulacao 004/Curva_de_Carga_<MON_NAME>_sim_4.csv
# Aplica shift anual unico para a DIREITA
# =============================================================================

import os
from pathlib import Path
import numpy as np
import pandas as pd

WORK_DIR = Path(r"C:\GitHub\determinar_modelo")
SIM_DIR  = WORK_DIR / "Simulacao 004"
SIM_DIR.mkdir(parents=True, exist_ok=True)
os.chdir(WORK_DIR)

MON_NAMES = ["GERAL"]

EXPECTED_N = 35040
DT_H = 0.25
hora = np.round(np.arange(0.0, 8760.0, DT_H), 10)

def _clean_columns(cols):
    s = pd.Index(cols).astype(str)
    return (
        s.str.replace("\ufeff", "", regex=False)
         .str.replace("\t", " ", regex=False)
         .str.strip()
         .str.replace(r"\s+", " ", regex=True)
    )

def process_monitor(mon_name: str) -> Path:
    mon_fp = SIM_DIR / f"UFSM_Mon_{mon_name}_1.csv"
    out_fp = SIM_DIR / f"Curva_de_Carga_{mon_name}_sim_4.csv"

    if not mon_fp.exists():
        raise FileNotFoundError(f"Monitor CSV not found: {mon_fp}")

    mon = pd.read_csv(mon_fp, encoding="utf-8-sig", sep=None, engine="python")
    mon.columns = _clean_columns(mon.columns)

    needed = [
        "P1 (kW)", "Q1 (kvar)",
        "P2 (kW)", "Q2 (kvar)",
        "P3 (kW)", "Q3 (kvar)",
    ]
    missing = [c for c in needed if c not in mon.columns]
    if missing:
        raise ValueError(f"[{mon_name}] Missing monitor columns: {missing}\nDetected: {list(mon.columns)}")

    for c in needed:
        mon[c] = pd.to_numeric(mon[c], errors="coerce")

    if mon[needed].isna().any().any():
        bad = mon[needed].isna().sum()
        raise ValueError(f"[{mon_name}] NaN found after numeric conversion:\n{bad}")

    vals = pd.DataFrame({
        "P_3f_S": mon["P1 (kW)"] + mon["P2 (kW)"] + mon["P3 (kW)"],
        "Q_3f_S": mon["Q1 (kvar)"] + mon["Q2 (kvar)"] + mon["Q3 (kvar)"],
    }).to_numpy(copy=True)

    if len(vals) != EXPECTED_N:
        raise ValueError(f"[{mon_name}] Unexpected length: {len(vals)} rows (expected {EXPECTED_N}).")

    # Shift anual unico para a DIREITA:
    # duplica a 1a linha e remove a ultima
    vals = np.vstack([vals[0:1, :], vals[0:-1, :]])

    df_out = pd.DataFrame({
        "Hora_decimal": hora,
        "P_3f_S": vals[:, 0],
        "Q_3f_S": vals[:, 1],
    })

    if len(df_out) != EXPECTED_N:
        raise ValueError(f"[{mon_name}] Tamanho inesperado da curva final: {len(df_out)}")

    if abs(df_out["Hora_decimal"].iloc[0] - 0.0) > 1e-9:
        raise ValueError(f"[{mon_name}] Hora_decimal does not start at 0.0")
    if abs(df_out["Hora_decimal"].iloc[-1] - 8759.75) > 1e-9:
        raise ValueError(f"[{mon_name}] Hora_decimal last time is not 8759.75")
    if not np.allclose(np.diff(df_out["Hora_decimal"].values), DT_H, atol=1e-9):
        raise ValueError(f"[{mon_name}] Hora_decimal is not a uniform 0.25h grid after cleaning.")

    df_out.to_csv(out_fp, index=False, encoding="utf-8-sig")

    # Preserva o monitor bruto para auditoria e reexecucao da celula.

    return out_fp

outs = []
for name in MON_NAMES:
    out_fp = process_monitor(name)
    outs.append(out_fp)
    print(f"[OK] {name} -> {out_fp.name}")

print("\nCONCLUIDO. Arquivos gerados em:", SIM_DIR)
print("Total:", len(outs))
print("[INFO] Shift anual unico aplicado para a DIREITA em todos os monitores.")


# %% Celula 049 - Estatísticas comparativas RGE vs SIM4 (2025)  [SAÍDA EM: Simulacao 004]

from pathlib import Path
import numpy as np
import pandas as pd

WORK_DIR = Path(r"C:\GitHub\determinar_modelo")

# --- pasta da Simulação IV ---
SIM4_DIR = WORK_DIR / "Simulacao 004"
SIM4_DIR.mkdir(parents=True, exist_ok=True)

RGE_FP = WORK_DIR / "00_memoria_de_massa_RGE_15min_2025.csv"
SIM_FP = SIM4_DIR / "Curva_de_Carga_GERAL_sim_4.csv"

OUT_RESUMO = SIM4_DIR / "validacao_SIM4_resumo.csv"
OUT_PICOS  = SIM4_DIR / "validacao_SIM4_picos_mensais.csv"

DT_H = 0.25
N = 35040
grid = np.round(np.arange(0.0, 8760.0, 0.25), 2)

# ---------- leitura ----------
rge = pd.read_csv(RGE_FP, encoding="utf-8-sig", sep=None, engine="python")
sim = pd.read_csv(SIM_FP, encoding="utf-8-sig", sep=None, engine="python")

# ---------- normalização de colunas ----------
def _norm_cols(df):
    df.columns = (
        df.columns.astype(str)
        .str.replace("\ufeff", "", regex=False)
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
    )
    return df

rge = _norm_cols(rge)
sim = _norm_cols(sim)

# ---------- seleção ----------
rge = rge[["Hora_decimal", "P_3f", "Q_3f"]].rename(columns={"P_3f": "P_RGE", "Q_3f": "Q_RGE"})
sim = sim[["Hora_decimal", "P_3f_S", "Q_3f_S"]].rename(columns={"P_3f_S": "P_SIM", "Q_3f_S": "Q_SIM"})

# ---------- numéricos ----------
for c in ["Hora_decimal", "P_RGE", "Q_RGE"]:
    rge[c] = pd.to_numeric(rge[c], errors="coerce")

for c in ["Hora_decimal", "P_SIM", "Q_SIM"]:
    sim[c] = pd.to_numeric(sim[c], errors="coerce")

rge = rge.dropna(subset=["Hora_decimal"]).drop_duplicates("Hora_decimal").sort_values("Hora_decimal")
sim = sim.dropna(subset=["Hora_decimal"]).drop_duplicates("Hora_decimal").sort_values("Hora_decimal")

# ---------- alinhamento ----------
base = pd.DataFrame({"Hora_decimal": grid})
df = base.merge(rge, on="Hora_decimal", how="left").merge(sim, on="Hora_decimal", how="left")

# HOLD forward
for c in ["P_RGE", "Q_RGE", "P_SIM", "Q_SIM"]:
    if pd.isna(df[c].iloc[0]):
        first = df[c].first_valid_index()
        if first is None:
            raise ValueError(f"Série inteira vazia para {c}")
        df.loc[0, c] = df.loc[first, c]
    df[c] = df[c].ffill()

if len(df) != N:
    raise ValueError(f"Tamanho inesperado após alinhamento: {len(df)} (esperado {N})")

# ---------- métricas ----------
def calc_stats(sim_s, ref_s):
    e = sim_s - ref_s

    NMAE = np.nan if ref_s.abs().sum() == 0 else float(e.abs().sum() / ref_s.abs().sum())

    RMSE = float(np.sqrt(np.mean(e.values ** 2)))
    rng = float(ref_s.max() - ref_s.min())
    NRMSE = np.nan if rng == 0 else float(RMSE / rng)

    E_sim = float(sim_s.sum() * DT_H)
    E_ref = float(ref_s.sum() * DT_H)
    eps_E = np.nan if E_ref == 0 else float(abs(E_sim - E_ref) / abs(E_ref))

    return NMAE, NRMSE, E_sim, E_ref, eps_E

NMAE_P, NRMSE_P, E_P_sim, E_P_rge, eps_E_P = calc_stats(df["P_SIM"], df["P_RGE"])
NMAE_Q, NRMSE_Q, E_Q_sim, E_Q_rge, eps_E_Q = calc_stats(df["Q_SIM"], df["Q_RGE"])

# ---------- picos mensais ----------
ts = pd.date_range("2025-01-01", periods=N, freq="15min")
dft = df.copy()
dft["timestamp"] = ts
dft = dft.set_index("timestamp")

mensal = pd.DataFrame({
    "P_SIM_max": dft["P_SIM"].resample("ME").max(),
    "P_RGE_max": dft["P_RGE"].resample("ME").max(),
    "Q_SIM_max": dft["Q_SIM"].resample("ME").max(),
    "Q_RGE_max": dft["Q_RGE"].resample("ME").max(),
})

mensal["Delta_Pmax"] = mensal["P_SIM_max"] - mensal["P_RGE_max"]
mensal["Delta_Qmax"] = mensal["Q_SIM_max"] - mensal["Q_RGE_max"]

mensal = mensal.reset_index()
mensal["Mes"] = mensal["timestamp"].dt.to_period("M").astype(str)

mensal = mensal[[
    "Mes",
    "P_SIM_max", "P_RGE_max", "Delta_Pmax",
    "Q_SIM_max", "Q_RGE_max", "Delta_Qmax"
]]

# ---------- resumo ----------
resumo = pd.DataFrame([
    ["P", "NMAE",              NMAE_P],
    ["P", "NRMSE",             NRMSE_P],
    ["P", "Energia_SIM_kWh",   E_P_sim],
    ["P", "Energia_RGE_kWh",   E_P_rge],
    ["P", "Erro_rel_energia",  eps_E_P],

    ["Q", "NMAE",              NMAE_Q],
    ["Q", "NRMSE",             NRMSE_Q],
    ["Q", "Energia_SIM_kVArh", E_Q_sim],
    ["Q", "Energia_RGE_kVArh", E_Q_rge],
    ["Q", "Erro_rel_energia",  eps_E_Q],
], columns=["Grandeza", "Metrica", "Valor"])

# ---------- salvar ----------
resumo.to_csv(OUT_RESUMO, index=False, float_format="%.6g", encoding="utf-8")
mensal.to_csv(OUT_PICOS, index=False, float_format="%.6g", encoding="utf-8")

print("✔ Resumo salvo em:", OUT_RESUMO)
print("✔ Picos mensais salvos em:", OUT_PICOS)



TOLERANCIA = 0.05  # 5% em forma decimal.
# Complementos da celula 048: meta conjunta, comparacao e graficos.
criterios = resumo[resumo.Metrica.isin(["NMAE", "NRMSE", "Erro_rel_energia"])].copy()
criterios["Valor_percentual"] = criterios.Valor * 100
criterios["Limite_percentual"] = TOLERANCIA * 100
criterios["Atende"] = np.isfinite(criterios.Valor) & (criterios.Valor <= TOLERANCIA)
criterios.to_csv(SIM4_DIR / "validacao_SIM4_criterios_5pct.csv", index=False, encoding="utf-8-sig")
print(criterios.to_string(index=False))
print("Meta conjunta no PAC:", "ATENDIDA" if criterios.Atende.all() else "NAO ATENDIDA")
print("Aderencia agregada nao valida as curvas locais nem as tensoes internas.")
for grandeza in ["P", "Q"]:
    ref = mensal[f"{grandeza}_RGE_max"].abs()
    mensal[f"Erro_{grandeza}max_percentual"] = mensal[f"Delta_{grandeza}max"].abs().div(ref.where(ref > 0)) * 100
mensal.to_csv(OUT_PICOS, index=False, encoding="utf-8-sig")
comparacoes = []
for numero in (1, 2, 3, 4):
    fp = WORK_DIR / f"Simulacao {numero:03d}" / f"validacao_SIM{numero}_resumo.csv"
    if fp.exists():
        tabela = pd.read_csv(fp)
        tabela = tabela[tabela.Metrica.isin(["NMAE", "NRMSE", "Erro_rel_energia"])].copy()
        tabela["Simulacao"] = numero
        tabela["Valor_percentual"] = tabela.Valor * 100
        comparacoes.append(tabela)
    else:
        print(f"[AVISO] Execute a analise estatistica da SIM{numero}: {fp}")
pd.concat(comparacoes, ignore_index=True).to_csv(
    SIM4_DIR / "Comparacao_SIM1_SIM2_SIM3_SIM4.csv", index=False, encoding="utf-8-sig")

import matplotlib.pyplot as plt
fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
for ax, g, unidade in zip(axes, ["P", "Q"], ["kW", "kVAr"]):
    ax.plot(ts, df[f"{g}_RGE"], label="RGE", linewidth=0.6)
    ax.plot(ts, df[f"{g}_SIM"], label="Simulacao 4", linewidth=0.6, alpha=0.75)
    ax.set_ylabel(f"{g} ({unidade})")
    ax.grid(alpha=0.3)
    ax.legend()
axes[0].set_title("Comparacao no PAC - quarta simulacao")
fig.tight_layout()
fig.savefig(SIM4_DIR / "Comparacao_RGE_SIM4.png", dpi=180)
plt.close(fig)

# Encerramento apos a quarta simulacao, conforme escopo deste estudo.
# Limite de rodadas e atendimento da tolerancia sao informacoes distintas.
print("Quarta e ultima simulacao: etapa de calibracao encerrada apos esta rodada.")
if not criterios.Atende.all():
    print("Indicadores que permanecem fora da meta de 5%:")
    print(criterios.loc[~criterios.Atende].to_string(index=False))
    print("Encerramento pelo limite de quatro simulacoes; meta conjunta nao atingida.")
else:
    print("Os seis indicadores atingiram a meta conjunta de 5% no PAC.")

# %% Celula 050 - Calcular Curva_residuo_BT_sim_4 = RGE (raiz) - SIM (Simulacao 004)

import os
from pathlib import Path
import numpy as np
import pandas as pd

WORK_DIR = Path(r"C:\GitHub\determinar_modelo")
SIM_DIR  = WORK_DIR / "Simulacao 004"
os.chdir(WORK_DIR)

# RGE fica na raiz
RGE_FP = WORK_DIR / "00_memoria_de_massa_RGE_15min_2025.csv"

# SIM e saídas ficam na subpasta
SIM_FP = SIM_DIR / "Curva_de_Carga_GERAL_sim_4.csv"
OUT_FP = SIM_DIR / "Curva_residuo_BT_sim_4.csv"

for fp in [RGE_FP, SIM_FP]:
    if not fp.exists():
        raise FileNotFoundError(f"File not found: {fp}")

expected_n = 35040
grid = np.round(np.arange(0.0, 8760.0, 0.25), 2)

def _read(fp: Path) -> pd.DataFrame:
    df = pd.read_csv(fp, encoding="utf-8-sig", sep=None, engine="python")
    df.columns = (
        df.columns.astype(str)
        .str.replace("\ufeff", "", regex=False)
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
    )
    return df

def _to_grid(df: pd.DataFrame, hcol: str, pcol: str, qcol: str, tag: str) -> pd.DataFrame:
    out = df[[hcol, pcol, qcol]].copy()
    out[hcol] = pd.to_numeric(out[hcol], errors="coerce")
    out[pcol] = pd.to_numeric(out[pcol], errors="coerce")
    out[qcol] = pd.to_numeric(out[qcol], errors="coerce")

    out = out.dropna(subset=[hcol]).drop_duplicates(subset=[hcol]).sort_values(hcol).reset_index(drop=True)
    out = out[out[hcol] < 8760.0].copy()

    base = pd.DataFrame({"Hora_decimal": grid})
    out = base.merge(out, left_on="Hora_decimal", right_on=hcol, how="left")

    # HOLD inicial
    if pd.isna(out[pcol].iloc[0]) or pd.isna(out[qcol].iloc[0]):
        first_idx = out[pcol].first_valid_index()
        if first_idx is None:
            raise ValueError(f"[{tag}] Série inteira sem valores válidos.")
        out.loc[0, pcol] = out.loc[first_idx, pcol]
        out.loc[0, qcol] = out.loc[first_idx, qcol]

    out[pcol] = out[pcol].ffill()
    out[qcol] = out[qcol].ffill()

    if len(out) != expected_n:
        raise ValueError(f"[{tag}] Tamanho inesperado: {len(out)} (esperado {expected_n}).")

    return out[["Hora_decimal", pcol, qcol]].rename(columns={pcol: "P", qcol: "Q"})

rge_raw = _read(RGE_FP)
sim_raw = _read(SIM_FP)

req_rge = ["Hora_decimal", "P_3f", "Q_3f"]
req_sim = ["Hora_decimal", "P_3f_S", "Q_3f_S"]

for name, df, req in [("RGE", rge_raw, req_rge), ("SIM", sim_raw, req_sim)]:
    miss = [c for c in req if c not in df.columns]
    if miss:
        raise ValueError(f"Colunas faltando em {name}: {miss}. Disponíveis: {list(df.columns)}")

rge = _to_grid(rge_raw, "Hora_decimal", "P_3f", "Q_3f", "RGE")
sim = _to_grid(sim_raw, "Hora_decimal", "P_3f_S", "Q_3f_S", "SIM")

res = pd.DataFrame({"Hora_decimal": grid})
res["P_residuo_BT_kW"]   = rge["P"] - sim["P"]
res["Q_residuo_BT_kVAr"] = rge["Q"] - sim["Q"]

# garante pasta
SIM_DIR.mkdir(parents=True, exist_ok=True)

res.to_csv(OUT_FP, index=False, encoding="utf-8-sig")
print("DONE. Saved:", OUT_FP)

print("P_residuo_BT_kW   min/mean/max =",
      float(res["P_residuo_BT_kW"].min()),
      float(res["P_residuo_BT_kW"].mean()),
      float(res["P_residuo_BT_kW"].max()))

print("Q_residuo_BT_kVAr min/mean/max =",
      float(res["Q_residuo_BT_kVAr"].min()),
      float(res["Q_residuo_BT_kVAr"].mean()),
      float(res["Q_residuo_BT_kVAr"].max()))
