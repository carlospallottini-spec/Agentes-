//+------------------------------------------------------------------+
//| SessionMarkov_EA.mq5   v1.10                                     |
//|------------------------------------------------------------------|
//| Motor S del EA DualNasdaq, aislado y con los parámetros que       |
//| sobrevivieron una optimización walk-forward.                      |
//|                                                                   |
//| QUÉ HACE                                                          |
//|   Mira la sesión RTH de AYER (9:30-16:00 ET):                     |
//|     A) movimiento = (cierre-apertura)/ATR(14) de sesión           |
//|     B) posición de cierre = (cierre-mínimo)/(máximo-mínimo)       |
//|   Compra en la apertura de hoy si se cumplen AMBAS. Stop en       |
//|   múltiplos de ATR. Sale al cierre de la sesión.                  |
//|                                                                   |
//| QUÉ CAMBIÓ RESPECTO DEL ORIGINAL, Y POR QUÉ                       |
//|   1. InpS_RequireBoth = true (antes false).                        |
//|      Una optimización walk-forward sobre 20 años de Nasdaq 100    |
//|      (750 combinaciones, 6 ventanas de entrenamiento) eligió       |
//|      "ambas condiciones" en las 6 ventanas, sin excepción.         |
//|      Fuera de muestra: Sharpe 0.65 -> 0.73 y, sobre todo,          |
//|      drawdown máximo 7.2% -> 3.4%. Opera 4 veces menos.            |
//|   2. InpS_StopATR = 3.0 (antes 2.0).                               |
//|      El backtest prefiere no tener stop, pero con 3 ATR el         |
//|      resultado es IDÉNTICO al de no tenerlo (mismo Sharpe, mismos  |
//|      trades, mismo peor día) porque a esa distancia casi nunca     |
//|      salta. O sea: se conserva el seguro contra una caída          |
//|      violenta sin pagar nada en el backtest. Quitarlo del todo     |
//|      sería regalar la cola por +0.00 de rendimiento.               |
//|   3. InpS_RiskPct = 0.75 (antes 1.5).                              |
//|      OJO: el stop está a 3 ATR, así que el riesgo por operación    |
//|      es ~2.25% del capital, no 0.75%. Este parámetro es            |
//|      EXPOSICIÓN por ATR, no riesgo por trade.                      |
//|      Bajar el riesgo NO mejora el Sharpe -- es invariante de       |
//|      escala. Divide a la mitad el retorno y el drawdown.           |
//|   4. Sin Sleep() en OnTick y más margen de historial M5.           |
//|                                                                   |
//| LO QUE LA OPTIMIZACIÓN **NO** ENCONTRÓ                             |
//|   Barrer las 750 combinaciones no le ganó a los parámetros por     |
//|   defecto fuera de muestra: +0.000 de Sharpe. Tampoco le ganó a    |
//|   elegir una combinación al azar (p empírico 0.32). Por eso        |
//|   ATRDrop y ClosePos quedan en sus valores originales: no hay      |
//|   evidencia para tocarlos.                                         |
//|                                                                   |
//| MEDIDO (índice Nasdaq 100, 2006-2026, 1 bp de costo, riesgo 0.75%) |
//|   Fuera de muestra (12 años): Sharpe 0.78 · maxDD 3.4% · PF 1.97   |
//|   Serie completa (20 años):   Sharpe 0.87 · CAGR 1.75% · 257 ops   |
//|   Peor día: -1.73% del capital                                     |
//|                                                                   |
//| DÓNDE SE ROMPE                                                     |
//|   En los costos. La ganancia media por operación es de pocos       |
//|   puntos básicos: a 5 bps de ida y vuelta el edge desaparece.      |
//|   Medí el spread real de tu símbolo entre 9:30 y 9:50 ET antes de  |
//|   poner un peso.                                                   |
//|                                                                   |
//| Investigación educativa - no es asesoría financiera.               |
//+------------------------------------------------------------------+
#property copyright "Investigacion educativa"
#property version   "1.10"
#property description "SessionMarkov: compra la debilidad de la sesión previa en el Nasdaq"
#include <Trade/Trade.mqh>

