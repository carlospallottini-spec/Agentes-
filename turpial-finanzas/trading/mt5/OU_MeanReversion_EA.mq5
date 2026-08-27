//+------------------------------------------------------------------+
//|  OU_MeanReversion_EA.mq5                                         |
//|  Reversión a la media con proceso de Ornstein-Uhlenbeck.         |
//|                                                                  |
//|  En cada barra nueva calibra sobre una ventana móvil el proceso  |
//|      dX = theta*(mu - X)*dt + sigma*dW      (X = log del precio)  |
//|  y opera el z-score = (X - mu)/sigma_eq:                          |
//|      z <= -Entrada  -> largo   (el resorte está estirado abajo)   |
//|      z >= +Entrada  -> corto                                      |
//|      |z| <= Salida  -> cerrar (volvió al equilibrio)              |
//|      |z| >= Stop    -> cerrar (la tesis falló)                    |
//|      t  >  k*half-life -> cerrar (la fuerza ya debería haber      |
//|                          actuado; el modelo dejó de describir)    |
//|                                                                  |
//|  Filtro opcional de régimen por cadena de Markov: no abre contra  |
//|  una tendencia persistente, y sólo se activa si un test chi2      |
//|  encuentra memoria markoviana real.                               |
//|                                                                  |
//|  IMPORTANTE — el gate estadístico: por defecto sólo opera si el   |
//|  test de Dickey-Fuller rechaza la raíz unitaria al 5%. Toda serie |
//|  finita produce un half-life; eso no prueba que haya reversión.   |
//|  Si el EA no abre operaciones, la lectura correcta no es "está    |
//|  roto" sino "en este símbolo y timeframe no hay reversión que     |
//|  operar". Ponelo en false sabiendo lo que estás apagando.         |
//|                                                                  |
//|  Espejo en MQL5 del motor validado en Python (quant/), donde 22   |
//|  tests verifican que recupera los parámetros de procesos          |
//|  simulados conocidos y que NO genera señal en un random walk.     |
//|                                                                  |
//|  Esto es investigación cuantitativa, no asesoramiento financiero. |
//+------------------------------------------------------------------+
#property copyright "Turpial Finanzas"
#property link      "https://github.com/carlospallottini-spec/Agentes-"
#property version   "1.00"
#property description "Reversión a la media con Ornstein-Uhlenbeck + filtro de régimen de Markov"

#include <Trade\Trade.mqh>
#include "Include\OUMath.mqh"

//--- Dirección permitida
enum ENUM_DIRECCION
  {
   DIR_AMBAS = 0,  // Largos y cortos
   DIR_LARGO = 1,  // Sólo largos
   DIR_CORTO = 2   // Sólo cortos
  };

//--- Modo de tamaño de posición
enum ENUM_SIZING
  {
   SIZE_FIJO   = 0, // Lote fijo
   SIZE_RIESGO = 1  // % de riesgo sobre el stop duro (requiere stop duro > 0)
  };

input group "── Calibración del proceso ──"
input int              InpVentana        = 250;    // Ventana de calibración (barras)
input int              InpMinPuntos      = 30;     // Mínimo de puntos para calibrar
input bool             InpExigirDF       = true;   // Exigir Dickey-Fuller significativo al 5%
input double           InpMaxHalfLife    = 200.0;  // Half-life máximo aceptado (barras; 0 = sin límite)

input group "── Señales de z-score ──"
input double           InpEntradaZ       = 1.5;    // z de entrada
input double           InpSalidaZ        = 0.5;    // z de salida (objetivo)
input double           InpStopZ          = 3.0;    // z de stop (la tesis falló)
input double           InpMaxHoldHL      = 3.0;    // Cierre por tiempo (múltiplos del half-life)
input ENUM_DIRECCION   InpDireccion      = DIR_AMBAS; // Dirección permitida

input group "── Filtro de régimen (Markov) ──"
input bool             InpUsarRegimen    = true;   // Usar filtro de régimen
input double           InpRegimenK       = 0.5;    // Umbral de régimen (±k·σ de los retornos)
input double           InpPersistMin     = 0.6;    // Persistencia mínima para que el filtro bloquee

