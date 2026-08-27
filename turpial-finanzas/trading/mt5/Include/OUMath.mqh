//+------------------------------------------------------------------+
//| OUMath.mqh — Ornstein-Uhlenbeck y cadenas de Markov para MQL5.    |
//|                                                                  |
//| Port directo del motor validado en Python (turpial-finanzas/     |
//| quant/): mismas fórmulas, mismos umbrales, mismos criterios de    |
//| rechazo. Si cambiás algo acá, cambialo también allá y volvé a     |
//| correr tests/test_quant.py.                                       |
//|                                                                  |
//| Modelo:  dX = theta*(mu - X)*dt + sigma*dW                        |
//| Se calibra por la discretización EXACTA del OU, que es un AR(1):  |
//|   X[i+1] = a + b*X[i] + eps,  b = exp(-theta*dt)                  |
//|   theta = -ln(b)/dt   mu = a/(1-b)   sigma = s_eps*sqrt(2th/(1-b^2))|
//| Half-life = ln(2)/theta.                                          |
//+------------------------------------------------------------------+
#ifndef __OU_MATH_MQH__
#define __OU_MATH_MQH__

//--- Valores críticos de Dickey-Fuller (con constante, sin tendencia).
//    El t-stat de (b-1) NO sigue una t de Student bajo raíz unitaria:
//    por eso se compara contra esta tabla y no contra +-1.96.
#define OU_DF_CRIT_1  -3.43
#define OU_DF_CRIT_5  -2.86
#define OU_DF_CRIT_10 -2.57

//--- Engle-Granger (residuo de una cointegración de 2 series, beta estimado).
#define OU_EG_CRIT_1  -3.90
#define OU_EG_CRIT_5  -3.34
#define OU_EG_CRIT_10 -3.04

//--- Regímenes de la cadena de Markov.
#define REG_BAJISTA 0
#define REG_LATERAL 1
#define REG_ALCISTA 2

//+------------------------------------------------------------------+
//| Resultado de la calibración del OU.                              |
//+------------------------------------------------------------------+
struct OUParams
  {
   bool     ok;             // false => no hay reversión estimable
   double   theta;          // velocidad de reversión (1/barra)
   double   mu;             // nivel de equilibrio
   double   sigma;          // volatilidad instantánea
   double   sigma_eq;       // desvío de la distribución estacionaria
   double   half_life;      // ln(2)/theta, en barras
   double   ar1_a;
   double   ar1_b;
   double   r2;
   double   df_stat;        // estadístico de Dickey-Fuller
   bool     estacionaria;   // df_stat < OU_DF_CRIT_5
   double   z;              // z-score del último dato
   double   last;
   int      n;
   string   motivo;         // por qué falló, si ok==false
  };

//+------------------------------------------------------------------+
//| Resultado del análisis de régimen (cadena de Markov 3x3).        |
//+------------------------------------------------------------------+
struct RegimeInfo
  {
   bool     ok;
   int      estado;          // REG_BAJISTA / REG_LATERAL / REG_ALCISTA
   double   P[3][3];         // matriz de transición (con suavizado de Laplace)
   double   persistencia;    // P[estado][estado]
   double   duracion_media;  // 1/(1-P_ii)
   double   chi2;            // test de independencia
   int      df;
   bool     hay_memoria;     // chi2 supera el crítico al 5%
   string   motivo;
  };

//+------------------------------------------------------------------+
//| Media y desvío estándar muestral (ddof=1).                       |
//+------------------------------------------------------------------+
double OUMean(const double &v[],const int n)
  {
   if(n<=0) return(0.0);
   double s=0.0;
   for(int i=0;i<n;i++) s+=v[i];
   return(s/n);
  }

double OUStdev(const double &v[],const int n)
  {
   if(n<2) return(0.0);
   double m=OUMean(v,n), acc=0.0;
   for(int i=0;i<n;i++) acc+=(v[i]-m)*(v[i]-m);
   return(MathSqrt(acc/(n-1)));
  }

//+------------------------------------------------------------------+
//| Mínimos cuadrados de y = a + b*x.                                |
//| Devuelve false si el regresor es constante (pendiente indefinida).|
//+------------------------------------------------------------------+
bool OULinReg(const double &x[],const double &y[],const int n,
              double &a,double &b,double &se_b,double &resid_std,double &r2)
  {
   a=0.0; b=0.0; se_b=0.0; resid_std=0.0; r2=0.0;
   if(n<3) return(false);

   double mx=OUMean(x,n), my=OUMean(y,n);
   double sxx=0.0, sxy=0.0, sst=0.0;
   for(int i=0;i<n;i++)
     {
      double dx=x[i]-mx, dy=y[i]-my;
      sxx+=dx*dx; sxy+=dx*dy; sst+=dy*dy;
     }
   if(sxx<=0.0) return(false);

   b=sxy/sxx;
   a=my-b*mx;

   double sse=0.0;
   for(int i=0;i<n;i++)
     {
      double e=y[i]-(a+b*x[i]);
      sse+=e*e;
     }
   int dof=n-2;
   double s2=sse/dof;
   se_b=MathSqrt(s2/sxx);
   resid_std=MathSqrt(s2);
   r2=(sst>0.0) ? 1.0-sse/sst : 0.0;
   return(true);
  }