input group "== Señal =="
input double InpS_RiskPct     = 0.75;  // Exposición %: 1 ATR de sesión = X% del capital
input double InpS_ATRDrop     = 1.00;  // Caída mínima de la sesión previa, en ATR
input double InpS_ClosePos    = 0.20;  // Cierre en el X inferior del rango
input int    InpS_ATRPeriod   = 14;    // Sesiones para el ATR
input double InpS_StopATR     = 3.00;  // Stop en múltiplos de ATR (0 = sin stop)
input bool   InpS_RequireBoth = true;  // true = exigir AMBAS condiciones

input group "== General =="
input long   InpMagic         = 330001;
input double InpMaxSpreadPts  = 50;
input int    InpEntryWindow   = 20;    // Minutos tras la apertura para entrar
input double InpMaxLeverage   = 3.0;   // Tope de apalancamiento nocional
input bool   InpAutoSession   = true;
input int    InpManOpenHour   = 15;
input int    InpManOpenMin    = 30;
input int    InpManCloseHour  = 22;
input bool   InpLogVerboso    = true;

CTrade   tr;
int      g_openMin = 0, g_closeMin = 0, g_lastDayChk = -1;
datetime g_lastDay = 0;
double   g_pendienteStop = 0;   // distancia del stop que quedó sin aplicar, si falló

//--- Declaraciones adelantadas: OnTick las usa antes de que aparezcan en el archivo.
void ApplyStop(double slDist);
bool PosicionYaTieneStop();

//====================== HORARIO AUTOMÁTICO ==========================
int NthSundayOfMonth(int year, int mon, int n)
{
   MqlDateTime d; ZeroMemory(d); d.year = year; d.mon = mon; d.day = 1;
   MqlDateTime f; TimeToStruct(StructToTime(d), f);
   return 1 + ((7 - f.day_of_week) % 7) + 7 * (n - 1);
}
bool IsUSDaylightTime(datetime gmt)
{
   MqlDateTime t; TimeToStruct(gmt, t);
   if(t.mon < 3 || t.mon > 11) return false;
   if(t.mon > 3 && t.mon < 11) return true;
   if(t.mon == 3) { int sm = NthSundayOfMonth(t.year, 3, 2);
                    return (t.day > sm) || (t.day == sm && t.hour >= 7); }
   int sn = NthSundayOfMonth(t.year, 11, 1);
   return (t.day < sn) || (t.day == sn && t.hour < 6);
}
void ComputeSessionTimes(bool verbose)
{
   if(!InpAutoSession)
   {
      g_openMin  = InpManOpenHour * 60 + InpManOpenMin;
      g_closeMin = InpManCloseHour * 60;
      if(verbose) PrintFormat("SessionMarkov %s: horario MANUAL -> apertura %02d:%02d",
                              _Symbol, g_openMin / 60, g_openMin % 60);
      return;
   }
   datetime gmt = TimeGMT();
   int srv = (int)MathRound((double)(TimeCurrent() - gmt) / 3600.0);
   int ny  = IsUSDaylightTime(gmt) ? -4 : -5;
   int sh  = (srv - ny) * 60;
   g_openMin  = ((9 * 60 + 30) + sh) % 1440; if(g_openMin  < 0) g_openMin  += 1440;
   g_closeMin = ((16 * 60) + sh) % 1440;     if(g_closeMin < 0) g_closeMin += 1440;
   if(verbose)
      PrintFormat("SessionMarkov %s: AUTO -> servidor GMT%+d, NY GMT%+d | sesión %02d:%02d-%02d:%02d",
                  _Symbol, srv, ny, g_openMin / 60, g_openMin % 60,
                  g_closeMin / 60, g_closeMin % 60);
}

//========================== UTILIDADES ==============================
bool SpreadOK() { return SymbolInfoInteger(_Symbol, SYMBOL_SPREAD) <= (long)InpMaxSpreadPts; }