input group "── Gestión de la posición ──"
input ENUM_SIZING      InpModoLote       = SIZE_FIJO; // Modo de tamaño
input double           InpLotes          = 0.10;   // Lote fijo
input double           InpRiesgoPct      = 1.0;    // Riesgo por operación (% del balance)
input double           InpStopDuroATR    = 0.0;    // Stop duro en múltiplos de ATR (0 = sin stop duro)
input int              InpATRPeriodo     = 14;     // Período del ATR
input int              InpMaxSpreadPts   = 0;      // Spread máximo en puntos (0 = sin límite)

input group "── Operativa ──"
input long             InpMagic          = 20260827; // Número mágico
input int              InpDesvioPuntos   = 20;     // Desviación máxima (slippage) en puntos
input int              InpMinTradesFit   = 20;     // Trades mínimos para el criterio de optimización
input bool             InpDiagnosticoCSV = false;  // Exportar diagnóstico a CSV (carpeta Files)
input bool             InpLogVerboso     = false;  // Log detallado en el diario

//--- Estado
CTrade        g_trade;
datetime      g_ultima_barra = 0;
int           g_bars_held    = 0;
int           g_atr_handle   = INVALID_HANDLE;
int           g_csv_handle   = INVALID_HANDLE;
double        g_punto        = 0.0;
int           g_digitos      = 0;
bool          g_aviso_sin_reversion = false;

//+------------------------------------------------------------------+
//| Inicialización                                                   |
//+------------------------------------------------------------------+
int OnInit()
  {
   if(InpVentana < InpMinPuntos + 1)
     {
      Print("ERROR: la ventana (", InpVentana, ") debe ser mayor que el mínimo de puntos (",
            InpMinPuntos, ").");
      return(INIT_PARAMETERS_INCORRECT);
     }
   if(InpEntradaZ <= InpSalidaZ)
     {
      Print("ERROR: el z de entrada debe ser mayor que el de salida.");
      return(INIT_PARAMETERS_INCORRECT);
     }
   if(InpStopZ <= InpEntradaZ)
     {
      Print("ERROR: el z de stop debe ser mayor que el de entrada.");
      return(INIT_PARAMETERS_INCORRECT);
     }
   if(InpModoLote == SIZE_RIESGO && InpStopDuroATR <= 0.0)
     {
      Print("ERROR: el sizing por riesgo necesita un stop duro (InpStopDuroATR > 0).");
      return(INIT_PARAMETERS_INCORRECT);
     }

   g_punto   = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   g_digitos = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);

   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetDeviationInPoints(InpDesvioPuntos);
   g_trade.SetTypeFillingBySymbol(_Symbol);
   g_trade.LogLevel(InpLogVerboso ? LOG_LEVEL_ALL : LOG_LEVEL_ERRORS);

   if(InpStopDuroATR > 0.0)
     {
      g_atr_handle = iATR(_Symbol, PERIOD_CURRENT, InpATRPeriodo);
      if(g_atr_handle == INVALID_HANDLE)
        {
         Print("ERROR: no se pudo crear el handle del ATR.");
         return(INIT_FAILED);
        }
     }

   if(InpDiagnosticoCSV)
     {
      string nombre = StringFormat("OU_diag_%s_%s.csv", _Symbol,
                                   EnumToString((ENUM_TIMEFRAMES)Period()));
      g_csv_handle = FileOpen(nombre, FILE_WRITE | FILE_CSV | FILE_ANSI, ';');
      if(g_csv_handle != INVALID_HANDLE)
         FileWrite(g_csv_handle, "time", "close", "ok", "theta", "mu", "sigma_eq",
                   "half_life", "z", "df_stat", "estacionaria", "regimen",
                   "persistencia", "memoria", "pos_actual", "pos_objetivo", "motivo");
      else
         Print("AVISO: no se pudo abrir el CSV de diagnóstico (", GetLastError(), ").");
     }

   g_bars_held = BarrasDesdeApertura();

   PrintFormat("OU EA listo · %s %s · ventana %d · z entrada %.2f / salida %.2f / stop %.2f · "
               "gate Dickey-Fuller %s",
               _Symbol, EnumToString((ENUM_TIMEFRAMES)Period()), InpVentana,
               InpEntradaZ, InpSalidaZ, InpStopZ, InpExigirDF ? "ACTIVADO" : "desactivado");
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
//| Descarga                                                         |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   if(g_atr_handle != INVALID_HANDLE) IndicatorRelease(g_atr_handle);
   if(g_csv_handle != INVALID_HANDLE) FileClose(g_csv_handle);
  }

