// ---------------------------------------------------------------------------
//  OUMeanReversion.cs — NinjaTrader 8
//
//  Reversión a la media con proceso de Ornstein-Uhlenbeck, pensada para
//  futuros (ES, NQ, MES, MNQ, CL, GC, ZN...) en cuenta de simulación.
//
//  Modelo:  dX = theta*(mu - X)*dt + sigma*dW,  con X = log del precio.
//  Se calibra en cada barra sobre una ventana móvil por la discretización
//  exacta del OU (que es un AR(1)) y se opera el z-score:
//
//      z <= -Entrada  -> largo        z >= +Entrada -> corto
//      |z| <= Salida  -> cerrar       |z| >= Stop   -> cerrar
//      barras > k*half-life           -> cerrar por tiempo
//
//  Gate estadístico (activado por defecto): sólo opera si el test de
//  Dickey-Fuller rechaza la raíz unitaria al 5%. Toda serie finita produce
//  un half-life; eso no prueba que haya reversión. Si la estrategia no
//  abre operaciones, la lectura correcta es "en este contrato y timeframe
//  no hay reversión que operar", no "está rota".
//
//  Filtro opcional de régimen por cadena de Markov de 3 estados, que sólo
//  se activa si un test chi-cuadrado encuentra memoria real en los datos.
//
//  Port del motor validado en Python (turpial-finanzas/quant/), donde 22
//  tests verifican que recupera los parámetros de procesos simulados y que
//  NO genera señal sobre un random walk.
//
//  Instalación: Herramientas > Importar > Archivo NinjaScript, o copiar a
//  Documents\NinjaTrader 8\bin\Custom\Strategies\ y compilar (F5).
//
//  Esto es investigación cuantitativa, no asesoramiento financiero.
// ---------------------------------------------------------------------------

