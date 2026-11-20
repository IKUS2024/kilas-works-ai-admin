// KilasWorks HTTPS approval. The OpenAI credential lives on the server.
const string SolURL="https://trading.kilasworks.id/products/services/trading/robot-hfm/signal";
string solStatus="Menunggu sinyal lokal";
datetime solBar=0,solUTC=0;
int solSide=0;
double solEntry=0;
bool solApproved=false;
ulong solMonotonic=0;

string FrameJson(ENUM_TIMEFRAMES tf){
   MqlRates bars[];
   if(CopyRates(_Symbol,tf,1,6,bars)!=6)return "";
   string buf="[";
   for(int i=0;i<6;i++){
      if(i>0)buf+=",";
      buf+="["+DoubleToString(bars[i].open,_Digits)+","+DoubleToString(bars[i].high,_Digits)+","+
               DoubleToString(bars[i].low,_Digits)+","+DoubleToString(bars[i].close,_Digits)+"]";
   }
   return buf+"]";
}

string PairToken(){
   int f=FileOpen("kilas-hfm-sol.key",FILE_READ|FILE_TXT|FILE_ANSI|FILE_SHARE_READ);
   if(f==INVALID_HANDLE)return "";
   string login=FileReadString(f), token=FileReadString(f);
   FileClose(f);
   if(login!=IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN))||StringLen(token)!=64)return "";
   for(int i=0;i<64;i++){
      ushort c=StringGetCharacter(token,i);
      if(!((c>=48&&c<=57)||(c>=97&&c<=102)))return "";
   }
   return token;
}

bool SolAllows(datetime bar,int proposedSide,double entry,double stop,double target,MqlTick &tick){
   if(MQLInfoInteger(MQL_TESTER))return false;
   if(solBar==bar){
      if(!solApproved || solSide!=proposedSide)return false;
      if(GetTickCount64()-solMonotonic>25000 || MathAbs(entry-solEntry)>.30){
         solApproved=false;solStatus="Tunda: persetujuan kedaluwarsa atau harga bergeser";return false;
      }
      return true;
   }
   solBar=bar;solApproved=false;solSide=proposedSide;solEntry=entry;
   string token=PairToken();
   if(token==""){solStatus="File koneksi hilang atau akun berbeda";return false;}
   string m5=FrameJson(PERIOD_M5),m15=FrameJson(PERIOD_M15),h1=FrameJson(PERIOD_H1),h4=FrameJson(PERIOD_H4);
   if(m5==""||m15==""||h1==""||h4==""){solStatus="Menunggu riwayat candle";return false;}
   string dir=proposedSide>0?"BUY":"SELL";
   solUTC=TimeGMT();solMonotonic=GetTickCount64();
   string payload=StringFormat("{\"login\":\"%I64d\",\"server\":\"HFMarketsGlobal-Live12\",\"symbol\":\"XAUUSDc\",\"at\":%I64d,\"bar\":%I64d,\"side\":\"%s\",\"bid\":%s,\"ask\":%s,\"sl\":%s,\"tp\":%s,\"frames\":{\"M5\":%s,\"M15\":%s,\"H1\":%s,\"H4\":%s}}",
      AccountInfoInteger(ACCOUNT_LOGIN),(long)solUTC,(long)bar,dir,DoubleToString(tick.bid,_Digits),
      DoubleToString(tick.ask,_Digits),DoubleToString(stop,_Digits),DoubleToString(target,_Digits),m5,m15,h1,h4);
   char body[],result[];
   int length=StringToCharArray(payload,body,0,WHOLE_ARRAY,CP_UTF8);
   if(length<=1)return false;
   ArrayResize(body,length-1);
   string headers="Content-Type: application/json\r\nAuthorization: Bearer "+token+"\r\n",responseHeaders;
   ResetLastError();
   int status=WebRequest("POST",SolURL,headers,12000,body,result,responseHeaders);
   if(status!=200){solStatus=StringFormat("Tunda: koneksi KilasWorks (HTTP %d, MT5 %d)",status,GetLastError());return false;}
   string reply=CharArrayToString(result,0,WHOLE_ARRAY,CP_UTF8);
   solApproved=(reply=="K1|"+IntegerToString((long)bar)+"|"+dir);
   solStatus=solApproved?"AI menyetujui "+dir:"AI menunggu";
   // A fresh tick must re-run all risk, connection and eligibility checks before entry.
   return false;
}