//+------------------------------------------------------------------+
//| Criterio propio de optimización.                                 |
//| Sharpe del tester, anulado si hubo muy pocos trades: evita que la |
//| optimización premie una curva construida sobre 3 operaciones.     |
//+------------------------------------------------------------------+
double OnTester()
  {
   double trades = TesterStatistics(STAT_TRADES);
   if(trades < InpMinTradesFit) return(0.0);
   return(TesterStatistics(STAT_SHARPE_RATIO));
  }

//+------------------------------------------------------------------+
//| Tick: sólo se decide en el cierre de cada barra.                 |
//+------------------------------------------------------------------+
void OnTick()
  {
   datetime barra = iTime(_Symbol, PERIOD_CURRENT, 0);
   if(barra == g_ultima_barra) return;
   g_ultima_barra = barra;

   ProcesarBarra();
  }

//+------------------------------------------------------------------+
//| Lógica principal, una vez por barra cerrada.                     |
//+------------------------------------------------------------------+
void ProcesarBarra()
  {
   //--- 1) Datos: cierres de las últimas InpVentana barras COMPLETAS.
   double closes[];
   ArraySetAsSeries(closes, false);
   int copiadas = CopyClose(_Symbol, PERIOD_CURRENT, 1, InpVentana, closes);
   if(copiadas < InpVentana) return;   // todavía no hay historial suficiente

   double x[];
   ArrayResize(x, copiadas);
   for(int i = 0; i < copiadas; i++)
     {
      if(closes[i] <= 0.0) return;     // sin log-precio definido
      x[i] = MathLog(closes[i]);
     }

   //--- 2) Calibración del OU sobre la ventana (sólo datos pasados).
   OUParams p = OUCalibrate(x, copiadas, InpMinPuntos);

   //--- 3) Régimen de Markov sobre los retornos de la misma ventana.
   RegimeInfo reg;
   reg.ok = false;
   if(InpUsarRegimen)
     {
      double rets[];
      ArrayResize(rets, copiadas - 1);
      for(int i = 1; i < copiadas; i++) rets[i - 1] = x[i] - x[i - 1];
      reg = MarkovRegime(rets, copiadas - 1, InpRegimenK);
     }

   //--- 4) Estado actual de la posición.
   int    pos_actual = PosicionActual();
   double z = 0.0;
   string motivo = "";
   int    objetivo = 0;

   bool operable = ModeloOperable(p, motivo);

   if(operable)
     {
      z = p.z;
      objetivo = OUTargetPosition(z, pos_actual, g_bars_held, p.half_life,
                                  InpEntradaZ, InpSalidaZ, InpStopZ, InpMaxHoldHL, motivo);

      //--- Filtro de régimen: sólo bloquea aperturas, nunca cierres.
      if(objetivo != pos_actual && objetivo != 0 && InpUsarRegimen)
        {
         if(!RegimeAllows(objetivo, reg, InpPersistMin))
           {
            objetivo = pos_actual;
            motivo   = "bloqueado por régimen persistente";
           }
        }

      //--- Filtro de dirección.
      if(objetivo == 1  && InpDireccion == DIR_CORTO) { objetivo = pos_actual; motivo = "sólo cortos habilitados"; }
      if(objetivo == -1 && InpDireccion == DIR_LARGO) { objetivo = pos_actual; motivo = "sólo largos habilitados"; }
     }
   else
     {
      //--- Sin reversión estadísticamente sostenible no se abre nada, y lo
      //    que esté abierto se cierra: el modelo que justificaba la posición
      //    dejó de valer.
      objetivo = 0;
      if(!g_aviso_sin_reversion)
        {
         Print("Sin reversión operable: ", motivo,
               ". El EA se queda afuera hasta que el test vuelva a rechazar la raíz unitaria.");
         g_aviso_sin_reversion = true;
        }
     }
   if(operable) g_aviso_sin_reversion = false;

   //--- 5) Diagnóstico.
   if(g_csv_handle != INVALID_HANDLE)
      FileWrite(g_csv_handle,
                TimeToString(iTime(_Symbol, PERIOD_CURRENT, 1), TIME_DATE | TIME_MINUTES),
                DoubleToString(closes[copiadas - 1], g_digitos),
                p.ok ? "1" : "0",
                DoubleToString(p.theta, 8), DoubleToString(p.mu, 8),
                DoubleToString(p.sigma_eq, 8), DoubleToString(p.half_life, 8),
                DoubleToString(p.z, 8), DoubleToString(p.df_stat, 8),
                p.estacionaria ? "1" : "0",
                reg.ok ? IntegerToString(reg.estado) : "-1",
                reg.ok ? DoubleToString(reg.persistencia, 8) : "",
                reg.ok ? (reg.hay_memoria ? "1" : "0") : "",
                IntegerToString(pos_actual), IntegerToString(objetivo), motivo);

   if(InpLogVerboso && operable)
      PrintFormat("z=%.3f half-life=%.1f df=%.2f pos=%d -> %d (%s)",
                  z, p.half_life, p.df_stat, pos_actual, objetivo, motivo);

   //--- 6) Ejecución.
   if(objetivo != pos_actual) AjustarPosicion(pos_actual, objetivo, p, motivo);

   //--- 7) Contador de permanencia, sobre la posición REAL resultante (una orden
   //    puede haber sido rechazada). Misma regla que quant/backtest.py: al abrir
   //    vale 1, mientras se mantiene suma 1, y fuera del mercado vuelve a 0.
   int pos_final = PosicionActual();
   if(pos_final == 0)                 g_bars_held = 0;
   else if(pos_final == pos_actual)   g_bars_held++;
   else                               g_bars_held = 1;
  }

