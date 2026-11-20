#property strict
#property version "1.72"
#property description "HFM Cent XAUUSDc | Trend and range | fixed lot and shared broker SL"
#include <Trade/Trade.mqh>
#include "NewsWindows2026.mqh"
#include "SolGate.mqh"

const ulong Magic=317465172;
const double BaseLot=0.01, MaxLot=0.01, ExpectedContractSize=1.0;
const int MaxPositions=8;
const ulong DeviationPoints=30;
input double GridPriceDistance=4.00;
input double MaxSpreadPrice=0.70;
input double EstimatedRoundTripCostUSCPerLot=0.0;

CTrade trade;
string key;
double moneyScale=1.0; // USC inputs /100, then convert USD to account currency
int state=0; // 0 running, 1 closing basket profit
int count=0,side=-1;
double pnl=0,basketVolume=0,lastPrice=0,lastLot=0;
long lastMs=0;
datetime lastAttempt=0;
bool mixed=false;
enum INIT_STATUS { ENV_BLOCKED=-1, ENV_WAIT=0, ENV_READY=1 };
INIT_STATUS readiness=ENV_WAIT;
bool stateLoaded=false;
string readinessReason="Belum diperiksa",unitLabel="USC",entryBlock="";
double sharedSL=0,sharedTP=0;bool trendBasket=false,intradayBasket=false;
datetime oldestEntry=0, cachedSignal=0, lastDecision=0, pauseUntil=0;
int trend=0,signal=0;
double atr=0;bool spike=false;
ulong lastReadinessMs=0,lastCloseAttemptMs=0;
datetime lastSimCloseAttempt=0;

string LiveEntryConflict()
{
 if(MQLInfoInteger(MQL_TESTER)) return "";
 for(long chart=ChartFirst();chart>=0;chart=ChartNext(chart))
 {
  if(chart==ChartID() || ChartSymbol(chart)!=_Symbol) continue;
  string expert="";
  if(!ChartGetString(chart,CHART_EXPERT_NAME,expert))
   return StringFormat("Pemeriksaan EA chart %I64d belum tersedia; entry ditunda",chart);
  if(expert!="")
   return StringFormat("EA lain di simbol %s, chart %I64d: %s. Gunakan satu EA untuk akun/simbol ini",_Symbol,chart,expert);
 }
 return "";
}

bool EntryBlocked()
{
 string reason=LiveEntryConflict();
 if(reason!=entryBlock)
 {
  entryBlock=reason;
  Print("STATUS ENTRY: ",entryBlock=="" ? "Tidak ada konflik EA dalam terminal ini" : entryBlock);
 }
 return entryBlock!="";
}

void ShowStatus()
{
 if(MQLInfoInteger(MQL_TESTER) && !MQLInfoInteger(MQL_VISUAL_MODE))return;
 Comment("Kilas HFM Sol v1.72 | ",unitLabel," | ",readinessReason,
         "\nPosisi EA: ",count,"/",MaxPositions," | P/L: ",DoubleToString(pnl,2)," | TP harga: ",DoubleToString(sharedTP,_Digits),
         "\nBreakout H4: ",trend," | Sinyal: ",signal," | SL basket: ",DoubleToString(sharedSL,_Digits),
         "\nGPT-6.2 Sol: ",solStatus,"\nStatus: ",state==1?"Menutup basket":(TimeCurrent()<pauseUntil?"Jeda setelah SL":entryBlock));
}

bool InputsValid(string &reason)
{
 if(!MathIsValidNumber(GridPriceDistance)||GridPriceDistance<=0 ||
    !MathIsValidNumber(MaxSpreadPrice)||MaxSpreadPrice<=0 ||
    !MathIsValidNumber(EstimatedRoundTripCostUSCPerLot)||EstimatedRoundTripCostUSCPerLot<0)
 {reason="Grid/spread harus positif, dan biaya >=0";return false;}
 return true;
}

INIT_STATUS MissingData(bool tester,string detail,string &reason)
{
 reason=(tester ? "GAGAL TESTER: data belum tersedia; " : "WAIT: menunggu data/koneksi broker; ")+detail;
 return tester ? ENV_BLOCKED : ENV_WAIT;
}

