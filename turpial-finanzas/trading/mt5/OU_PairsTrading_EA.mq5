//+------------------------------------------------------------------+
//|  OU_PairsTrading_EA.mq5                                          |
//|  Arbitraje estadístico: cointegración + Ornstein-Uhlenbeck.      |
//|                                                                  |
//|  Un precio suelto casi nunca revierte — el test de Dickey-Fuller  |
//|  lo rechaza una y otra vez. Pero la combinación lineal de dos     |
//|  activos relacionados sí puede ser estacionaria. Ahí el OU deja   |
//|  de ser una analogía y pasa a ser el modelo correcto.             |
//|                                                                  |
//|  Engle-Granger en dos etapas, recalculado en cada barra:          |
//|    1) log A = alpha + beta*log B + s   (beta = hedge ratio)       |
//|    2) test de raíz unitaria sobre el spread s, con los valores    |
//|       críticos de Engle-Granger (más exigentes que Dickey-Fuller  |
//|       porque beta se estimó de los mismos datos).                 |
//|  Si el spread pasa, se lo modela como OU y se opera su z-score.   |
//|                                                                  |
//|  Posición larga del spread = comprar A y vender B (beta unidades  |
//|  en valor); corta = al revés. Las patas se dimensionan por        |
//|  valor nocional para que el par quede neutral a movimientos       |
//|  comunes.                                                         |
//|                                                                  |
//|  Requiere que AMBOS símbolos estén en el Observador de Mercado.   |
//|  Para el tester: modo "1 minuto OHLC" o "cada tick real", y que   |
//|  el historial del símbolo B esté descargado.                      |
//|                                                                  |
//|  Esto es investigación cuantitativa, no asesoramiento financiero. |
//+------------------------------------------------------------------+
#property copyright "Turpial Finanzas"
#property link      "https://github.com/carlospallottini-spec/Agentes-"
#property version   "1.00"
#property description "Pares cointegrados con Ornstein-Uhlenbeck sobre el spread"

#include <Trade\Trade.mqh>
#include "Include\OUMath.mqh"

input group "── Par ──"
input string           InpSymbolB       = "";      // Símbolo B (el A es el del gráfico)
input int              InpVentana       = 250;     // Ventana de calibración (barras)
input int              InpMinPuntos     = 30;      // Mínimo de puntos para calibrar

input group "── Gate estadístico ──"
input bool             InpExigirEG      = true;    // Exigir cointegración (Engle-Granger 5%)
input double           InpMaxHalfLife   = 120.0;   // Half-life máximo del spread (barras; 0 = sin límite)
input double           InpMinR2         = 0.30;    // R² mínimo de la regresión de cointegración

input group "── Señales de z-score ──"
input double           InpEntradaZ      = 2.0;     // z de entrada
input double           InpSalidaZ       = 0.5;     // z de salida
input double           InpStopZ         = 3.5;     // z de stop
input double           InpMaxHoldHL     = 3.0;     // Cierre por tiempo (múltiplos del half-life)

input group "── Tamaño y operativa ──"
input double           InpLotesA        = 0.10;    // Lote de la pata A
input double           InpMaxLotesB     = 10.0;    // Tope de seguridad para la pata B
input long             InpMagic         = 20260828; // Número mágico
input int              InpDesvioPuntos  = 30;      // Desviación máxima (slippage)
input bool             InpDiagnosticoCSV= false;   // Exportar diagnóstico a CSV
input bool             InpLogVerboso    = false;   // Log detallado

//--- Estado
CTrade    g_trade;
string    g_symA = "";
string    g_symB = "";
datetime  g_ultima_barra = 0;
int       g_bars_held    = 0;
int       g_csv_handle   = INVALID_HANDLE;
bool      g_aviso_sin_coint = false;