//+------------------------------------------------------------------+
//| ¿El modelo habilita a operar? Acá vive la honestidad estadística. |
//+------------------------------------------------------------------+
bool ModeloOperable(const OUParams &p, string &motivo)
  {
   if(!p.ok)
     {
      motivo = p.motivo;
      return(false);
     }
   if(InpExigirDF && !p.estacionaria)
     {
      motivo = StringFormat("Dickey-Fuller %.2f no rechaza la raíz unitaria al 5%% (crítico %.2f): "
                            "el half-life de %.1f barras es un artefacto de la muestra",
                            p.df_stat, OU_DF_CRIT_5, p.half_life);
      return(false);
     }
   if(InpMaxHalfLife > 0.0 && p.half_life > InpMaxHalfLife)
     {
      motivo = StringFormat("half-life de %.1f barras supera el máximo aceptado (%.1f)",
                            p.half_life, InpMaxHalfLife);
      return(false);
     }
   if(p.sigma_eq <= 0.0)
     {
      motivo = "sigma_eq no positivo";
      return(false);
     }
   return(true);
  }

//+------------------------------------------------------------------+
//| Posición actual del EA: +1 largo, -1 corto, 0 fuera.             |
//+------------------------------------------------------------------+
int PosicionActual()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      return(PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY ? 1 : -1);
     }
   return(0);
  }

//+------------------------------------------------------------------+
//| Ticket de la posición del EA (0 si no hay).                      |
//+------------------------------------------------------------------+
ulong TicketActual()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      return(ticket);
     }
   return(0);
  }

//+------------------------------------------------------------------+
//| Barras que lleva abierta la posición (para el corte por tiempo    |
//| tras un reinicio del EA con posición viva).                       |
//+------------------------------------------------------------------+
int BarrasDesdeApertura()
  {
   ulong ticket = TicketActual();
   if(ticket == 0) return(0);
   if(!PositionSelectByTicket(ticket)) return(0);
   datetime apertura = (datetime)PositionGetInteger(POSITION_TIME);
   int shift = iBarShift(_Symbol, PERIOD_CURRENT, apertura, false);
   return(shift > 0 ? shift : 1);
  }

