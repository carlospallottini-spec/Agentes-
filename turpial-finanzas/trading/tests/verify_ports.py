"""Verifica que los ports de MQL5 y C# calculen lo MISMO que el motor de Python.

Los EAs no se pueden compilar en este entorno (no hay MetaEditor ni NinjaTrader),
pero su matemática sí es ejecutable. Este script:

  1. Extrae la matemática real de `trading/mt5/Include/OUMath.mqh` y la transpila a
     C++ con shims mínimos (MQL5 es casi C++: la diferencia relevante es la sintaxis
     de arrays y las funciones Math*/String*). Compila con g++ y la corre.
  2. Extrae la región PORTABLE MATH de `trading/ninjatrader/OUMeanReversion.cs`,
     la envuelve en una clase sin dependencias de NinjaTrader, compila con mcs y la corre.
  3. Corre el motor de Python (`quant/`) sobre las MISMAS series.
  4. Exige que los tres coincidan dentro de 1e-9.

Lo que esto verifica: la calibración del OU, el half-life, el z-score, el estadístico
de Dickey-Fuller, la cadena de Markov con su test chi-cuadrado y las reglas de posición.
Lo que NO verifica: la capa de ejecución de cada plataforma (órdenes, lotes, sesiones),
que sólo se puede probar en el tester de MT5 y en NinjaTrader.

Uso:  python trading/tests/verify_ports.py
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, RAIZ)

from quant import markov, ou  # noqa: E402
from quant.strategies import ou_position  # noqa: E402

MQH = os.path.join(RAIZ, "trading", "mt5", "Include", "OUMath.mqh")
CS = os.path.join(RAIZ, "trading", "ninjatrader", "OUMeanReversion.cs")

TOL = 1e-9
ROLL_VENTANA = 100   # ventana del test de bucle rodante

# --------------------------------------------------------------------- casos
def casos() -> dict[str, list[float]]:
    """Series de prueba: un OU verdadero, un random walk y una serie corta."""
    rw = [0.0]
    import random
    rng = random.Random(1234)
    for _ in range(399):
        rw.append(rw[-1] + rng.gauss(0, 0.01))
    return {
        "ou_fuerte": ou.simulate(0.08, 4.0, 0.15, 4.35, 400, seed=42),
        "ou_lento": ou.simulate(0.004, 3.0, 0.05, 3.20, 400, seed=7),
        "random_walk": [4.0 + v for v in rw],
        # Serie corta: los tres motores tienen que NEGARSE a calibrar, igual.
        "muy_corta": ou.simulate(0.08, 4.0, 0.15, 4.35, 25, seed=3),
    }


CASOS_POS = [
    # (z, prev, bars_held, half_life)
    (-2.0, 0, 0, 10.0),
    (2.0, 0, 0, 10.0),
    (-1.0, 0, 0, 10.0),
    (-0.2, 1, 5, 10.0),
    (-3.5, 1, 5, 10.0),
    (-2.0, 1, 5, 10.0),
    (-2.0, 1, 31, 10.0),
    (0.2, -1, 5, 10.0),
    (3.5, -1, 5, 10.0),
    (2.0, -1, 40, 10.0),
]


# ----------------------------------------------------------------- referencia
def referencia() -> list[str]:
    """Salida canónica del motor de Python, en el formato común."""
    out = []
    for nombre, serie in casos().items():
        out.append(f"CASE {nombre}")
        p = ou.calibrate(serie)
        if p.get("ok"):
            out.append(_fmt_ou(1, p["theta"], p["mu"], p["sigma"], p["sigma_eq"],
                               p["half_life"], p["z"], p["df_stat"],
                               1 if p["estacionaria_5pct"] else 0))
        else:
            df = p.get("df_stat")
            out.append(_fmt_ou(0, 0, 0, 0, 0, 0, 0,
                               df if df is not None else 0,
                               1 if (df is not None and df < ou.DF_CRITICAL["5%"]) else 0))
        rets = [serie[i] - serie[i - 1] for i in range(1, len(serie))]
        # Se usan las primitivas crudas: markov.analyze() redondea para la UI y ese
        # redondeo no es parte del modelo, así que compararlo sería comparar el formato.
        lab = markov.label_states(rets)
        if lab.get("ok"):
            tm = markov.transition_matrix(lab["states"])
            t = markov.independence_test(tm["counts"])
            estado = lab["states"][-1]
            out.append(_fmt_reg(1, estado, tm["P"][estado][estado], t["chi2"], t["df"],
                                1 if t["hay_memoria_5pct"] else 0))
        else:
            out.append(_fmt_reg(0, 0, 0, 0, 0, 0))
    for z, prev, held, hl in CASOS_POS:
        target, _ = ou_position(z, prev, held, hl, 1.5, 0.5, 3.0, 3.0)
        out.append(f"POS {z:.4f} {prev} {held} {hl:.4f} -> {target}")

    # Ventana móvil: en la barra t se calibra con serie[t-V+1 .. t] y nada más.
    # Es la convención que el EA implementa con CopyClose(..., 1, V, ...) y donde
    # se escondería un off-by-one que en el tester se vería como alfa del futuro.
    serie = casos()["ou_fuerte"]
    for t in range(ROLL_VENTANA - 1, len(serie)):
        w = serie[t - ROLL_VENTANA + 1: t + 1]
        p = ou.calibrate(w)
        if p.get("ok"):
            out.append("ROLL {} 1 {:.10f} {:.10f} {:.10f} {:.10f} {:.10f}".format(
                t, p["theta"], p["mu"], p["sigma_eq"], p["half_life"], p["z"]))
        else:
            out.append("ROLL {} 0 0.0000000000 0.0000000000 0.0000000000 "
                       "0.0000000000 0.0000000000".format(t))
    return out


def _fmt_ou(ok, theta, mu, sigma, sigma_eq, hl, z, df, est) -> str:
    return ("OU {} {:.10f} {:.10f} {:.10f} {:.10f} {:.10f} {:.10f} {:.10f} {}"
            .format(ok, theta, mu, sigma, sigma_eq, hl, z, df, est))


def _fmt_reg(ok, estado, persist, chi2, df, mem) -> str:
    return "REG {} {} {:.10f} {:.10f} {} {}".format(ok, estado, persist, chi2, df, mem)


# ------------------------------------------------------------------- MQL5 → C++
SHIM_CPP = r'''
// Shims mínimos para ejecutar la matemática de MQL5 como C++.
#include <cstdio>
#include <cstdarg>
#include <cfloat>
#include <cmath>
#include <string>
#include <vector>

typedef std::string string;
struct MArr : std::vector<double> {};
struct IArr : std::vector<int> {};

template<class T> T MathMax(T a, T b) { return a > b ? a : b; }
template<class T> T MathMin(T a, T b) { return a < b ? a : b; }
static inline double MathLog(double v)   { return std::log(v); }
static inline double MathLog10(double v) { return std::log10(v); }
static inline double MathSqrt(double v)  { return std::sqrt(v); }
static inline double MathExp(double v)   { return std::exp(v); }
static inline double MathAbs(double v)   { return std::fabs(v); }
static inline double MathFloor(double v) { return std::floor(v); }
static inline double MathCeil(double v)  { return std::ceil(v); }
static inline double MathRound(double v) { return std::floor(v + 0.5); }

static string StringFormat(const char *fmt, ...) {
   char buf[1024];
   va_list ap; va_start(ap, fmt);
   vsnprintf(buf, sizeof(buf), fmt, ap);
   va_end(ap);
   return string(buf);
}
'''

MAIN_CPP = r'''
static void emitirOU(const OUParams &p) {
   if(p.ok)
      printf("OU 1 %.10f %.10f %.10f %.10f %.10f %.10f %.10f %d\n",
             p.theta, p.mu, p.sigma, p.sigma_eq, p.half_life, p.z, p.df_stat,
             p.estacionaria ? 1 : 0);
   else
      printf("OU 0 0.0000000000 0.0000000000 0.0000000000 0.0000000000 "
             "0.0000000000 0.0000000000 %.10f %d\n",
             p.df_stat == -DBL_MAX ? 0.0 : p.df_stat, p.estacionaria ? 1 : 0);
}

static void emitirREG(const RegimeInfo &r) {
   if(r.ok)
      printf("REG 1 %d %.10f %.10f %d %d\n", r.estado, r.persistencia, r.chi2, r.df,
             r.hay_memoria ? 1 : 0);
   else
      printf("REG 0 0 0.0000000000 0.0000000000 0 0\n");
}

int main(int argc, char **argv) {
   FILE *f = fopen(argv[1], "r");
   char nombre[128];
   int n;
   MArr primera;   // la primera serie del fixture alimenta el bucle rodante
   while(fscanf(f, "%127s %d", nombre, &n) == 2) {
      MArr serie; serie.resize(n);
      for(int i = 0; i < n; i++) fscanf(f, "%lf", &serie[i]);
      if(primera.empty()) primera = serie;
      printf("CASE %s\n", nombre);
      OUParams p = OUCalibrate(serie, n, 30);
      emitirOU(p);
      MArr rets; rets.resize(n - 1);
      for(int i = 1; i < n; i++) rets[i-1] = serie[i] - serie[i-1];
      RegimeInfo r = MarkovRegime(rets, n - 1, 0.5, 1.0);
      emitirREG(r);
   }
   fclose(f);
   double zs[]   = {-2.0, 2.0, -1.0, -0.2, -3.5, -2.0, -2.0, 0.2, 3.5, 2.0};
   int prevs[]   = {0, 0, 0, 1, 1, 1, 1, -1, -1, -1};
   int helds[]   = {0, 0, 0, 5, 5, 5, 31, 5, 5, 40};
   for(int i = 0; i < 10; i++) {
      string motivo;
      int t = OUTargetPosition(zs[i], prevs[i], helds[i], 10.0, 1.5, 0.5, 3.0, 3.0, motivo);
      printf("POS %.4f %d %d %.4f -> %d\n", zs[i], prevs[i], helds[i], 10.0, t);
   }

   // Bucle rodante con la MISMA convención de ventana que usa el EA.
   const int V = ROLL_V;
   for(int t = V - 1; t < (int)primera.size(); t++) {
      MArr w; w.resize(V);
      for(int i = 0; i < V; i++) w[i] = primera[t - V + 1 + i];
      OUParams p = OUCalibrate(w, V, 30);
      if(p.ok)
         printf("ROLL %d 1 %.10f %.10f %.10f %.10f %.10f\n",
                t, p.theta, p.mu, p.sigma_eq, p.half_life, p.z);
      else
         printf("ROLL %d 0 0.0000000000 0.0000000000 0.0000000000 "
                "0.0000000000 0.0000000000\n", t);
   }
   return 0;
}
'''


def transpilar_mql5(fuente: str) -> str:
    """MQL5 -> C++ con cambios acotados y explícitos (sin tocar la lógica).

    La única diferencia estructural es cómo se declaran los arrays dinámicos.
    Si alguna de estas sustituciones dejara de aplicar, el compilador falla y el
    test lo reporta: nunca 'arregla' silenciosamente el código del EA.
    """
    s = fuente
    s = re.sub(r"#ifndef\s+__OU_MATH_MQH__|#define\s+__OU_MATH_MQH__|#endif.*", "", s)
    # parámetros de array: const double &x[] -> const MArr& x
    s = re.sub(r"const\s+double\s*&\s*(\w+)\s*\[\]", r"const MArr& \1", s)
    s = re.sub(r"const\s+int\s*&\s*(\w+)\s*\[\]", r"const IArr& \1", s)
    s = re.sub(r"(?<!const )\bdouble\s*&\s*(\w+)\s*\[\]", r"MArr& \1", s)
    # declaraciones locales de arrays dinámicos
    s = re.sub(r"^\s*double\s+(\w+)\[\]\s*,\s*(\w+)\[\]\s*;", r"   MArr \1, \2;", s, flags=re.M)
    s = re.sub(r"^\s*double\s+(\w+)\[\]\s*;", r"   MArr \1;", s, flags=re.M)
    s = re.sub(r"^\s*int\s+(\w+)\[\]\s*;", r"   IArr \1;", s, flags=re.M)
    # ArrayResize -> resize
    s = re.sub(r"ArrayResize\(\s*(\w+)\s*,\s*([^)]+)\)", r"\1.resize(\2)", s)
    # los structs de MQL5 se devuelven por valor igual que en C++: nada que hacer
    return SHIM_CPP + s + MAIN_CPP.replace("ROLL_V", str(ROLL_VENTANA))


def correr_mql5(fixture: str, work: str) -> list[str]:
    fuente = open(MQH, encoding="utf-8-sig").read()
    cpp = os.path.join(work, "ou_math.cpp")
    with open(cpp, "w", encoding="utf-8") as fh:
        fh.write(transpilar_mql5(fuente))
    binario = os.path.join(work, "ou_math")
    r = subprocess.run(["g++", "-std=c++17", "-O1", "-o", binario, cpp],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("g++ falló sobre la matemática de MQL5:\n" + r.stderr[:4000])
    out = subprocess.run([binario, fixture], capture_output=True, text=True, check=True)
    return out.stdout.strip().splitlines()


# --------------------------------------------------------------------- C# (NT8)
CS_SHELL = r'''
using System;

public class Harness
{
    private const double DfCrit5 = -2.86;
    private static readonly double[] Chi2Crit5 = { 0.0, 3.841, 5.991, 7.815, 9.488 };

    public double EntradaZ = 1.5, SalidaZ = 0.5, StopZ = 3.0, MaxHoldHL = 3.0, PersistMin = 0.6;
    public double RegimenK = 0.5;

__MATH__

    public static void Main(string[] args)
    {
        Harness h = new Harness();
        string[] tokens = System.IO.File.ReadAllText(args[0])
            .Split(new char[] { ' ', '\n', '\r', '\t' }, StringSplitOptions.RemoveEmptyEntries);
        int k = 0;
        double[] primera = null;
        while (k < tokens.Length)
        {
            string nombre = tokens[k++];
            int n = int.Parse(tokens[k++]);
            double[] serie = new double[n];
            for (int i = 0; i < n; i++)
                serie[i] = double.Parse(tokens[k++], System.Globalization.CultureInfo.InvariantCulture);
            if (primera == null) primera = serie;

            Console.WriteLine("CASE " + nombre);
            OUFit p = h.Calibrate(serie);
            if (p.Ok)
                Console.WriteLine(string.Format(System.Globalization.CultureInfo.InvariantCulture,
                    "OU 1 {0:F10} {1:F10} {2:F10} {3:F10} {4:F10} {5:F10} {6:F10} {7}",
                    p.Theta, p.Mu, p.Sigma, p.SigmaEq, p.HalfLife, p.Z, p.DfStat,
                    p.Estacionaria ? 1 : 0));
            else
                Console.WriteLine(string.Format(System.Globalization.CultureInfo.InvariantCulture,
                    "OU 0 0.0000000000 0.0000000000 0.0000000000 0.0000000000 0.0000000000 "
                    + "0.0000000000 {0:F10} {1}",
                    p.DfStat == double.MinValue ? 0.0 : p.DfStat, p.Estacionaria ? 1 : 0));

            double[] rets = new double[n - 1];
            for (int i = 1; i < n; i++) rets[i - 1] = serie[i] - serie[i - 1];
            RegimeFit r = h.MarkovRegime(rets, h.RegimenK, 1.0);
            if (r.Ok)
                Console.WriteLine(string.Format(System.Globalization.CultureInfo.InvariantCulture,
                    "REG 1 {0} {1:F10} {2:F10} {3} {4}",
                    r.Estado, r.Persistencia, r.Chi2, r.Df, r.HayMemoria ? 1 : 0));
            else
                Console.WriteLine("REG 0 0 0.0000000000 0.0000000000 0 0");
        }

        double[] zs = { -2.0, 2.0, -1.0, -0.2, -3.5, -2.0, -2.0, 0.2, 3.5, 2.0 };
        int[] prevs = { 0, 0, 0, 1, 1, 1, 1, -1, -1, -1 };
        int[] helds = { 0, 0, 0, 5, 5, 5, 31, 5, 5, 40 };
        for (int i = 0; i < zs.Length; i++)
        {
            string motivo;
            int t = h.TargetPosition(zs[i], prevs[i], helds[i], 10.0, out motivo);
            Console.WriteLine(string.Format(System.Globalization.CultureInfo.InvariantCulture,
                "POS {0:F4} {1} {2} {3:F4} -> {4}", zs[i], prevs[i], helds[i], 10.0, t));
        }

        // Bucle rodante con la misma convención de ventana que usa OnBarUpdate.
        int V = ROLL_V;
        for (int t = V - 1; t < primera.Length; t++)
        {
            double[] w = new double[V];
            for (int i = 0; i < V; i++) w[i] = primera[t - V + 1 + i];
            OUFit p = h.Calibrate(w);
            if (p.Ok)
                Console.WriteLine(string.Format(System.Globalization.CultureInfo.InvariantCulture,
                    "ROLL {0} 1 {1:F10} {2:F10} {3:F10} {4:F10} {5:F10}",
                    t, p.Theta, p.Mu, p.SigmaEq, p.HalfLife, p.Z));
            else
                Console.WriteLine(string.Format(System.Globalization.CultureInfo.InvariantCulture,
                    "ROLL {0} 0 0.0000000000 0.0000000000 0.0000000000 0.0000000000 0.0000000000", t));
        }
    }
}
'''


def extraer_math_cs() -> str:
    s = open(CS, encoding="utf-8-sig").read()
    m = re.search(r"// ===== BEGIN PORTABLE MATH =====(.*?)// ===== END PORTABLE MATH =====",
                  s, re.S)
    if not m:
        raise RuntimeError("No encontré los marcadores PORTABLE MATH en el archivo de NinjaTrader.")
    return m.group(1)


def correr_csharp(fixture: str, work: str) -> list[str]:
    fuente = (CS_SHELL.replace("__MATH__", extraer_math_cs())
              .replace("ROLL_V", str(ROLL_VENTANA)))
    cs = os.path.join(work, "Harness.cs")
    with open(cs, "w", encoding="utf-8") as fh:
        fh.write(fuente)
    exe = os.path.join(work, "harness.exe")
    r = subprocess.run(["mcs", "-optimize+", "-out:" + exe, cs], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("mcs falló sobre la matemática de C#:\n" + r.stdout[:2000] + r.stderr[:2000])
    out = subprocess.run(["mono", exe, fixture], capture_output=True, text=True, check=True)
    return out.stdout.strip().splitlines()


# ------------------------------------------------------------------ comparación
def comparar(nombre: str, esperado: list[str], obtenido: list[str]) -> int:
    if len(esperado) != len(obtenido):
        print(f"  FALLA {nombre}: {len(obtenido)} líneas vs {len(esperado)} esperadas")
        return 1
    fallos = 0
    for i, (a, b) in enumerate(zip(esperado, obtenido)):
        ta, tb = a.split(), b.split()
        if len(ta) != len(tb) or ta[0] != tb[0]:
            print(f"  FALLA {nombre} línea {i}: '{b}' vs '{a}'")
            fallos += 1
            continue
        for va, vb in zip(ta, tb):
            if va == vb:
                continue
            try:
                if abs(float(va) - float(vb)) <= TOL:
                    continue
            except ValueError:
                pass
            print(f"  FALLA {nombre} línea {i}: '{b}'\n         esperado: '{a}'")
            fallos += 1
            break
    return fallos


def main() -> int:
    if not shutil.which("g++"):
        print("Falta g++: no se puede verificar el port de MQL5.")
        return 2
    if not shutil.which("mcs") or not shutil.which("mono"):
        print("Falta mono/mcs: no se puede verificar el port de C#.")
        return 2

    work = tempfile.mkdtemp(prefix="ou_ports_")
    try:
        fixture = os.path.join(work, "series.txt")
        with open(fixture, "w", encoding="utf-8") as fh:
            for nombre, serie in casos().items():
                fh.write(f"{nombre} {len(serie)}\n")
                fh.write(" ".join(f"{v:.17g}" for v in serie) + "\n")

        esperado = referencia()
        print(f"Referencia de Python: {len(esperado)} líneas sobre {len(casos())} series.")

        fallos = 0
        print("\nMQL5 (trading/mt5/Include/OUMath.mqh, compilado como C++):")
        f = comparar("MQL5", esperado, correr_mql5(fixture, work))
        fallos += f
        if f == 0:
            print("  ok   idéntico al motor de Python dentro de 1e-9")

        print("\nC# (trading/ninjatrader/OUMeanReversion.cs, región PORTABLE MATH):")
        f = comparar("C#", esperado, correr_csharp(fixture, work))
        fallos += f
        if f == 0:
            print("  ok   idéntico al motor de Python dentro de 1e-9")

        print()
        if fallos:
            print(f"{fallos} discrepancias: los ports NO están alineados con quant/.")
            return 1
        print("Los tres motores (Python, MQL5, C#) coinciden en OU, Markov y reglas de posición.")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