double MinStopDist()
{
   double pt = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   int a = (int)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   int b = (int)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_FREEZE_LEVEL);
   double sp = SymbolInfoDouble(_Symbol, SYMBOL_ASK) - SymbolInfoDouble(_Symbol, SYMBOL_BID);
   return MathMax(a, b) * pt + sp;
}
double NormalizeLots(double lots)
{
   double mn = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double mx = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double st = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(st <= 0) return 0;
   lots = MathFloor(lots / st) * st;
   return lots < mn ? 0 : MathMin(lots, mx);
}
//--- 1 ATR de movimiento = InpS_RiskPct % del capital, con tope de apalancamiento
double LotsForVolTarget(double atrVal)
{
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   double px = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double tv = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double ts = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(atrVal <= 0 || px <= 0 || tv <= 0 || ts <= 0) return 0;
   double vpp  = tv / ts;
   double lots = (eq * InpS_RiskPct / 100.0) / (atrVal * vpp);
   double maxLots = (px * vpp > 0) ? eq * InpMaxLeverage / (px * vpp) : 0;
   if(maxLots > 0 && lots > maxLots) lots = maxLots;
   return NormalizeLots(lots);
}
double PosByMagic()
{
   double net = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(!PositionSelectByTicket(tk)) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      double v = PositionGetDouble(POSITION_VOLUME);
      net += (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? v : -v;
   }
   return net;
}
//--- varias pasadas: los índices se corren al cerrar posiciones
void CloseAll()
{
   for(int pass = 0; pass < 5; pass++)
   {
      bool any = false;
      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         ulong tk = PositionGetTicket(i);
         if(!PositionSelectByTicket(tk)) continue;
         if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
         if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
         tr.PositionClose(tk); any = true;
      }
      if(!any) return;
   }
   PrintFormat("SessionMarkov %s: ATENCIÓN, quedan posiciones sin cerrar", _Symbol);
}
bool MarginOK(double vol)
{
   double need = 0;
   if(!OrderCalcMargin(ORDER_TYPE_BUY, _Symbol, vol,
                       SymbolInfoDouble(_Symbol, SYMBOL_ASK), need)) return false;
   return need < AccountInfoDouble(ACCOUNT_MARGIN_FREE) * 0.8;
}

//--- reconstruye las sesiones RTH pasadas desde barras M5
int BuildSessions(int wanted, double &so[], double &sh[], double &sl[], double &sc[])
{
   ArrayResize(so, wanted); ArrayResize(sh, wanted);
   ArrayResize(sl, wanted); ArrayResize(sc, wanted);
   MqlRates r[]; ArraySetAsSeries(r, false);
   // Margen amplio: con (wanted+3)*288 el motor se quedaba sin sesiones en cuanto el
   // bróker tenía huecos de historial M5, y dejaba de operar en silencio.
   int need = (wanted + 10) * 288 * 2; if(need > 400000) need = 400000;
   int n = CopyRates(_Symbol, PERIOD_M5, 0, need, r);
   if(n < 100) return 0;
   MqlDateTime now; TimeToStruct(TimeCurrent(), now);
   MqlDateTime z; ZeroMemory(z); z.year = now.year; z.mon = now.mon; z.day = now.day;
   datetime todayStart = StructToTime(z);
   int found = 0, i = n - 1;
   while(i >= 0 && found < wanted)
   {
      MqlDateTime b; TimeToStruct(r[i].time, b);
      int m = b.hour * 60 + b.min;
      if(!((m >= g_openMin && m < g_closeMin) && r[i].time < todayStart)) { i--; continue; }
      MqlDateTime ref; TimeToStruct(r[i].time, ref);
      double hi = r[i].high, lo = r[i].low, cl = r[i].close, op = r[i].open;
      int j = i;
      while(j >= 0)
      {
         MqlDateTime bb; TimeToStruct(r[j].time, bb);
         if(bb.year != ref.year || bb.mon != ref.mon || bb.day != ref.day) break;
         int mm = bb.hour * 60 + bb.min;
         if(mm < g_openMin || mm >= g_closeMin) break;
         if(r[j].high > hi) hi = r[j].high;
         if(r[j].low  < lo) lo = r[j].low;
         op = r[j].open; j--;
      }
      so[found] = op; sh[found] = hi; sl[found] = lo; sc[found] = cl; found++;
      i = j;
   }
   return found;
}