//+------------------------------------------------------------------+
//| Calibra el OU sobre `series` (n puntos equiespaciados, dt=1 barra)|
//+------------------------------------------------------------------+
OUParams OUCalibrate(const double &series[],const int n,const int min_puntos=30)
  {
   OUParams p;
   p.ok=false; p.theta=0; p.mu=0; p.sigma=0; p.sigma_eq=0; p.half_life=0;
   p.ar1_a=0; p.ar1_b=0; p.r2=0; p.df_stat=0; p.estacionaria=false;
   p.z=0; p.last=(n>0?series[n-1]:0.0); p.n=n; p.motivo="";

   if(n<min_puntos)
     {
      p.motivo="Serie demasiado corta para calibrar";
      return(p);
     }

   int m=n-1;
   double x[];
   double y[];
   ArrayResize(x,m);
   ArrayResize(y,m);
   for(int i=0;i<m;i++) { x[i]=series[i]; y[i]=series[i+1]; }

   double a,b,se_b,s_eps,r2;
   if(!OULinReg(x,y,m,a,b,se_b,s_eps,r2))
     {
      p.motivo="Regresor constante: pendiente indefinida";
      return(p);
     }

   p.ar1_a=a; p.ar1_b=b; p.r2=r2;
   p.df_stat=(se_b>0.0) ? (b-1.0)/se_b : -DBL_MAX;
   p.estacionaria=(p.df_stat<OU_DF_CRIT_5);

   if(b<=0.0) { p.motivo="Pendiente AR(1) <= 0: oscilación, no reversión"; return(p); }
   if(b>=1.0) { p.motivo="Pendiente AR(1) >= 1: random walk o explosiva";  return(p); }

   p.theta     = -MathLog(b);
   p.mu        = a/(1.0-b);
   p.sigma     = s_eps*MathSqrt(2.0*p.theta/(1.0-b*b));
   p.sigma_eq  = s_eps/MathSqrt(1.0-b*b);
   p.half_life = MathLog(2.0)/p.theta;
   p.z         = (p.sigma_eq>0.0) ? (p.last-p.mu)/p.sigma_eq : 0.0;
   p.ok        = true;
   return(p);
  }

//+------------------------------------------------------------------+
//| Trayectoria esperada: E[X_t|X_0] = mu + (X_0-mu)*exp(-theta*t).  |
//| `t` en barras. Es la curva de decaimiento del half-life.          |
//+------------------------------------------------------------------+
double OUExpectedAt(const OUParams &p,const double x0,const double t)
  {
   if(!p.ok) return(x0);
   return(p.mu+(x0-p.mu)*MathExp(-p.theta*t));
  }

//+------------------------------------------------------------------+
//| Valores críticos de chi-cuadrado al 5% por grados de libertad.   |
//| Se compara el estadístico contra la tabla en vez de calcular el   |
//| p-valor: para la decisión binaria al 5% es exactamente lo mismo   |
//| y evita portar la función gamma incompleta.                       |
//+------------------------------------------------------------------+
double Chi2Crit5(const int df)
  {
   switch(df)
     {
      case 1: return(3.841);
      case 2: return(5.991);
      case 3: return(7.815);
      case 4: return(9.488);
      case 5: return(11.070);
      case 6: return(12.592);
      default: break;
     }
   // Aproximación de Wilson-Hilferty para df grandes (no se usa con 3 estados).
   double h=2.0/(9.0*df);
   double q=1.0-h+1.6449*MathSqrt(h);
   return(df*q*q*q);
  }