INIT_STATUS CheckEnvironment(string &reason)
{
 bool tester=(bool)MQLInfoInteger(MQL_TESTER);
 string server=AccountInfoString(ACCOUNT_SERVER),currency=AccountInfoString(ACCOUNT_CURRENCY);
 long login=AccountInfoInteger(ACCOUNT_LOGIN);
 double contract=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_CONTRACT_SIZE);
 double minimum=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN),step=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
 double maximum=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX);
 string profitCurrency=SymbolInfoString(_Symbol,SYMBOL_CURRENCY_PROFIT);
 string marginCurrency=SymbolInfoString(_Symbol,SYMBOL_CURRENCY_MARGIN);
 bool custom=(bool)SymbolInfoInteger(_Symbol,SYMBOL_CUSTOM);
 string actual=StringFormat("aktual server='%s', currency='%s', symbol='%s', custom=%d, contract=%.8f, minLot=%.8f, lotStep=%.8f, maxLot=%.8f, profitCurrency='%s', marginCurrency='%s'",server,currency,_Symbol,(int)custom,contract,minimum,step,maximum,profitCurrency,marginCurrency);
 if(server!="" && StringFind(server,"HFMarkets")!=0)
 { reason="Server wajib diawali HFMarkets; "+actual; return ENV_BLOCKED; }
 if(currency!="" && currency!="USC" && !(tester && currency=="USD"))
 { reason="Akun live wajibUSC; USD hanya pengecualian tester terbatas; "+actual; return ENV_BLOCKED; }
 if(_Symbol!="XAUUSDc" && !(tester && (_Symbol=="XAUUSDc.USC_SIM" || _Symbol=="XAUUSDc.USC_TEST")))
 { reason="Simbol live wajib tepat XAUUSDc; simbol khusus hanya tester; "+actual; return ENV_BLOCKED; }
 if(server=="" || currency=="" || login<=0)
  return MissingData(tester,"identitas akun belum lengkap; "+actual,reason);
 bool usdScaled=tester && custom && currency=="USD" && _Symbol=="XAUUSDc.USC_SIM";
 bool uscDirect=tester && custom && currency=="USC" && _Symbol=="XAUUSDc.USC_TEST";
 bool nativeUSC=!custom && currency=="USC" && _Symbol=="XAUUSDc";
 bool usdPrecise=tester && !custom && currency=="USD" && _Symbol=="XAUUSDc";
 if(!usdScaled && !uscDirect && !nativeUSC && !usdPrecise)
 { reason="Kombinasi akun/simbol tidak diizinkan. Live: HFM/USC/XAUUSDc/native/contract1; tester custom wajib nama dan mata uang persis; "+actual; return ENV_BLOCKED; }
 if(AccountInfoInteger(ACCOUNT_MARGIN_MODE)!=ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
 { reason=StringFormat("Akun wajib hedging; aktual marginMode=%I64d; ",AccountInfoInteger(ACCOUNT_MARGIN_MODE))+actual; return ENV_BLOCKED; }
 double expected=(usdScaled || uscDirect) ? 100.0 : 1.0;
 if(!MathIsValidNumber(contract) || !MathIsValidNumber(minimum) || !MathIsValidNumber(step) || !MathIsValidNumber(maximum))
 { reason="Spesifikasi volume/contract bukan angka finite; "+actual; return ENV_BLOCKED; }
 if(contract>0 && MathAbs(contract-expected)>1e-8)
 { reason=StringFormat("Contract wajib%.2f untuk mode ini; ",expected)+actual; return ENV_BLOCKED; }
 if(contract<0 || minimum<0 || step<0 || maximum<0)
 { reason="Spesifikasi volume/contract negatif tidak valid; "+actual; return ENV_BLOCKED; }
 if(contract==0 || minimum==0 || step==0 || maximum==0)
  return MissingData(tester,"contract/minLot/lotStep/maxLot harus>0; "+actual,reason);
 if(usdScaled || uscDirect)
 {
  string expectedCurrency=uscDirect ? "USC" : "USD";
  if(profitCurrency=="" || marginCurrency=="")
   return MissingData(tester,"mata uang profit/margin simbol custom belum tersedia; "+actual,reason);
  if(profitCurrency!=expectedCurrency || marginCurrency!=expectedCurrency)
  { reason="Simbol custom wajib profitCurrency dan marginCurrency="+expectedCurrency+"; "+actual; return ENV_BLOCKED; }
 }
 if(minimum>maximum || MathAbs(Lot(BaseLot)-0.01)>1e-8)
 { reason="Broker tidak dapat menerima lot awal tepat0.01 dengan min/step/max tersebut; lot tidak dinaikkan otomatis; "+actual; return ENV_BLOCKED; }
 if(!SymbolIsSynchronized(_Symbol))
  return MissingData(tester,"SymbolIsSynchronized=false; "+actual,reason);
 moneyScale=usdPrecise ? 1.0 : 100.0;
 unitLabel=usdScaled ? "USC simulation units (tester USD contract100)" :
           (uscDirect ? "USC custom test (contract100)" : (usdPrecise ? "USD proxy (contract 1)" : "USC"));
 reason="READY: TP dan SL dari harga pasar; "+actual;
 return ENV_READY;
}