//+------------------------------------------------------------------+
//| Lleva la posición al objetivo (-1 / 0 / +1).                     |
//+------------------------------------------------------------------+
void AjustarPosicion(const int actual, const int objetivo, const OUParams &p, const string motivo)
  {
   //--- Cerrar lo que haya si el objetivo cambió.
   if(actual != 0)
     {
      ulong ticket = TicketActual();
      if(ticket != 0 && !g_trade.PositionClose(ticket))
        {
         PrintFormat("No se pudo cerrar el ticket %I64u: %d (%s)",
                     ticket, g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
         return;
        }
      if(InpLogVerboso) Print("Cerrada por: ", motivo);
     }

   if(objetivo == 0) return;

   //--- Spread: en reversión a la media el spread se come el edge.
   if(InpMaxSpreadPts > 0)
     {
      long spread = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
      if(spread > InpMaxSpreadPts)
        {
         PrintFormat("Entrada omitida: spread %d > máximo %d puntos.", (int)spread, InpMaxSpreadPts);
         return;
        }
     }

   double sl    = 0.0;
   double dist  = DistanciaStop();
   double lotes = CalcularLotes(dist);
   if(lotes <= 0.0)
     {
      Print("Entrada omitida: volumen calculado no válido.");
      return;
     }

   double precio = (objetivo == 1) ? SymbolInfoDouble(_Symbol, SYMBOL_ASK)
                                   : SymbolInfoDouble(_Symbol, SYMBOL_BID);
   if(dist > 0.0)
      sl = NormalizarStop(objetivo, precio, dist);

   string comentario = StringFormat("OU z=%.2f hl=%.0f", p.z, p.half_life);
   bool ok = (objetivo == 1) ? g_trade.Buy(lotes, _Symbol, 0.0, sl, 0.0, comentario)
                             : g_trade.Sell(lotes, _Symbol, 0.0, sl, 0.0, comentario);
   if(!ok)
     {
      PrintFormat("Orden rechazada: %d (%s)", g_trade.ResultRetcode(),
                  g_trade.ResultRetcodeDescription());
      return;
     }
   if(InpLogVerboso)
      PrintFormat("Abierta %s %.2f lotes · %s", objetivo == 1 ? "LARGA" : "CORTA", lotes, motivo);
  }

//+------------------------------------------------------------------+
//| Distancia del stop duro en precio (0 si está desactivado).       |
//+------------------------------------------------------------------+
double DistanciaStop()
  {
   if(InpStopDuroATR <= 0.0 || g_atr_handle == INVALID_HANDLE) return(0.0);
   double atr[];
   ArraySetAsSeries(atr, true);
   if(CopyBuffer(g_atr_handle, 0, 1, 1, atr) < 1) return(0.0);
   if(atr[0] <= 0.0) return(0.0);
   return(atr[0] * InpStopDuroATR);
  }

//+------------------------------------------------------------------+
//| Normaliza el stop respetando la distancia mínima del bróker.     |
//+------------------------------------------------------------------+
double NormalizarStop(const int direccion, const double precio, const double distancia)
  {
   long   nivel_min = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   double min_dist  = nivel_min * g_punto;
   double d = MathMax(distancia, min_dist + g_punto);
   double sl = (direccion == 1) ? precio - d : precio + d;
   return(NormalizeDouble(sl, g_digitos));
  }

//+------------------------------------------------------------------+
//| Volumen: lote fijo o riesgo % sobre la distancia del stop duro.  |
//+------------------------------------------------------------------+
double CalcularLotes(const double distancia_stop)
  {
   double lotes = InpLotes;

   if(InpModoLote == SIZE_RIESGO && distancia_stop > 0.0)
     {
      double tick_value = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
      double tick_size  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
      if(tick_value > 0.0 && tick_size > 0.0)
        {
         double perdida_por_lote = (distancia_stop / tick_size) * tick_value;
         if(perdida_por_lote > 0.0)
           {
            double riesgo = AccountInfoDouble(ACCOUNT_BALANCE) * InpRiesgoPct / 100.0;
            lotes = riesgo / perdida_por_lote;
           }
        }
     }
   return(NormalizarVolumen(lotes));
  }

//+------------------------------------------------------------------+
//| Ajusta el volumen al paso, mínimo y máximo del símbolo.          |
//+------------------------------------------------------------------+
double NormalizarVolumen(const double volumen)
  {
   double vmin  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vmax  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double paso  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(paso <= 0.0) paso = 0.01;

   double v = MathFloor(volumen / paso) * paso;
   v = MathMax(v, vmin);
   v = MathMin(v, vmax);
   //--- Redondeo al número de decimales del paso, para que el bróker no lo rechace.
   int dec = (int)MathMax(0.0, MathCeil(-MathLog10(paso)));
   return(NormalizeDouble(v, dec));
  }
//+------------------------------------------------------------------+