//+------------------------------------------------------------------+
int OnInit()
  {
   g_symA = _Symbol;
   g_symB = InpSymbolB;
   StringTrimLeft(g_symB);
   StringTrimRight(g_symB);

   if(g_symB == "" || g_symB == g_symA)
     {
      Print("ERROR: configurá un símbolo B distinto del símbolo del gráfico.");
      return(INIT_PARAMETERS_INCORRECT);
     }
   if(!SymbolSelect(g_symB, true))
     {
      Print("ERROR: no se pudo seleccionar ", g_symB, " en el Observador de Mercado.");
      return(INIT_PARAMETERS_INCORRECT);
     }
   if(InpVentana < InpMinPuntos + 1)
     {
      Print("ERROR: la ventana debe ser mayor que el mínimo de puntos.");
      return(INIT_PARAMETERS_INCORRECT);
     }
   if(InpEntradaZ <= InpSalidaZ || InpStopZ <= InpEntradaZ)
     {
      Print("ERROR: se espera salida < entrada < stop.");
      return(INIT_PARAMETERS_INCORRECT);
     }

   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetDeviationInPoints(InpDesvioPuntos);
   g_trade.LogLevel(InpLogVerboso ? LOG_LEVEL_ALL : LOG_LEVEL_ERRORS);

   if(InpDiagnosticoCSV)
     {
      string nombre = StringFormat("OU_pares_%s_%s_%s.csv", g_symA, g_symB,
                                   EnumToString((ENUM_TIMEFRAMES)Period()));
      g_csv_handle = FileOpen(nombre, FILE_WRITE | FILE_CSV | FILE_ANSI, ';');
      if(g_csv_handle != INVALID_HANDLE)
         FileWrite(g_csv_handle, "time", "beta", "alpha", "r2", "eg_stat", "cointegrado",
                   "half_life", "spread", "mu_abs", "sigma_eq", "z",
                   "pos_actual", "pos_objetivo", "motivo");
     }

   PrintFormat("OU pares listo · %s vs %s · ventana %d · gate Engle-Granger %s",
               g_symA, g_symB, InpVentana, InpExigirEG ? "ACTIVADO" : "desactivado");
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   if(g_csv_handle != INVALID_HANDLE) FileClose(g_csv_handle);
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   datetime barra = iTime(g_symA, PERIOD_CURRENT, 0);
   if(barra == g_ultima_barra) return;
   g_ultima_barra = barra;
   ProcesarBarra();
  }

//+------------------------------------------------------------------+
//| Series alineadas por timestamp. Sin fechas comunes no hay spread. |
//+------------------------------------------------------------------+
bool SeriesAlineadas(double &la[], double &lb[], const int necesarias)
  {
   int pedir = necesarias * 3 + 50;   // holgura por feriados y huecos de sesión
   MqlRates ra[], rb[];
   ArraySetAsSeries(ra, true);
   ArraySetAsSeries(rb, true);

   int na = CopyRates(g_symA, PERIOD_CURRENT, 1, pedir, ra);
   int nb = CopyRates(g_symB, PERIOD_CURRENT, 1, pedir, rb);
   if(na < necesarias || nb < necesarias) return(false);

   double ta[], tb[];
   ArrayResize(ta, necesarias);
   ArrayResize(tb, necesarias);

   //--- Dos punteros desde la barra más reciente hacia atrás.
   int i = 0, j = 0, k = 0;
   while(i < na && j < nb && k < necesarias)
     {
      if(ra[i].time == rb[j].time)
        {
         if(ra[i].close <= 0.0 || rb[j].close <= 0.0) return(false);
         ta[k] = MathLog(ra[i].close);
         tb[k] = MathLog(rb[j].close);
         k++; i++; j++;
        }
      else if(ra[i].time > rb[j].time) i++;
      else                             j++;
     }
   if(k < necesarias) return(false);

   //--- Invertir a orden cronológico (viejo -> nuevo).
   ArrayResize(la, necesarias);
   ArrayResize(lb, necesarias);
   for(int m = 0; m < necesarias; m++)
     {
      la[m] = ta[necesarias - 1 - m];
      lb[m] = tb[necesarias - 1 - m];
     }
   return(true);
  }