bool LoadOwnershipState(string &reason)
{
 if(stateLoaded) return true;
 key=StringFormat("KGH172.%I64d.%s.%I64u",AccountInfoInteger(ACCOUNT_LOGIN),_Symbol,Magic);
 if(MQLInfoInteger(MQL_TESTER)) key="T."+key;
 if(StringLen(key)>63) { reason="State key melebihi63karakter: "+key; return false; }
 if(MQLInfoInteger(MQL_TESTER)){GlobalVariableDel(key);GlobalVariableDel(key+".m");GlobalVariableDel(key+".p");}
 lastDecision=(datetime)GlobalVariableGet(key+".m");pauseUntil=(datetime)GlobalVariableGet(key+".p");
 double raw=0.0;
 if(GlobalVariableCheck(key))
 {
  ResetLastError();
  if(!GlobalVariableGet(key,raw))
  { reason=StringFormat("State tersimpan gagal dibaca; key=%s error=%d. Tidak diasumsikan0 dan tidak direset",key,GetLastError()); return false; }
 }
 if(!MathIsValidNumber(raw) || (raw!=0.0 && raw!=1.0))
 { reason=StringFormat("State tersimpan wajib tepat0 atau1; aktual=%.16f key=%s. Nilai tidak direset",raw,key); return false; }
 state=(int)raw;
 stateLoaded=true;
 trade.SetExpertMagicNumber(Magic);
 trade.SetDeviationInPoints(DeviationPoints);
 trade.SetTypeFillingBySymbol(_Symbol);
 trade.SetAsyncMode(false);
 Scan();
 return true;
}

bool EnsureReady()
{
 if(readiness==ENV_READY) return true;
 if(readiness==ENV_BLOCKED) return false;
 ulong now=GetTickCount64();
 if(lastReadinessMs>0 && now-lastReadinessMs<1000) return false;
 lastReadinessMs=now;
 string reason;
 INIT_STATUS next=CheckEnvironment(reason);
 if(next==ENV_READY && !LoadOwnershipState(reason)) next=ENV_BLOCKED;
 if(next!=readiness || reason!=readinessReason) Print("INIT STATUS: ",reason);
 readiness=next; readinessReason=reason;
 ShowStatus();
 return readiness==ENV_READY;
}

void SetState(int value)
{
 state=value;
 GlobalVariableSet(key,(double)value);
 GlobalVariablesFlush();
}

bool Owned()
{
 return PositionGetString(POSITION_SYMBOL)==_Symbol &&
        (ulong)PositionGetInteger(POSITION_MAGIC)==Magic;
}