//============================ INIT ==================================
int OnInit()
{
   if(InpS_ATRPeriod < 2) { Print("SessionMarkov: ATRPeriod inválido"); return INIT_PARAMETERS_INCORRECT; }
   if(InpS_ClosePos <= 0.0 || InpS_ClosePos >= 1.0)
     { Print("SessionMarkov: ClosePos debe estar entre 0 y 1"); return INIT_PARAMETERS_INCORRECT; }

   tr.SetExpertMagicNumber(InpMagic);
   tr.SetTypeFillingBySymbol(_Symbol);
   tr.LogLevel(InpLogVerboso ? LOG_LEVEL_ALL : LOG_LEVEL_ERRORS);
   ComputeSessionTimes(true);
   PrintFormat("SessionMarkov v1.10 en %s | %.2f%%/ATR · stop %.1f ATR · %s condiciones",
               _Symbol, InpS_RiskPct, InpS_StopATR,
               InpS_RequireBoth ? "AMBAS" : "cualquiera de las dos");
   if(!InpS_RequireBoth)
      Print("SessionMarkov: AVISO — con una sola condición se opera 4 veces más y el "
            "drawdown medido se duplica (7.2% contra 3.4%).");
   return INIT_SUCCEEDED;
}
void OnDeinit(const int reason) {}

//============================ TICK ==================================
void OnTick()
{
   MqlDateTime t; TimeToStruct(TimeCurrent(), t);
   if(t.day != g_lastDayChk) { g_lastDayChk = t.day; ComputeSessionTimes(false); }
   MqlDateTime z; ZeroMemory(z); z.year = t.year; z.mon = t.mon; z.day = t.day;
   datetime today = StructToTime(z);
   int nowMin = t.hour * 60 + t.min;

   //---- cierre de sesión: la estrategia no deja posición de un día para otro ----
   if(nowMin >= g_closeMin)
   {
      if(PosByMagic() != 0) CloseAll();
      g_pendienteStop = 0;
      return;
   }

   //---- red de seguridad: si el stop no entró al abrir, reintentarlo ----
   if(InpS_StopATR > 0 && g_pendienteStop > 0 && PosByMagic() != 0)
   {
      ApplyStop(g_pendienteStop);
      if(PosicionYaTieneStop()) g_pendienteStop = 0;
   }

   if(!(nowMin >= g_openMin && nowMin < g_openMin + InpEntryWindow)) return;
   if(today == g_lastDay || PosByMagic() != 0) return;
   if(!SpreadOK())
   {
      static datetime aviso = 0;
      if(TimeCurrent() - aviso > 60)
        { PrintFormat("SessionMarkov %s: spread %d alto, reintentando en la ventana...",
                      _Symbol, (int)SymbolInfoInteger(_Symbol, SYMBOL_SPREAD));
          aviso = TimeCurrent(); }
      return;
   }

   double so[], sh[], sl[], sc[];
   int got = BuildSessions(InpS_ATRPeriod + 3, so, sh, sl, sc);
   if(got < InpS_ATRPeriod + 2)
   {
      static datetime aviso2 = 0;
      if(TimeCurrent() - aviso2 > 600)
        { PrintFormat("SessionMarkov %s: sólo %d sesiones reconstruidas, faltan %d. "
                      "Descargá más historial M5.", _Symbol, got, InpS_ATRPeriod + 2);
          aviso2 = TimeCurrent(); }
      return;
   }

   double sum = 0;
   for(int k = 0; k < InpS_ATRPeriod; k++)
   {
      double pc = sc[k + 1];
      sum += MathMax(sh[k] - sl[k], MathMax(MathAbs(sh[k] - pc), MathAbs(sl[k] - pc)));
   }
   double atrVal = sum / InpS_ATRPeriod;
   double rng = sh[0] - sl[0];
   if(atrVal <= 0 || rng <= 0) return;

   g_lastDay = today;   // un intento por día, haya señal o no

   double atrMove  = (sc[0] - so[0]) / atrVal;
   double closePos = (sc[0] - sl[0]) / rng;
   bool cA = (atrMove <= -InpS_ATRDrop);
   bool cB = (closePos <= InpS_ClosePos);
   bool sig = InpS_RequireBoth ? (cA && cB) : (cA || cB);

   PrintFormat("SessionMarkov %s [%02d:%02d]: ayer %.2f ATR (%s), cerró en %.0f%% (%s) "
               "| ATR=%.1f -> %s",
               _Symbol, t.hour, t.min, atrMove, cA ? "ok" : "no", closePos * 100,
               cB ? "ok" : "no", atrVal, sig ? "COMPRA" : "sin señal");
   if(!sig) return;

   double lots = LotsForVolTarget(atrVal);
   if(lots <= 0) { Print("SessionMarkov ", _Symbol, ": volumen calculado = 0"); return; }
   if(!MarginOK(lots))
     { PrintFormat("SessionMarkov %s: margen insuficiente para %.3f lotes", _Symbol, lots);
       return; }

   //--- se abre a mercado y el stop se aplica después: evita rechazos "Invalid stops"
   if(!tr.Buy(lots, _Symbol, 0.0, 0.0, 0.0, "SessMarkov"))
   {
      PrintFormat("SessionMarkov %s: apertura RECHAZADA %d (%s)",
                  _Symbol, tr.ResultRetcode(), tr.ResultRetcodeDescription());
      return;
   }
   if(InpS_StopATR > 0)
   {
      g_pendienteStop = InpS_StopATR * atrVal;
      ApplyStop(g_pendienteStop);
      if(PosicionYaTieneStop()) g_pendienteStop = 0;
   }
   PrintFormat("SessionMarkov %s: COMPRA %.3f lotes (stop a %.1f puntos)",
               _Symbol, lots, InpS_StopATR * atrVal);
}