//+------------------------------------------------------------------+
void ProcesarBarra()
  {
   double la[], lb[];
   if(!SeriesAlineadas(la, lb, InpVentana)) return;

   //--- 1) Regresión de cointegración: log A = alpha + beta*log B + spread.
   double alpha, beta, se_b, resid_std, r2;
   if(!OULinReg(lb, la, InpVentana, alpha, beta, se_b, resid_std, r2)) return;

   double spread[];
   ArrayResize(spread, InpVentana);
   for(int i = 0; i < InpVentana; i++) spread[i] = la[i] - (alpha + beta * lb[i]);

   //--- 2) OU sobre el spread.
   OUParams p = OUCalibrate(spread, InpVentana, InpMinPuntos);

   double s_t    = la[InpVentana - 1] - beta * lb[InpVentana - 1];
   double mu_abs = alpha + (p.ok ? p.mu : 0.0);   // los residuos tienen media 0 por OLS
   double z      = (p.ok && p.sigma_eq > 0.0) ? (s_t - mu_abs) / p.sigma_eq : 0.0;

   //--- 3) Gate estadístico.
   string motivo   = "";
   bool   operable = ParOperable(p, r2, motivo);

   int pos_actual = PosicionActual();
   int objetivo   = 0;

   if(operable)
     {
      objetivo = OUTargetPosition(z, pos_actual, g_bars_held, p.half_life,
                                  InpEntradaZ, InpSalidaZ, InpStopZ, InpMaxHoldHL, motivo);
      g_aviso_sin_coint = false;
     }
   else
     {
      objetivo = 0;   // sin cointegración vigente no hay par que sostener
      if(!g_aviso_sin_coint)
        {
         Print("Par no operable: ", motivo);
         g_aviso_sin_coint = true;
        }
     }

   if(g_csv_handle != INVALID_HANDLE)
      FileWrite(g_csv_handle,
                TimeToString(iTime(g_symA, PERIOD_CURRENT, 1), TIME_DATE | TIME_MINUTES),
                DoubleToString(beta, 8), DoubleToString(alpha, 8), DoubleToString(r2, 8),
                DoubleToString(p.df_stat, 8), (p.df_stat < OU_EG_CRIT_5) ? "1" : "0",
                DoubleToString(p.half_life, 8), DoubleToString(s_t, 8),
                DoubleToString(mu_abs, 8), DoubleToString(p.sigma_eq, 8),
                DoubleToString(z, 8),
                IntegerToString(pos_actual), IntegerToString(objetivo), motivo);

   if(InpLogVerboso && operable)
      PrintFormat("beta=%.4f z=%.3f half-life=%.1f EG=%.2f pos=%d -> %d (%s)",
                  beta, z, p.half_life, p.df_stat, pos_actual, objetivo, motivo);

   if(objetivo != pos_actual) AjustarPar(pos_actual, objetivo, beta, z, motivo);

   int pos_final = PosicionActual();
   if(pos_final == 0)               g_bars_held = 0;
   else if(pos_final == pos_actual) g_bars_held++;
   else                             g_bars_held = 1;
  }

//+------------------------------------------------------------------+
//| Gate de cointegración: acá se decide si el par existe de verdad. |
//+------------------------------------------------------------------+
bool ParOperable(const OUParams &p, const double r2, string &motivo)
  {
   if(!p.ok) { motivo = p.motivo; return(false); }

   if(r2 < InpMinR2)
     {
      motivo = StringFormat("R² de cointegración %.2f por debajo del mínimo %.2f: "
                            "los activos no comparten suficiente movimiento", r2, InpMinR2);
      return(false);
     }
   if(InpExigirEG && p.df_stat >= OU_EG_CRIT_5)
     {
      motivo = StringFormat("Engle-Granger %.2f no rechaza al 5%% (crítico %.2f): "
                            "el spread no está cointegrado, el half-life de %.1f barras "
                            "no describe nada real", p.df_stat, OU_EG_CRIT_5, p.half_life);
      return(false);
     }
   if(InpMaxHalfLife > 0.0 && p.half_life > InpMaxHalfLife)
     {
      motivo = StringFormat("half-life de %.1f barras supera el máximo (%.1f): "
                            "capital inmovilizado demasiado tiempo por trade",
                            p.half_life, InpMaxHalfLife);
      return(false);
     }
   if(p.sigma_eq <= 0.0) { motivo = "sigma_eq no positivo"; return(false); }
   return(true);
  }

//+------------------------------------------------------------------+
//| Posición del par: +1 spread largo (A largo / B corto), -1 corto. |
//| Se determina por la pata A, que es la de referencia.              |
//+------------------------------------------------------------------+
int PosicionActual()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      if(PositionGetString(POSITION_SYMBOL) != g_symA) continue;
      return(PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY ? 1 : -1);
     }
   return(0);
  }

ulong TicketDe(const string simbolo)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      if(PositionGetString(POSITION_SYMBOL) != simbolo) continue;
      return(ticket);
     }
   return(0);
  }

//+------------------------------------------------------------------+
//| Valor en moneda de cuenta de 1 unidad de precio, por 1 lote.     |
//+------------------------------------------------------------------+
double ValorPorUnidad(const string simbolo)
  {
   double tick_value = SymbolInfoDouble(simbolo, SYMBOL_TRADE_TICK_VALUE);
   double tick_size  = SymbolInfoDouble(simbolo, SYMBOL_TRADE_TICK_SIZE);
   if(tick_value <= 0.0 || tick_size <= 0.0) return(0.0);
   return(tick_value / tick_size);
  }