void Scan()
{
 count=0; side=-1; pnl=0; basketVolume=0; lastMs=0; lastPrice=0; lastLot=0; mixed=false;
 ulong lastTicket=0;sharedSL=0;oldestEntry=0;sharedTP=0;trendBasket=false;intradayBasket=false;
 for(int i=PositionsTotal()-1;i>=0;i--)
 {
  ulong ticket=PositionGetTicket(i);
  if(ticket==0 || !Owned()) continue;
  int s=(int)PositionGetInteger(POSITION_TYPE);
  if(side==-1) side=s; else if(side!=s) mixed=true;
  double level=PositionGetDouble(POSITION_SL);
  datetime opened=(datetime)PositionGetInteger(POSITION_TIME);
  double target=PositionGetDouble(POSITION_TP);
  if(count==0){sharedSL=level;oldestEntry=opened;sharedTP=target;intradayBasket=PositionGetString(POSITION_COMMENT)=="K172I";trendBasket=StringFind(PositionGetString(POSITION_COMMENT),"K172T")==0;}else oldestEntry=MathMin(oldestEntry,opened);
  if(target<=0 || MathAbs(target-sharedTP)>_Point/2 || level<=0 || MathAbs(level-sharedSL)>_Point/2)mixed=true;
  count++;
  double v=PositionGetDouble(POSITION_VOLUME);
  basketVolume+=v;
  pnl+=PositionGetDouble(POSITION_PROFIT)+PositionGetDouble(POSITION_SWAP)
       -v*(EstimatedRoundTripCostUSCPerLot/100.0)*moneyScale;
  long ms=PositionGetInteger(POSITION_TIME_MSC);
  if(ms>lastMs || (ms==lastMs && ticket>lastTicket))
  {
   lastMs=ms; lastTicket=ticket;
   lastPrice=PositionGetDouble(POSITION_PRICE_OPEN); lastLot=v;
  }
 }
}

double Lot(double requested)
{
 double step=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
 double minimum=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
 double cap=MathMin(MaxLot,SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX));
 if(step<=0 || requested<minimum-1e-9 || cap<minimum) return 0;
 return NormalizeDouble(MathFloor((MathMin(requested,cap)+1e-9)/step)*step,8);
}

bool HasOutstandingOrder()
{
 for(int i=OrdersTotal()-1;i>=0;i--)
 {
  if(OrderGetTicket(i)==0) continue;
  if(OrderGetString(ORDER_SYMBOL)==_Symbol && (ulong)OrderGetInteger(ORDER_MAGIC)==Magic)
   return true;
 }
 return false;
}

bool Allowed()
{
 return TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) && MQLInfoInteger(MQL_TRADE_ALLOWED)
        && AccountInfoInteger(ACCOUNT_TRADE_ALLOWED) && AccountInfoInteger(ACCOUNT_TRADE_EXPERT);
}

void Open(int direction,double requested,MqlTick &tick,double stop,double target,string orderTag)
{
 if(readiness!=ENV_READY || !Allowed() || HasOutstandingOrder() || EntryBlocked()) return;
 double lot=Lot(requested);
 if(lot<=0) return;
 double limit=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_LIMIT);
 // Include other strategies' same-direction positions/orders in broker exposure limit.
 double exposure=0;
 for(int i=PositionsTotal()-1;i>=0;i--)
 {
  if(PositionGetTicket(i)==0) continue;
  if(PositionGetString(POSITION_SYMBOL)==_Symbol &&
     PositionGetInteger(POSITION_TYPE)==direction) exposure+=PositionGetDouble(POSITION_VOLUME);
 }
 for(int i=OrdersTotal()-1;i>=0;i--)
 {
  if(OrderGetTicket(i)==0 || OrderGetString(ORDER_SYMBOL)!=_Symbol) continue;
  ENUM_ORDER_TYPE t=(ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE);
  bool buy=(t==ORDER_TYPE_BUY || t==ORDER_TYPE_BUY_LIMIT || t==ORDER_TYPE_BUY_STOP || t==ORDER_TYPE_BUY_STOP_LIMIT);
  if((direction==POSITION_TYPE_BUY)==buy) exposure+=OrderGetDouble(ORDER_VOLUME_CURRENT);
 }
 if(limit>0 && exposure+lot>limit+1e-9) return;
 ENUM_ORDER_TYPE type=(direction==POSITION_TYPE_BUY ? ORDER_TYPE_BUY : ORDER_TYPE_SELL);
 double margin=0,price=(direction==POSITION_TYPE_BUY ? tick.ask : tick.bid);
 if(!OrderCalcMargin(type,_Symbol,lot,price,margin) || margin>AccountInfoDouble(ACCOUNT_MARGIN_FREE)) return;
 lastAttempt=TimeCurrent();
 if(stop<=0 || (direction==POSITION_TYPE_BUY ? tick.bid-stop : stop-tick.ask)<=SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL)*_Point)return;
 bool ok=trade.PositionOpen(_Symbol,type,lot,price,stop,target,orderTag);
 uint rc=trade.ResultRetcode();
 if(!ok || (rc!=TRADE_RETCODE_DONE && rc!=TRADE_RETCODE_DONE_PARTIAL && rc!=TRADE_RETCODE_PLACED))
  Print("Entry failed: ",rc," ",trade.ResultRetcodeDescription());
}