//+------------------------------------------------------------------+
//| Régimen de mercado por cadena de Markov de 3 estados.            |
//| `rets` son retornos (log) de la ventana; los umbrales son +-k*sd. |
//| alpha = suavizado de Laplace.                                     |
//+------------------------------------------------------------------+
RegimeInfo MarkovRegime(const double &rets[],const int n,
                        const double k=0.5,const double alpha=1.0)
  {
   RegimeInfo r;
   r.ok=false; r.estado=REG_LATERAL; r.persistencia=0.0; r.duracion_media=0.0;
   r.chi2=0.0; r.df=4; r.hay_memoria=false; r.motivo="";
   for(int i=0;i<3;i++) for(int j=0;j<3;j++) r.P[i][j]=0.0;

   if(n<10) { r.motivo="Muy pocos retornos para etiquetar regímenes"; return(r); }

   double sd=OUStdev(rets,n);
   if(sd<=0.0) { r.motivo="Retornos sin dispersión"; return(r); }

   double lo=-k*sd, hi=k*sd;
   int estados[];
   ArrayResize(estados,n);
   for(int i=0;i<n;i++)
      estados[i]=(rets[i]<lo) ? REG_BAJISTA : ((rets[i]>hi) ? REG_ALCISTA : REG_LATERAL);

   int counts[3][3];
   for(int i=0;i<3;i++) for(int j=0;j<3;j++) counts[i][j]=0;
   for(int i=0;i<n-1;i++) counts[estados[i]][estados[i+1]]++;

   for(int i=0;i<3;i++)
     {
      double fila=0.0;
      for(int j=0;j<3;j++) fila+=counts[i][j];
      double den=fila+alpha*3.0;
      for(int j=0;j<3;j++) r.P[i][j]=(counts[i][j]+alpha)/den;
     }

   // chi-cuadrado de independencia sobre la tabla de contingencia cruda.
   double total=0.0;
   double filas[3];
   double cols[3];
   for(int i=0;i<3;i++) { filas[i]=0.0; cols[i]=0.0; }
   for(int i=0;i<3;i++)
      for(int j=0;j<3;j++)
        { filas[i]+=counts[i][j]; cols[j]+=counts[i][j]; total+=counts[i][j]; }

   if(total<=0.0) { r.motivo="Sin transiciones observadas"; return(r); }

   double stat=0.0; int penal=0;
   for(int i=0;i<3;i++)
      for(int j=0;j<3;j++)
        {
         double e=filas[i]*cols[j]/total;
         if(e<=0.0) { penal++; continue; }
         double d=counts[i][j]-e;
         stat+=d*d/e;
        }
   r.chi2=stat;
   r.df=MathMax(4-penal,1);
   r.hay_memoria=(stat>Chi2Crit5(r.df));

   r.estado=estados[n-1];
   r.persistencia=r.P[r.estado][r.estado];
   double pp=MathMin(r.persistencia,1.0-1e-12);
   r.duracion_media=1.0/(1.0-pp);
   r.ok=true;
   return(r);
  }

//+------------------------------------------------------------------+
//| Posición objetivo dado el z-score. Espejo de quant/strategies.py. |
//|  prev: -1 corto, 0 fuera, +1 largo                                |
//|  bars_held: barras que lleva abierta la posición actual           |
//| Devuelve -1/0/+1 y escribe el motivo en `motivo`.                 |
//+------------------------------------------------------------------+
int OUTargetPosition(const double z,const int prev,const int bars_held,
                     const double half_life,const double entry,const double exit_,
                     const double stop,const double max_hold_hl,string &motivo)
  {
   double max_bars=MathMax(1.0,max_hold_hl*half_life);

   if(prev==0)
     {
      if(z<=-entry) { motivo="entrada larga: z bajo el umbral";  return(1); }
      if(z>= entry) { motivo="entrada corta: z sobre el umbral"; return(-1); }
      motivo="sin señal";
      return(0);
     }

   if(bars_held>=max_bars)
     {
      motivo=StringFormat("tiempo agotado: %.1fx half-life sin reversión",max_hold_hl);
      return(0);
     }

   if(prev==1)
     {
      if(z<=-stop)  { motivo="stop: la desviación siguió creciendo"; return(0); }
      if(z>=-exit_) { motivo="objetivo: volvió al equilibrio";       return(0); }
      motivo="mantener larga";
      return(1);
     }

   if(z>= stop) { motivo="stop: la desviación siguió creciendo"; return(0); }
   if(z<= exit_){ motivo="objetivo: volvió al equilibrio";       return(0); }
   motivo="mantener corta";
   return(-1);
  }

//+------------------------------------------------------------------+
//| Filtro de régimen: no operar contra una tendencia persistente.   |
//| Si el chi2 no encontró memoria, no filtra nada (sin evidencia,    |
//| no inventamos un filtro).                                         |
//+------------------------------------------------------------------+
bool RegimeAllows(const int target,const RegimeInfo &reg,const double persist_min)
  {
   if(target==0)        return(true);
   if(!reg.ok)          return(true);
   if(!reg.hay_memoria) return(true);
   if(reg.persistencia<persist_min) return(true);
   if(target==1  && reg.estado==REG_BAJISTA) return(false);
   if(target==-1 && reg.estado==REG_ALCISTA) return(false);
   return(true);
  }

#endif // __OU_MATH_MQH__