//+------------------------------------------------------------------+
//| Lotes de la pata B para neutralizar el movimiento común.         |
//|                                                                  |
//| El spread está en logaritmos: un 1% en A mueve el spread 0.01 y   |
//| hace falta que beta*1% de B lo compense. En moneda de cuenta:     |
//|   nocional_B = |beta| * nocional_A                                |
//| con nocional = lotes * precio * (tick_value/tick_size).           |
//+------------------------------------------------------------------+
double LotesPataB(const double beta)
  {
   double pa = SymbolInfoDouble(g_symA, SYMBOL_BID);
   double pb = SymbolInfoDouble(g_symB, SYMBOL_BID);
   double va = ValorPorUnidad(g_symA);
   double vb = ValorPorUnidad(g_symB);
   if(pa <= 0.0 || pb <= 0.0 || va <= 0.0 || vb <= 0.0) return(0.0);

   double lotes = InpLotesA * MathAbs(beta) * (pa * va) / (pb * vb);
   lotes = MathMin(lotes, InpMaxLotesB);
   return(NormalizarVolumen(g_symB, lotes));
  }

//+------------------------------------------------------------------+
double NormalizarVolumen(const string simbolo, const double volumen)
  {
   double vmin = SymbolInfoDouble(simbolo, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(simbolo, SYMBOL_VOLUME_MAX);
   double paso = SymbolInfoDouble(simbolo, SYMBOL_VOLUME_STEP);
   if(paso <= 0.0) paso = 0.01;

   double v = MathRound(volumen / paso) * paso;
   if(v < vmin) v = vmin;
   if(v > vmax) v = vmax;
   int dec = (int)MathMax(0.0, MathCeil(-MathLog10(paso)));
   return(NormalizeDouble(v, dec));
  }

//+------------------------------------------------------------------+
//| Abre / cierra las dos patas de forma coordinada.                 |
//| Si la segunda pata falla, se revierte la primera: media posición  |
//| es peor que ninguna — deja de ser un par y queda direccional.     |
//+------------------------------------------------------------------+
void AjustarPar(const int actual, const int objetivo, const double beta,
                const double z, const string motivo)
  {
   if(actual != 0)
     {
      CerrarPar();
      if(InpLogVerboso) Print("Par cerrado por: ", motivo);
     }
   if(objetivo == 0) return;

   double lotesA = NormalizarVolumen(g_symA, InpLotesA);
   double lotesB = LotesPataB(beta);
   if(lotesA <= 0.0 || lotesB <= 0.0)
     {
      Print("Entrada omitida: volumen inválido (A=", lotesA, " B=", lotesB, ").");
      return;
     }

   //--- Con beta negativo las dos patas van en el mismo sentido.
   int dirA = objetivo;
   int dirB = (beta >= 0.0) ? -objetivo : objetivo;

   string com = StringFormat("OUpar z=%.2f b=%.3f", z, beta);

   g_trade.SetTypeFillingBySymbol(g_symA);
   bool okA = (dirA == 1) ? g_trade.Buy(lotesA, g_symA, 0.0, 0.0, 0.0, com)
                          : g_trade.Sell(lotesA, g_symA, 0.0, 0.0, 0.0, com);
   if(!okA)
     {
      PrintFormat("Pata A rechazada: %d (%s)", g_trade.ResultRetcode(),
                  g_trade.ResultRetcodeDescription());
      return;
     }

   g_trade.SetTypeFillingBySymbol(g_symB);
   bool okB = (dirB == 1) ? g_trade.Buy(lotesB, g_symB, 0.0, 0.0, 0.0, com)
                          : g_trade.Sell(lotesB, g_symB, 0.0, 0.0, 0.0, com);
   if(!okB)
     {
      PrintFormat("Pata B rechazada: %d (%s) — se revierte la pata A.",
                  g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
      CerrarPar();
      return;
     }

   if(InpLogVerboso)
      PrintFormat("Par abierto: %s %.2f %s / %s %.2f %s · %s",
                  dirA == 1 ? "compra" : "venta", lotesA, g_symA,
                  dirB == 1 ? "compra" : "venta", lotesB, g_symB, motivo);
  }

//+------------------------------------------------------------------+
void CerrarPar()
  {
   ulong tb = TicketDe(g_symB);
   if(tb != 0)
     {
      g_trade.SetTypeFillingBySymbol(g_symB);
      if(!g_trade.PositionClose(tb))
         PrintFormat("No se pudo cerrar la pata B (%I64u): %d", tb, g_trade.ResultRetcode());
     }
   ulong ta = TicketDe(g_symA);
   if(ta != 0)
     {
      g_trade.SetTypeFillingBySymbol(g_symA);
      if(!g_trade.PositionClose(ta))
         PrintFormat("No se pudo cerrar la pata A (%I64u): %d", ta, g_trade.ResultRetcode());
     }
  }
//+------------------------------------------------------------------+