void CloseBasket()
{
 if(readiness!=ENV_READY || !Allowed() || HasOutstandingOrder()) return;
 // Close retry has its own clock: entry throttle never delays the first close.
 if(MQLInfoInteger(MQL_TESTER))
 {
  if(lastSimCloseAttempt>0 && TimeCurrent()-lastSimCloseAttempt<1) return;
  lastSimCloseAttempt=TimeCurrent();
 }
 else
 {
  ulong now=GetTickCount64();
  if(lastCloseAttemptMs>0 && now-lastCloseAttemptMs<1000) return;
  lastCloseAttemptMs=now;
 }
 lastAttempt=TimeCurrent();
 for(int i=PositionsTotal()-1;i>=0;i--)
 {
  ulong ticket=PositionGetTicket(i);
  if(ticket==0 || !Owned()) continue;
  bool ok=trade.PositionClose(ticket,DeviationPoints);
  uint rc=trade.ResultRetcode();
  if(!ok || (rc!=TRADE_RETCODE_DONE && rc!=TRADE_RETCODE_DONE_PARTIAL))
   Print("Close retry pending #",ticket,": ",rc," ",trade.ResultRetcodeDescription());
 }
 Scan();
 if(count==0 && !HasOutstandingOrder()) SetState(0);
}

bool simulation=false, calendarReady=false;
datetime nextRefresh=0, liveRelease[];


void RefreshCalendar(datetime now){
   if(simulation || now<nextRefresh)return;
   MqlCalendarValue values[];
   datetime times[];
   int releaseCount=CalendarValueHistory(values,now-3*86400,now+2*86400,"US");
   bool ok=releaseCount>=0 && TerminalInfoInteger(TERMINAL_CONNECTED);
   int used=0;
   if(ok && ArrayResize(times,releaseCount)!=releaseCount)ok=false;
   for(int i=0;ok && i<releaseCount;i++){
      MqlCalendarEvent event;
      if(!CalendarEventById(values[i].event_id,event)){ok=false;break;}
      if(event.importance==CALENDAR_IMPORTANCE_HIGH && event.time_mode==CALENDAR_TIMEMODE_DATETIME)
         times[used++]=values[i].time;
   }
   if(ok){
      ArrayResize(times,used);
      ArraySwap(times,liveRelease);
   }
   if(calendarReady!=ok || nextRefresh==0)
      Print(ok?"US news calendar available":"US news calendar unavailable. New entries suspended.");
   calendarReady=ok;
   nextRefresh=now+(ok?60:15);
}

// Does the interval [from,now] overlap a scheduled exclusion window?
bool NewsOverlap(datetime from,datetime now){
   if(simulation){
      int lo=0,hi=ArraySize(newsEnd);
      while(lo<hi){
         int mid=lo+(hi-lo)/2;
         if(newsEnd[mid]<from)lo=mid+1;else hi=mid;
      }
      return lo<ArraySize(newsStart) && newsStart[lo]<=now;
   }
   for(int i=0;i<ArraySize(liveRelease);i++)
      if(liveRelease[i]-1800<=now && liveRelease[i]+1800>=from)return true;
   return false;
}


