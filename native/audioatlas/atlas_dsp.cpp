/* AudioAtlas native feature extractor. Copyright 2026 Authority Closers.
   MIT. No machine-learning weights or third-party source embedded.
   Input: little-endian float32, interleaved, sample rate supplied.
   Output: little-endian float64 frame rows + optional float32 log spectrum.
   Same mathematical calculation in direct and FFT autocorrelation modes.
*/
#if defined(AA_CROSS)
typedef unsigned long long size_t;
typedef long long i64;
extern "C" {
struct FILE;
FILE* fopen(const char*, const char*); int fclose(FILE*);
size_t fread(void*,size_t,size_t,FILE*); size_t fwrite(const void*,size_t,size_t,FILE*);
int fseek(FILE*,long,int); long ftell(FILE*); int fflush(FILE*);
void* malloc(size_t); void* calloc(size_t,size_t); void free(void*);
int printf(const char*,...); int atoi(const char*); int strcmp(const char*,const char*);
double sin(double); double cos(double); double sqrt(double); double log(double);
double log10(double); double exp(double); double pow(double,double); double fabs(double);
void* memset(void*,int,size_t); void* memcpy(void*,const void*,size_t);
}
#else
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cmath>
typedef long long i64;
#endif
#ifdef _WIN32
#if defined(AA_CROSS)
extern "C" {
FILE* _wfopen(const wchar_t*, const wchar_t*);
__declspec(dllimport) int WideCharToMultiByte(unsigned int,unsigned long,const wchar_t*,int,char*,int,const char*,int*);
__declspec(dllimport) int MultiByteToWideChar(unsigned int,unsigned long,const char*,int,wchar_t*,int);
__declspec(dllimport) int __wgetmainargs(int*,wchar_t***,wchar_t***,int,int*);
__declspec(dllimport) void ExitProcess(unsigned int);
}
#else
#include <windows.h>
#endif
static FILE* open_utf8(const char* name,const char* mode){
  int n=MultiByteToWideChar(65001,8,name,-1,0,0);if(n<=0)return 0;
  wchar_t* p=(wchar_t*)malloc((size_t)n*sizeof(wchar_t));if(!p)return 0;
  wchar_t wm[8];if(!MultiByteToWideChar(65001,8,name,-1,p,n)||!MultiByteToWideChar(65001,8,mode,-1,wm,8)){free(p);return 0;}
  FILE*f=_wfopen(p,wm);free(p);return f;
}
#else
static FILE* open_utf8(const char* name,const char* mode){return fopen(name,mode);}
#endif
static const double PI=3.1415926535897932384626433832795;
static const int COLS=18;
static void fft(double *re,double *im,int n,int inverse) {
  for(int i=1,j=0;i<n;i++) {int bit=n>>1; for(;j&bit;bit>>=1)j^=bit; j^=bit;
    if(i<j){double t=re[i];re[i]=re[j];re[j]=t;t=im[i];im[i]=im[j];im[j]=t;}}
  for(int len=2;len<=n;len<<=1){double angle=(inverse?2.0:-2.0)*PI/len;
    double wr0=cos(angle),wi0=sin(angle);
    for(int i=0;i<n;i+=len){double wr=1,wi=0;
      for(int j=0;j<len/2;j++){int a=i+j,b=a+len/2;
        double tr=wr*re[b]-wi*im[b],ti=wr*im[b]+wi*re[b];
        re[b]=re[a]-tr;im[b]=im[a]-ti;re[a]+=tr;im[a]+=ti;
        double next=wr*wr0-wi*wi0;wi=wr*wi0+wi*wr0;wr=next;}}}
  if(inverse)for(int i=0;i<n;i++){re[i]/=n;im[i]/=n;}
}
static double maxd(double a,double b){return a>b?a:b;}
static double mind(double a,double b){return a<b?a:b;}
static int imin(int a,int b){return a<b?a:b;}
static int run(int argc,char**argv){
  if(argc<6){printf("AudioAtlas DSP 0.1\nUsage: aa-dsp INPUT.f32 OUTPUT.f64 RATE CHANNELS direct|fft [SPECTRUM.f32]\n18 columns; see docs/DATA_CONTRACT.md. Input max 2GB; frames 40ms, hop 10ms.\n");return argc==1?0:2;}
  const int sr=atoi(argv[3]),ch=atoi(argv[4]);
  if(sr<8000||sr>96000||ch<1||ch>8 || (strcmp(argv[5],"fft")&&strcmp(argv[5],"direct"))){printf("invalid rate, channels, or mode\n");return 2;}
  FILE*in=open_utf8(argv[1],"rb");if(!in){printf("cannot open input\n");return 3;}
  if(fseek(in,0,2)){fclose(in);return 3;} long bytes=ftell(in); fseek(in,0,0);
  if(bytes<=0 || bytes>2000000000L || bytes%(4*ch)){printf("invalid or oversized PCM input\n");fclose(in);return 3;}
  i64 total=bytes/(4*ch);int win=sr*40/1000,hop=sr*10/1000;
  int nfft=1;while(nfft<2*win)nfft<<=1;int bins=nfft/2+1;
  int lagmax=imin(win/2,sr/50),lagmin=sr/1000;
  float*raw=(float*)malloc((size_t)win*ch*sizeof(float));
  double*x=(double*)calloc(win,sizeof(double));double*w=(double*)calloc(win,sizeof(double));
  double*re=(double*)calloc(nfft,sizeof(double));double*im=(double*)calloc(nfft,sizeof(double));
  double*prefix=(double*)calloc(win+1,sizeof(double));double*diff=(double*)calloc(lagmax+2,sizeof(double));
  double*prev=(double*)calloc((size_t)bins*ch,sizeof(double));float*spec=(float*)calloc(bins,sizeof(float));
  if(!raw||!x||!w||!re||!im||!prefix||!diff||!prev||!spec){printf("allocation failed\n");fclose(in);return 4;}
  for(int i=0;i<win;i++)w[i]=0.5-0.5*cos(2*PI*i/(win-1));
  FILE*out=open_utf8(argv[2],"wb");FILE*sp=argc>6?open_utf8(argv[6],"wb"):0;
  if(!out || (argc>6&&!sp)){printf("cannot open output\n");fclose(in);return 3;}
  i64 frames=(total+hop-1)/hop;int fast=strcmp(argv[5],"direct")!=0;bool bad=false;
  for(i64 frame=0;frame<frames&&!bad;frame++){
    i64 start=frame*hop;int valid=(int)((total-start)<win?total-start:win);
    if(fseek(in,(long)(start*ch*4),0)){bad=true;break;}
    if(fread(raw,sizeof(float),(size_t)valid*ch,in)!=(size_t)valid*ch){bad=true;break;}
    for(int channel=0;channel<ch;channel++){
      double sum=0,energy=0,peak=0,clipped=0,zc=0,invalid=0;
      for(int i=0;i<valid;i++){double v=raw[i*ch+channel];
        if(!(v==v)||fabs(v)>1e6){invalid++;v=0;} // preserve count; cannot emit NaN
        x[i]=v;sum+=v;energy+=v*v;peak=maxd(peak,fabs(v));if(fabs(v)>=0.999)clipped++;
        if(i&&((v<0)!=(x[i-1]<0)))zc++;}
      for(int i=valid;i<win;i++)x[i]=0;
      double mean=sum/valid,rms=sqrt(energy/valid),db=20*log10(maxd(rms,1e-12));
      for(int i=0;i<nfft;i++){re[i]=i<win?x[i]*w[i]:0;im[i]=0;}fft(re,im,nfft,0);
      double mass=0,centroid=0,logs=0,entropy=0,flux=0,low=0,high=0;
      for(int k=0;k<bins;k++){double p=re[k]*re[k]+im[k]*im[k]; re[k]=p;mass+=p;centroid+=p*k*sr/nfft;logs+=log(maxd(p,1e-30));}
      bool rolloff_set=false;
      double centroid_hz=mass>1e-20?centroid/mass:0,bandwidth=0,rolloff=0,acc=0;
      for(int k=0;k<bins;k++){double p=re[k],freq=(double)k*sr/nfft,prob=mass>1e-20?p/mass:0;
        bandwidth+=prob*(freq-centroid_hz)*(freq-centroid_hz);if(prob>0)entropy-=prob*log(prob);
        acc+=p;if(!rolloff_set&&mass>1e-20&&acc>=0.85*mass){rolloff=freq;rolloff_set=true;}
        if(freq<300)low+=p;if(freq>3400)high+=p;
        double d=prob-prev[(size_t)channel*bins+k];flux+=d*d;prev[(size_t)channel*bins+k]=prob;
        spec[k]=(float)(10*log10(maxd(p/(nfft*nfft),1e-12)));}
      double flat=mass>1e-20?exp(logs/bins)/(mass/bins):0;
      // YIN cumulative mean normalized difference on DC-centred samples.
      prefix[0]=0;for(int i=0;i<win;i++){x[i]=(i<valid?x[i]-mean:0);prefix[i+1]=prefix[i]+x[i]*x[i];}
      if(fast){for(int i=0;i<nfft;i++){re[i]=i<win?x[i]:0;im[i]=0;}fft(re,im,nfft,0);
        for(int i=0;i<nfft;i++){re[i]=re[i]*re[i]+im[i]*im[i];im[i]=0;}fft(re,im,nfft,1);}
      double cumulative=0;diff[0]=1;
      for(int lag=1;lag<=lagmax;lag++){
        double d=0;if(fast){d=maxd(0,prefix[win-lag]+prefix[win]-prefix[lag]-2*re[lag]);}
        else for(int i=0;i<win-lag;i++){double z=x[i]-x[i+lag];d+=z*z;}
        cumulative+=d;diff[lag]=cumulative>1e-24?d*lag/cumulative:1;}
      int best=lagmin;for(int lag=lagmin;lag<=lagmax;lag++){
        if(diff[lag]<diff[best])best=lag;
        if(diff[lag]<0.15){while(lag<lagmax&&diff[lag+1]<diff[lag])lag++;best=lag;break;}}
      double confidence=maxd(0,mind(1,1-diff[best]));double f0=0;
      if(db>-65&&confidence>=0.8&&valid==win&&invalid==0){double offset=0;
        if(best>1&&best<lagmax){double den=diff[best-1]-2*diff[best]+diff[best+1];if(fabs(den)>1e-12)offset=0.5*(diff[best-1]-diff[best+1])/den;}
        f0=sr/(best+mind(1,maxd(-1,offset)));}
      // Position is an integer sample clock. No fabricated word/speaker timing.
      double row[COLS]={(double)start,(double)channel,(double)valid,rms,db,peak,clipped/valid,mean,
        valid>1?zc/(valid-1):0,centroid_hz,sqrt(bandwidth),rolloff,flat,entropy/log((double)bins),sqrt(flux),f0,confidence,invalid};
      if(fwrite(row,sizeof(double),COLS,out)!=COLS){bad=true;break;}
      if(sp&&fwrite(spec,sizeof(float),bins,sp)!=(size_t)bins){bad=true;break;}
    }
  }
  if(fclose(out))bad=true;if(sp&&fclose(sp))bad=true;fclose(in);
  free(raw);free(x);free(w);free(re);free(im);free(prefix);free(diff);free(prev);free(spec);
  if(bad){printf("I/O failure; output incomplete\n");return 5;}
  printf("{\"frames_per_channel\":%lld,\"channels\":%d,\"columns\":%d,\"sample_rate\":%d,\"hop\":%d,\"window\":%d,\"fft_size\":%d,\"mode\":\"%s\"}\n",frames,ch,COLS,sr,hop,win,nfft,argv[5]);return 0;
}
#ifdef _WIN32
static int run_wide(int argc,wchar_t** wide){
  char**argv=(char**)calloc((size_t)argc+1,sizeof(char*));if(!argv)return 4;
  bool ok=true;
  for(int i=0;i<argc;i++){
    int n=WideCharToMultiByte(65001,0,wide[i],-1,0,0,0,0);
    if(n<=0 || !(argv[i]=(char*)malloc(n)) || !WideCharToMultiByte(65001,0,wide[i],-1,argv[i],n,0,0)){ok=false;break;}
  }
  int result=ok?run(argc,argv):4;for(int i=0;i<argc;i++)free(argv[i]);free(argv);return result;
}
#if defined(AA_CROSS)
extern "C" void mainCRTStartup(){int argc=0,info=0;wchar_t**argv=0,**env=0;__wgetmainargs(&argc,&argv,&env,0,&info);ExitProcess(run_wide(argc,argv));}
#else
int wmain(int argc,wchar_t**argv){return run_wide(argc,argv);}
#endif
#else
int main(int argc,char**argv){return run(argc,argv);}
#endif