//--- ¿La posición del EA ya tiene stop puesto?
bool PosicionYaTieneStop()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(!PositionSelectByTicket(tk)) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      return PositionGetDouble(POSITION_SL) != 0.0;
   }
   return true;   // sin posición, no hay nada pendiente
}

//--- Aplica el stop a la posición recién abierta. Sin Sleep(): en la apertura de NY
//--- bloquear el hilo hasta 2 segundos es caro, y el tick siguiente reintenta solo.
void ApplyStop(double slDist)
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong tk = PositionGetTicket(i);
      if(!PositionSelectByTicket(tk)) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      if(PositionGetDouble(POSITION_SL) != 0.0) return;      // ya tiene stop
      double entry = PositionGetDouble(POSITION_PRICE_OPEN);
      double minD  = MinStopDist();
      double d     = MathMax(slDist, minD + SymbolInfoDouble(_Symbol, SYMBOL_POINT));
      double sl    = NormalizeDouble(entry - d, (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS));
      if(!tr.PositionModify(tk, sl, 0.0))
         PrintFormat("SessionMarkov %s: no se pudo poner el stop (%d). Se reintenta al "
                     "próximo tick.", _Symbol, tr.ResultRetcode());
      return;
   }
}
//+------------------------------------------------------------------+
// EN EL TESTER:
//   US100 (o el índice Nasdaq de tu bróker), M5, "Cada tick basado en ticks reales",
//   spread real, comisión configurada. Período 2006-2026 si tenés historial.
//
// COMPARAR: con InpS_RequireBoth=false se reproduce el comportamiento original.
//   Esperado (índice, 1 bp): Sharpe 0.57 y maxDD 7.2% contra 0.87 y 3.4% con AMBAS.
//+------------------------------------------------------------------+