double breakoutRisk=0,midRange=0,rangeStop=0;
bool isBreakout=false;
int intradaySide=0;
double hourlyRisk=0;
bool Signals(datetime bar){
 if(cachedSignal==bar)return true;
 MqlRates h[],m[],f[];
 ArraySetAsSeries(h,true);ArraySetAsSeries(m,true);ArraySetAsSeries(f,true);
 if(CopyRates(_Symbol,PERIOD_H1,1,12,h)!=12 || CopyRates(_Symbol,PERIOD_M15,1,15,m)!=15 ||
    CopyRates(_Symbol,PERIOD_M5,1,2,f)!=2)return false;
 double mean=0,total=0;
 for(int i=0;i<12;i++)mean+=h[i].close;
 for(int i=0;i<14;i++)total+=MathMax(m[i].high-m[i].low,MathMax(MathAbs(m[i].high-m[i+1].close),MathAbs(m[i].low-m[i+1].close)));
 mean/=12;atr=total/14;if(atr<=0)return false;
 MqlRates slow[];ArraySetAsSeries(slow,true);
 if(CopyRates(_Symbol,PERIOD_H4,1,25,slow)!=25)return false;
 double top=slow[1].high,base=slow[1].low,vol=0;
 for(int i=1;i<=24;i++){top=MathMax(top,slow[i].high);base=MathMin(base,slow[i].low);}
 for(int i=0;i<14;i++)vol+=MathMax(slow[i].high-slow[i].low,
   MathMax(MathAbs(slow[i].high-slow[i+1].close),MathAbs(slow[i].low-slow[i+1].close)));
 breakoutRisk=2.*vol/14;
 trend=slow[0].close>top?1:(slow[0].close<base?-1:0);
 signal=0;isBreakout=false;spike=f[0].high-f[0].low>2*atr;
 if(bar==iTime(_Symbol,PERIOD_H4,0) && trend!=0){signal=trend;isBreakout=true;}
 else if(trend==0 && bar==iTime(_Symbol,PERIOD_H1,0) && MathAbs(h[0].close-mean)<=atr){
   double hi=h[1].high,lo=h[1].low;
   for(int i=2;i<12;i++){hi=MathMax(hi,h[i].high);lo=MathMin(lo,h[i].low);}
   midRange=(hi+lo)/2.;
   bool down=h[0].low<lo && h[0].close>lo && h[0].close<midRange && h[0].close>h[0].open;
   bool up=h[0].high>hi && h[0].close<hi && h[0].close>midRange && h[0].close<h[0].open;
   if(down){signal=1;rangeStop=h[0].low-.25*atr;}
   if(up){signal=-1;rangeStop=h[0].high+.25*atr;}
 }

 // At each M5 open, use the M1 candle just before that boundary.
 // Reading by timestamp also keeps a reconnect mid-bar from changing the signal.
 MqlRates minute[1];
 if(CopyRates(_Symbol,PERIOD_M1,bar-60,bar-1,minute)!=1)return false;
 double upper=h[1].high,lower=h[1].low,rangeSum=0;
 for(int i=1;i<12;i++){
    upper=MathMax(upper,h[i].high);
    lower=MathMin(lower,h[i].low);
    rangeSum+=MathMax(h[i-1].high-h[i-1].low,MathMax(MathAbs(h[i-1].high-h[i].close),MathAbs(h[i-1].low-h[i].close)));
 }
 hourlyRisk=1.5*rangeSum/11.;
 intradaySide=0;
 if(h[0].close>upper && minute[0].close>minute[0].open && trend>=0)intradaySide=1;
 if(h[0].close<lower && minute[0].close<minute[0].open && trend<=0)intradaySide=-1;
 cachedSignal=bar;return true;
}

bool ForeignExposure(){
 for(int i=PositionsTotal()-1;i>=0;i--)
   if(PositionGetTicket(i)>0 && PositionGetString(POSITION_SYMBOL)==_Symbol && !Owned())return true;
 for(int i=OrdersTotal()-1;i>=0;i--)
   if(OrderGetTicket(i)>0 && OrderGetString(ORDER_SYMBOL)==_Symbol && (ulong)OrderGetInteger(ORDER_MAGIC)!=Magic)return true;
 return false;
}

void PauseAfterStop(datetime when){
 pauseUntil=MathMax(pauseUntil,when+900);
 GlobalVariableSet(key+".p",(double)pauseUntil);GlobalVariablesFlush();
}
void OnTradeTransaction(const MqlTradeTransaction &tx,const MqlTradeRequest &rq,const MqlTradeResult &res){
 if(!stateLoaded || tx.type!=TRADE_TRANSACTION_DEAL_ADD || !HistoryDealSelect(tx.deal))return;
 if(HistoryDealGetString(tx.deal,DEAL_SYMBOL)!=_Symbol ||
    (ulong)HistoryDealGetInteger(tx.deal,DEAL_MAGIC)!=Magic ||
    HistoryDealGetInteger(tx.deal,DEAL_REASON)!=DEAL_REASON_SL)return;
 PauseAfterStop((datetime)HistoryDealGetInteger(tx.deal,DEAL_TIME));
 Scan();if(count>0)SetState(1);
}