#region Using declarations
using System;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.Gui;
using NinjaTrader.NinjaScript;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class OUMeanReversion : Strategy
    {
        // ---- Valores críticos de Dickey-Fuller (con constante, sin tendencia).
        //      El t-stat de (b-1) no sigue una t de Student bajo raíz unitaria.
        private const double DfCrit5 = -2.86;

        // ---- Chi-cuadrado al 5% por grados de libertad (df <= 4 con 3 estados).
        private static readonly double[] Chi2Crit5 = { 0.0, 3.841, 5.991, 7.815, 9.488 };

        private int barsHeld;
        private bool avisoSinReversion;

        #region Parámetros
        [NinjaScriptProperty]
        [Range(50, int.MaxValue)]
        [Display(Name = "Ventana", Description = "Barras de la ventana de calibración", Order = 1, GroupName = "1 Calibración")]
        public int Ventana { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Exigir Dickey-Fuller", Description = "Operar sólo si el test rechaza la raíz unitaria al 5%", Order = 2, GroupName = "1 Calibración")]
        public bool ExigirDF { get; set; }

        [NinjaScriptProperty]
        [Range(0, double.MaxValue)]
        [Display(Name = "Half-life máximo", Description = "Half-life máximo aceptado en barras (0 = sin límite)", Order = 3, GroupName = "1 Calibración")]
        public double MaxHalfLife { get; set; }

        [NinjaScriptProperty]
        [Range(0.1, 10.0)]
        [Display(Name = "z de entrada", Order = 1, GroupName = "2 Señales")]
        public double EntradaZ { get; set; }

        [NinjaScriptProperty]
        [Range(0.0, 5.0)]
        [Display(Name = "z de salida", Order = 2, GroupName = "2 Señales")]
        public double SalidaZ { get; set; }

        [NinjaScriptProperty]
        [Range(0.5, 15.0)]
        [Display(Name = "z de stop", Order = 3, GroupName = "2 Señales")]
        public double StopZ { get; set; }

        [NinjaScriptProperty]
        [Range(0.1, 50.0)]
        [Display(Name = "Cierre por tiempo (× half-life)", Order = 4, GroupName = "2 Señales")]
        public double MaxHoldHL { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Usar filtro de régimen", Description = "Cadena de Markov: no abrir contra una tendencia persistente", Order = 1, GroupName = "3 Régimen")]
        public bool UsarRegimen { get; set; }

        [NinjaScriptProperty]
        [Range(0.05, 3.0)]
        [Display(Name = "Umbral de régimen (k·σ)", Order = 2, GroupName = "3 Régimen")]
        public double RegimenK { get; set; }

        [NinjaScriptProperty]
        [Range(0.0, 1.0)]
        [Display(Name = "Persistencia mínima", Description = "P_ii a partir del cual el filtro bloquea", Order = 3, GroupName = "3 Régimen")]
        public double PersistMin { get; set; }

        [NinjaScriptProperty]
        [Range(1, int.MaxValue)]
        [Display(Name = "Contratos", Order = 1, GroupName = "4 Operativa")]
        public int Contratos { get; set; }

        [NinjaScriptProperty]
        [Range(0, int.MaxValue)]
        [Display(Name = "Stop duro (ticks)", Description = "Red de seguridad además del stop por z (0 = sin stop duro)", Order = 2, GroupName = "4 Operativa")]
        public int StopTicks { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Filtrar por horario", Description = "Operar sólo dentro de la franja indicada", Order = 3, GroupName = "4 Operativa")]
        public bool UsarHorario { get; set; }

        [NinjaScriptProperty]
        [Range(0, 2359)]
        [Display(Name = "Hora de inicio (HHmm)", Order = 4, GroupName = "4 Operativa")]
        public int HoraInicio { get; set; }

        [NinjaScriptProperty]
        [Range(0, 2359)]
        [Display(Name = "Hora de fin (HHmm)", Order = 5, GroupName = "4 Operativa")]
        public int HoraFin { get; set; }

        [NinjaScriptProperty]
        [Display(Name = "Log detallado", Order = 6, GroupName = "4 Operativa")]
        public bool LogVerboso { get; set; }
        #endregion

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Description = "Reversión a la media con Ornstein-Uhlenbeck y filtro de régimen de Markov";
                Name        = "OUMeanReversion";

                // Se decide en el cierre de cada barra, igual que el backtest de referencia.
                Calculate                 = Calculate.OnBarClose;
                EntriesPerDirection       = 1;
                EntryHandling             = EntryHandling.AllEntries;
                IsExitOnSessionCloseStrategy = true;   // futuros: no dejar posición al cierre
                ExitOnSessionCloseSeconds = 60;
                BarsRequiredToTrade       = 260;
                IncludeCommission         = true;      // el edge de reversión es chico: los costos importan

                Ventana     = 250;
                ExigirDF    = true;
                MaxHalfLife = 200;
                EntradaZ    = 1.5;
                SalidaZ     = 0.5;
                StopZ       = 3.0;
                MaxHoldHL   = 3.0;
                UsarRegimen = true;
                RegimenK    = 0.5;
                PersistMin  = 0.6;
                Contratos   = 1;
                StopTicks   = 0;
                UsarHorario = false;
                HoraInicio  = 930;
                HoraFin     = 1545;
                LogVerboso  = false;
            }
            else if (State == State.Configure)
            {
                if (StopTicks > 0)
                    SetStopLoss(CalculationMode.Ticks, StopTicks);

                if (BarsRequiredToTrade < Ventana + 10)
                    BarsRequiredToTrade = Ventana + 10;
            }
            else if (State == State.DataLoaded)
            {
                barsHeld = 0;
                avisoSinReversion = false;
            }
        }

        protected override void OnBarUpdate()
        {
            if (CurrentBar < Ventana + 1)
                return;

            // ---- 1) Ventana de log-precios, en orden cronológico.
            double[] x = new double[Ventana];
            for (int i = 0; i < Ventana; i++)
            {
                double c = Close[Ventana - 1 - i];
                if (c <= 0)
                    return;
                x[i] = Math.Log(c);
            }

            // ---- 2) Calibración del OU (sólo con datos hasta esta barra).
            OUFit p = Calibrate(x);

            // ---- 3) Régimen de Markov sobre los retornos de la misma ventana.
            RegimeFit reg = null;
            if (UsarRegimen)
            {
                double[] rets = new double[Ventana - 1];
                for (int i = 1; i < Ventana; i++)
                    rets[i - 1] = x[i] - x[i - 1];
                reg = MarkovRegime(rets, RegimenK);
            }

            int posActual = PosicionActual();
            string motivo;
            bool operable = ModeloOperable(p, out motivo);
            int objetivo;

            if (operable)
            {
                objetivo = TargetPosition(p.Z, posActual, barsHeld, p.HalfLife, out motivo);

                if (objetivo != posActual && objetivo != 0 && UsarRegimen && !RegimeAllows(objetivo, reg))
                {
                    objetivo = posActual;
                    motivo   = "bloqueado por régimen persistente";
                }

                // El horario sólo restringe aperturas; los cierres se ejecutan siempre.
                if (objetivo != posActual && objetivo != 0 && UsarHorario && !EnHorario())
                {
                    objetivo = posActual;
                    motivo   = "fuera de la franja horaria";
                }

                avisoSinReversion = false;
            }
            else
            {
                objetivo = 0;   // sin reversión sostenible no se sostiene la posición
                if (!avisoSinReversion)
                {
                    Print(Time[0] + "  Sin reversión operable: " + motivo);
                    avisoSinReversion = true;
                }
            }

            if (LogVerboso && operable)
                Print(string.Format("{0}  z={1:F3} half-life={2:F1} df={3:F2} pos={4} -> {5} ({6})",
                                    Time[0], p.Z, p.HalfLife, p.DfStat, posActual, objetivo, motivo));

            // ---- 4) Ejecución.
            if (objetivo != posActual)
                Ejecutar(posActual, objetivo, p, motivo);

            // ---- 5) Contador de permanencia (misma regla que el backtest de referencia:
            //      al abrir vale 1, mientras se mantiene suma 1, fuera del mercado 0).
            int posFinal = PosicionActual();
            if (posFinal == 0)              barsHeld = 0;
            else if (posFinal == posActual) barsHeld++;
            else                            barsHeld = 1;
        }

        // -------------------------------------------------------------------
        private void Ejecutar(int actual, int objetivo, OUFit p, string motivo)
        {
            if (actual == 1 && objetivo != 1)
                ExitLong("salidaL", "OU_L");
            else if (actual == -1 && objetivo != -1)
                ExitShort("salidaC", "OU_C");

            if (objetivo == 1)
                EnterLong(Contratos, "OU_L");
            else if (objetivo == -1)
                EnterShort(Contratos, "OU_C");

            if (LogVerboso && objetivo != 0)
                Print(string.Format("{0}  {1} {2} contratos · z={3:F2} half-life={4:F0} · {5}",
                                    Time[0], objetivo == 1 ? "LARGO" : "CORTO",
                                    Contratos, p.Z, p.HalfLife, motivo));
        }

        private int PosicionActual()
        {
            if (Position.MarketPosition == MarketPosition.Long)  return 1;
            if (Position.MarketPosition == MarketPosition.Short) return -1;
            return 0;
        }

        private bool EnHorario()
        {
            int ahora = Time[0].Hour * 100 + Time[0].Minute;
            if (HoraInicio <= HoraFin)
                return ahora >= HoraInicio && ahora <= HoraFin;
            return ahora >= HoraInicio || ahora <= HoraFin;   // franja que cruza medianoche
        }

        private bool ModeloOperable(OUFit p, out string motivo)
        {
            if (!p.Ok)
            {
                motivo = p.Motivo;
                return false;
            }
            if (ExigirDF && !p.Estacionaria)
            {
                motivo = string.Format(
                    "Dickey-Fuller {0:F2} no rechaza la raíz unitaria al 5% (crítico {1:F2}): " +
                    "el half-life de {2:F1} barras es un artefacto de la muestra",
                    p.DfStat, DfCrit5, p.HalfLife);
                return false;
            }
            if (MaxHalfLife > 0 && p.HalfLife > MaxHalfLife)
            {
                motivo = string.Format("half-life de {0:F1} barras supera el máximo ({1:F1})",
                                       p.HalfLife, MaxHalfLife);
                return false;
            }
            if (p.SigmaEq <= 0)
            {
                motivo = "sigma_eq no positivo";
                return false;
            }
            motivo = "";
            return true;
        }

        // ===== BEGIN PORTABLE MATH =====
        //  Todo lo que sigue hasta END PORTABLE MATH no depende de NinjaTrader:
        //  trading/tests/verify_ports.py lo extrae, lo compila y lo corre contra
        //  el motor de Python para verificar que el port da los mismos números.
        // -------------------------------------------------------------------
        //  Reglas de posición — espejo de quant/strategies.py
        // -------------------------------------------------------------------
        private int TargetPosition(double z, int prev, int held, double halfLife, out string motivo)
        {
            double maxBars = Math.Max(1.0, MaxHoldHL * halfLife);

            if (prev == 0)
            {
                if (z <= -EntradaZ) { motivo = "entrada larga: z bajo el umbral";  return 1; }
                if (z >=  EntradaZ) { motivo = "entrada corta: z sobre el umbral"; return -1; }
                motivo = "sin señal";
                return 0;
            }

            if (held >= maxBars)
            {
                motivo = string.Format("tiempo agotado: {0:F1}× half-life sin reversión", MaxHoldHL);
                return 0;
            }

            if (prev == 1)
            {
                if (z <= -StopZ)   { motivo = "stop: la desviación siguió creciendo"; return 0; }
                if (z >= -SalidaZ) { motivo = "objetivo: volvió al equilibrio";       return 0; }
                motivo = "mantener larga";
                return 1;
            }

            if (z >=  StopZ)   { motivo = "stop: la desviación siguió creciendo"; return 0; }
            if (z <=  SalidaZ) { motivo = "objetivo: volvió al equilibrio";       return 0; }
            motivo = "mantener corta";
            return -1;
        }

        private bool RegimeAllows(int target, RegimeFit reg)
        {
            if (target == 0 || reg == null || !reg.Ok) return true;
            if (!reg.HayMemoria)                       return true;   // sin evidencia, no se filtra
            if (reg.Persistencia < PersistMin)         return true;
            if (target ==  1 && reg.Estado == 0)       return false;  // no comprar en régimen bajista
            if (target == -1 && reg.Estado == 2)       return false;  // no vender en régimen alcista
            return true;
        }

        // -------------------------------------------------------------------
        //  Matemática: OLS, Ornstein-Uhlenbeck y cadena de Markov
        // -------------------------------------------------------------------
        private class OUFit
        {
            public bool   Ok;
            public double Theta, Mu, Sigma, SigmaEq, HalfLife, Ar1B, R2, DfStat, Z, Last;
            public bool   Estacionaria;
            public string Motivo = "";
        }

        private class RegimeFit
        {
            public bool   Ok;
            public int    Estado;
            public double Persistencia, DuracionMedia, Chi2;
            public int    Df;
            public bool   HayMemoria;
        }

        private static double Mean(double[] v, int n)
        {
            double s = 0;
            for (int i = 0; i < n; i++) s += v[i];
            return n > 0 ? s / n : 0;
        }

        private static double Stdev(double[] v, int n)
        {
            if (n < 2) return 0;
            double m = Mean(v, n), acc = 0;
            for (int i = 0; i < n; i++) acc += (v[i] - m) * (v[i] - m);
            return Math.Sqrt(acc / (n - 1));
        }

        /// <summary>Mínimos cuadrados de y = a + b·x. false si el regresor es constante.</summary>
        private static bool LinReg(double[] x, double[] y, int n,
                                   out double a, out double b, out double seB,
                                   out double residStd, out double r2)
        {
            a = b = seB = residStd = r2 = 0;
            if (n < 3) return false;

            double mx = Mean(x, n), my = Mean(y, n), sxx = 0, sxy = 0, sst = 0;
            for (int i = 0; i < n; i++)
            {
                double dx = x[i] - mx, dy = y[i] - my;
                sxx += dx * dx; sxy += dx * dy; sst += dy * dy;
            }
            if (sxx <= 0) return false;

            b = sxy / sxx;
            a = my - b * mx;

            double sse = 0;
            for (int i = 0; i < n; i++)
            {
                double e = y[i] - (a + b * x[i]);
                sse += e * e;
            }
            double s2 = sse / (n - 2);
            seB      = Math.Sqrt(s2 / sxx);
            residStd = Math.Sqrt(s2);
            r2       = sst > 0 ? 1.0 - sse / sst : 0;
            return true;
        }

        /// <summary>
        /// Calibra el OU por su discretización exacta AR(1):
        ///   X[i+1] = a + b·X[i] + eps,  b = exp(-theta·dt)
        ///   theta = -ln(b)   mu = a/(1-b)   sigma = s_eps·sqrt(2·theta/(1-b²))
        /// </summary>
        private OUFit Calibrate(double[] serie)
        {
            OUFit p = new OUFit();
            int n = serie.Length;
            p.Last = n > 0 ? serie[n - 1] : 0;

            if (n < 30)
            {
                p.Motivo = "Serie demasiado corta para calibrar";
                return p;
            }

            int m = n - 1;
            double[] xs = new double[m], ys = new double[m];
            for (int i = 0; i < m; i++) { xs[i] = serie[i]; ys[i] = serie[i + 1]; }

            double a, b, seB, sEps, r2;
            if (!LinReg(xs, ys, m, out a, out b, out seB, out sEps, out r2))
            {
                p.Motivo = "Regresor constante: pendiente indefinida";
                return p;
            }

            p.Ar1B  = b;
            p.R2    = r2;
            // Dickey-Fuller: t-stat de (b-1) en ΔX = a + (b-1)·X + eps.
            p.DfStat       = seB > 0 ? (b - 1.0) / seB : double.MinValue;
            p.Estacionaria = p.DfStat < DfCrit5;

            if (b <= 0) { p.Motivo = "Pendiente AR(1) <= 0: oscilación, no reversión"; return p; }
            if (b >= 1) { p.Motivo = "Pendiente AR(1) >= 1: random walk o explosiva";  return p; }

            p.Theta    = -Math.Log(b);
            p.Mu       = a / (1.0 - b);
            p.Sigma    = sEps * Math.Sqrt(2.0 * p.Theta / (1.0 - b * b));
            p.SigmaEq  = sEps / Math.Sqrt(1.0 - b * b);
            p.HalfLife = Math.Log(2.0) / p.Theta;
            p.Z        = p.SigmaEq > 0 ? (p.Last - p.Mu) / p.SigmaEq : 0;
            p.Ok       = true;
            return p;
        }

        /// <summary>
        /// Régimen de mercado por cadena de Markov de 3 estados
        /// (0 bajista, 1 lateral, 2 alcista) con umbrales ±k·σ, suavizado de
        /// Laplace y test chi-cuadrado de independencia contra tabla al 5%.
        /// </summary>
        private RegimeFit MarkovRegime(double[] rets, double k, double alpha = 1.0)
        {
            RegimeFit r = new RegimeFit();
            int n = rets.Length;
            if (n < 10) return r;

            double sd = Stdev(rets, n);
            if (sd <= 0) return r;

            double lo = -k * sd, hi = k * sd;
            int[] estados = new int[n];
            for (int i = 0; i < n; i++)
                estados[i] = rets[i] < lo ? 0 : (rets[i] > hi ? 2 : 1);

            int[,] counts = new int[3, 3];
            for (int i = 0; i < n - 1; i++)
                counts[estados[i], estados[i + 1]]++;

            double[,] P = new double[3, 3];
            for (int i = 0; i < 3; i++)
            {
                double fila = 0;
                for (int j = 0; j < 3; j++) fila += counts[i, j];
                double den = fila + alpha * 3.0;
                for (int j = 0; j < 3; j++) P[i, j] = (counts[i, j] + alpha) / den;
            }

            double total = 0;
            double[] filas = new double[3], cols = new double[3];
            for (int i = 0; i < 3; i++)
                for (int j = 0; j < 3; j++)
                {
                    filas[i] += counts[i, j];
                    cols[j]  += counts[i, j];
                    total    += counts[i, j];
                }
            if (total <= 0) return r;

            double stat = 0;
            int penal = 0;
            for (int i = 0; i < 3; i++)
                for (int j = 0; j < 3; j++)
                {
                    double e = filas[i] * cols[j] / total;
                    if (e <= 0) { penal++; continue; }
                    double d = counts[i, j] - e;
                    stat += d * d / e;
                }

            r.Chi2       = stat;
            r.Df         = Math.Max(4 - penal, 1);
            r.HayMemoria = stat > Chi2Crit5[Math.Min(r.Df, 4)];
            r.Estado     = estados[n - 1];
            r.Persistencia  = P[r.Estado, r.Estado];
            r.DuracionMedia = 1.0 / (1.0 - Math.Min(r.Persistencia, 1.0 - 1e-12));
            r.Ok = true;
            return r;
        }
        // ===== END PORTABLE MATH =====
    }
}