// Reconstruct recent broker-side stops after restart or a disconnected terminal.
bool RestoreStopPause(datetime now){
 if(!HistorySelect(now-901,now))return false;
 for(int i=HistoryDealsTotal()-1;i>=0;i--){
   ulong d=HistoryDealGetTicket(i);if(!d)return false;
   if(HistoryDealGetString(d,DEAL_SYMBOL)!=_Symbol || (ulong)HistoryDealGetInteger(d,DEAL_MAGIC)!=Magic ||
      HistoryDealGetInteger(d,DEAL_REASON)!=DEAL_REASON_SL)continue;
   datetime when=(datetime)HistoryDealGetInteger(d,DEAL_TIME);
   if(when+900>pauseUntil)PauseAfterStop(when);
   break;
 }
 return true;
}
bool Protect(datetime now){
 if(now<=0)return true;
 RefreshCalendar(now);
 if(state==1){
   if(!count && !HasOutstandingOrder())SetState(0);else CloseBasket();
   return true;
 }
 if(count && (mixed || now-oldestEntry>=48*3600 || NewsOverlap(oldestEntry,now) || now<pauseUntil)){
   SetState(1);CloseBasket();return true;
 }
 return NewsOverlap(now,now);
}

int OnInit()
{
 simulation=(bool)MQLInfoInteger(MQL_TESTER);
 if(simulation){Print("Strategy Tester MT5 tidak menjalankan WebRequest. Gunakan demo untuk uji model.");return INIT_FAILED;}
 if(AccountInfoString(ACCOUNT_SERVER)!="HFMarketsGlobal-Live12"){Print("Khusus HFMarketsGlobal-Live12");return INIT_FAILED;}
 PrintFormat("INIT v1.72: expected HFM/USC/XAUUSDc/hedging/contract1/minLotCompatible0.01; actual server='%s' currency='%s' symbol='%s' contract=%.8f minLot=%.8f lotStep=%.8f maxLot=%.8f tester=%d custom=%I64d",AccountInfoString(ACCOUNT_SERVER),AccountInfoString(ACCOUNT_CURRENCY),_Symbol,SymbolInfoDouble(_Symbol,SYMBOL_TRADE_CONTRACT_SIZE),SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN),SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP),SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX),(int)MQLInfoInteger(MQL_TESTER),SymbolInfoInteger(_Symbol,SYMBOL_CUSTOM));
 if(!InputsValid(readinessReason))
 { readiness=ENV_BLOCKED; Print("INIT_PARAMETERS_INCORRECT (2): ",readinessReason); ShowStatus(); return INIT_PARAMETERS_INCORRECT; }
 readiness=CheckEnvironment(readinessReason);
 if(readiness==ENV_READY && !LoadOwnershipState(readinessReason)) readiness=ENV_BLOCKED;
 if(readiness==ENV_BLOCKED)
 { Print("INIT_FAILED (1): ",readinessReason); ShowStatus(); return INIT_FAILED; }
 Print("INIT STATUS: ",readinessReason);
 if(!EventSetTimer(1))
 { PrintFormat("INIT_FAILED (1): timer retry tidak dapat dibuat; error=%d",GetLastError()); return INIT_FAILED; }
 if(readiness==ENV_READY) EntryBlocked();
 ShowStatus();
 return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) { EventKillTimer(); Print("Deinit reason=",reason); Comment(""); }

void OnTimer()
{
 if(!EnsureReady()) { ShowStatus(); return; }
 if(!MQLInfoInteger(MQL_TESTER)){Scan();Protect(TimeTradeServer());ShowStatus();}
}

void OnTick(){
 if(!EnsureReady())return;
 datetime now=TimeCurrent();
 if(simulation && (now<D'2026.01.01' || now>=D'2026.11.15')){TesterStop();return;}
 Scan();
 if(Protect(now))return;
 datetime bar=iTime(_Symbol,PERIOD_M5,0);
 if(bar<=0 || !Signals(bar))return;
 int direction=side==POSITION_TYPE_BUY?1:-1;
 datetime h4Open=iTime(_Symbol,PERIOD_H4,0);
 if(h4Open<=0)return;
 bool closingH4=now>=h4Open+PeriodSeconds(PERIOD_H4)-300;
 if(count && intradayBasket && (closingH4 || oldestEntry<h4Open)){SetState(1);CloseBasket();return;}
 if(count && trend*direction<0){SetState(1);CloseBasket();return;}
 if((!count && !signal && !intradaySide) || spike || now<pauseUntil || (!simulation && !calendarReady) || lastDecision==bar ||
    count>=MaxPositions || HasOutstandingOrder() || EntryBlocked() || !Allowed() || ForeignExposure())return;
 static datetime restoredBar=0;
 if(!simulation && restoredBar!=bar){
   if(!RestoreStopPause(now))return;
   restoredBar=bar;
   if(now<pauseUntil)return;
 }
 MqlTick tick;if(!SymbolInfoTick(_Symbol,tick)||tick.ask<tick.bid||tick.bid<=0 || tick.ask-tick.bid>MaxSpreadPrice+1e-9)return;
 double tickSize=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);if(tickSize<=0)return;
 bool intraday=!count && !signal && intradaySide!=0;
 if(intraday && closingH4)return;
 int sideToOpen=intraday?intradaySide:signal;
 if(count){
    if(!trendBasket || pnl<=0 || direction*( (direction>0?tick.bid:tick.ask)-lastPrice)<MathMax(GridPriceDistance,.5*atr))return;
    MqlRates last[1];if(CopyRates(_Symbol,PERIOD_M5,1,1,last)!=1 || direction*(last[0].close-last[0].open)<=0)return;
    sideToOpen=direction;
 }
 if(sideToOpen==0)return;
 double entry=sideToOpen>0?tick.ask:tick.bid;
 double stop=count?sharedSL:(isBreakout?entry-sideToOpen*breakoutRisk:rangeStop);
 double target=count?sharedTP:(isBreakout?entry+sideToOpen*2*breakoutRisk:midRange);
 if(intraday){
    // Intraday baskets have their own shorter price objective, with no averaging.
    double distance=MathMax(hourlyRisk,GridPriceDistance);
    stop=entry-sideToOpen*distance;
    target=entry+sideToOpen*2.*distance;
 }
 stop=NormalizeDouble(MathRound(stop/tickSize)*tickSize,_Digits);
 target=NormalizeDouble(MathRound(target/tickSize)*tickSize,_Digits);
 if(sideToOpen*(entry-stop)<=0 || sideToOpen*(target-entry)<.50)return;
 // All layers have the same stop. Include loss from current entry versus stop for each ticket individually.
 double loss=0,pl=0;
 ENUM_ORDER_TYPE orderType=sideToOpen>0?ORDER_TYPE_BUY:ORDER_TYPE_SELL;
 if(!OrderCalcProfit(orderType,_Symbol,BaseLot,entry,stop,pl))return;
 loss=MathMax(0.,-pl);
 for(int i=PositionsTotal()-1;i>=0;i--){
   if(PositionGetTicket(i)==0 || !Owned())continue;
   if(!OrderCalcProfit(orderType,_Symbol,PositionGetDouble(POSITION_VOLUME),PositionGetDouble(POSITION_PRICE_OPEN),stop,pl))return;
   loss+=MathMax(0.,-pl-PositionGetDouble(POSITION_SWAP));
 }
 if(loss+(basketVolume+BaseLot)*EstimatedRoundTripCostUSCPerLot*moneyScale/100.>MathMin(500.*moneyScale/100.,AccountInfoDouble(ACCOUNT_EQUITY)*.005))return;
 if(!SolAllows(bar,sideToOpen,entry,stop,target,tick))return;
 solApproved=false;
 lastDecision=bar;GlobalVariableSet(key+".m",(double)bar);GlobalVariablesFlush();
 Open(sideToOpen>0?POSITION_TYPE_BUY:POSITION_TYPE_SELL,BaseLot,tick,stop,target,intraday?"K172I":(count || isBreakout?"K172T":"K172R"));
}
