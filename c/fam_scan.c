// fam_scan.c - SetiYeti square-law / fourth-power cyclo scanner (dependency-free C99)
// Finds hidden baud/periodicities under noise: Y2=x^2 (BPSK/DSSS chip rate, 2x carrier),
// Y4=(x^2-m)^2 (QPSK energy). Peaks in |FFT(Y)| = cyclic frequencies alpha.
// This is the f=0 slice of S_x^alpha(f): cheap, robust, no carrier knowledge needed.
// Usage: fam_scan <in.f32> [fs_Hz=2929687.5] [seg=131072] [topK=15] [candpath]
//   candpath: where to write ratio>3.0 candidates (default alpha_candidates.txt,
//             "-" disables - batch scanners pass "-"; the old unconditional CWD
//             rewrite raced under parallel scans and measured 0 bytes anyway).
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <math.h>
#include "vendor/sy_fft.h"   /* BEAST: cached-twiddle FFT core */
#include "vendor/sy_stats.h" /* BEAST: quickselect median */

/* fft_mag2 now routes through the vendored core (same math, no per-butterfly
   trig). Local median helper kept for the accumulation floor. */
static void fft_mag2(double* re, double* im, int n, double* out_pwr) {
    sy_fft_mag2(re, im, n, out_pwr);
}

static void fft_mag2_old(double* re, double* im, int n, double* out_pwr) {
    for (int i=1,j=0;i<n;i++){
        int bit=n>>1;
        for(;j&bit;bit>>=1) j&=~bit;
        j|=bit;
        if(i<j){double t=re[i];re[i]=re[j];re[j]=t;t=im[i];im[i]=im[j];im[j]=t;}
    }
    for(int len=2;len<=n;len<<=1){
        double ang=-2*M_PI/len;
        double wr=cos(ang), wi=sin(ang);
        for(int i=0;i<n;i+=len){
            double cwr=1.0,cwi=0.0;
            for(int k=0;k<len/2;k++){
                double ur=re[i+k],ui=im[i+k];
                double vr=re[i+k+len/2]*cwr-im[i+k+len/2]*cwi;
                double vi=re[i+k+len/2]*cwi+im[i+k+len/2]*cwr;
                re[i+k]=ur+vr; im[i+k]=ui+vi;
                re[i+k+len/2]=ur-vr; im[i+k+len/2]=ui-vi;
                double nwr=cwr*wr-cwi*wi, nwi=cwr*wi+cwi*wr;
                cwr=nwr; cwi=nwi;
            }
        }
    }
    for(int i=0;i<n;i++) out_pwr[i]=re[i]*re[i]+im[i]*im[i];
}

static int cmp_d(const void*a,const void*b){double x=*(double*)a,y=*(double*)b;return(x<y?-1:x>y?1:0);}
static double median(double*v,int n){ return sy_median(v,n); }

static void scan_feature(float* x, int nx, double fs, int SEG, int topK, const char* tag, FILE* cand) {
    double* re=malloc(SEG*sizeof(double));
    double* im=malloc(SEG*sizeof(double));
    double* pwr=malloc(SEG*sizeof(double));
    double* acc=calloc(SEG/2+1,sizeof(double));
    // build feature on the fly per segment
    double m2=0; // mean of x^2 for Y4 centering (compute globally cheap)
    // global mean of x^2
    { double s=0; int st=nx>200000?200000:nx; for(int i=0;i<st;i++){double v=x[i];s+=v*v;} m2=s/st; }
    int nseg=0;
    for(int off=0; off+SEG<=nx; off+=SEG){
        if(!strcmp(tag,"Y2")){
            double m=0; for(int i=0;i<SEG;i++){double v=x[off+i];m+=v*v;} m/=SEG;
            for(int i=0;i<SEG;i++){double v=x[off+i];re[i]=v*v-m;im[i]=0;}
        } else {
            for(int i=0;i<SEG;i++){double v=x[off+i];double y=v*v-m2;re[i]=y*y;im[i]=0;}
            // remove seg mean
            double m=0; for(int i=0;i<SEG;i++)m+=re[i]; m/=SEG;
            for(int i=0;i<SEG;i++)re[i]-=m;
        }
        fft_mag2(re,im,SEG,pwr);
        for(int i=0;i<=SEG/2;i++) acc[i]+=pwr[i];
        nseg++;
    }
    for(int i=0;i<=SEG/2;i++) acc[i]/=nseg;
    double med=median(acc+1,SEG/2-1);
    // topK excluding DC, simple non-max suppression (min sep 3 bins)
    printf("--- %s segs=%d SEG=%d fs=%.1f med=%.3e ---\n",tag,nseg,SEG,fs,med);
    int* taken=calloc(SEG/2+1,sizeof(int));
    for(int k=0;k<topK;k++){
        int bi=-1; double bv=0;
        for(int i=2;i<=SEG/2;i++){ if(!taken[i]&&acc[i]>bv){bv=acc[i];bi=i;} }
        if(bi<0) break;
        for(int i=bi-3;i<=bi+3;i++) if(i>=0&&i<=SEG/2) taken[i]=1;
        double hz=(double)bi*fs/SEG;
        double ratio=bv/med;
        printf("%s peak %2d bin=%-7d alpha=%12.2f Hz  ratio=%6.2fx\n",tag,k,bi,hz,ratio);
        if(cand&&ratio>3.0) fprintf(cand,"%s %.2f %d %.2f\n",tag,hz,bi,ratio);
    }
    free(re);free(im);free(pwr);free(acc);free(taken);
}

int main(int argc,char**argv){
    if(argc<2){fprintf(stderr,"usage: %s <in.f32> [fs] [seg] [topK] [candpath|-]\n",argv[0]);return 2;}
    double fs=argc>2?atof(argv[2]):2929687.5;
    int SEG=argc>3?atoi(argv[3]):32768;
    int topK=argc>4?atoi(argv[4]):15;
    FILE*f=fopen(argv[1],"rb"); if(!f){perror("fopen");return 1;}
    fseek(f,0,SEEK_END); long nb=ftell(f); fseek(f,0,SEEK_SET);
    int nx=nb/4;
    float* x=malloc(nb); fread(x,1,nb,f); fclose(f);
    printf("samples=%d fs=%.1f seg=%d\n",nx,fs,SEG);
    const char* candpath=argc>5?argv[5]:"alpha_candidates.txt";
    FILE*cand=NULL;
    if(strcmp(candpath,"-")!=0) cand=fopen(candpath,"w");
    scan_feature(x,nx,fs,SEG,topK,"Y2",cand);
    scan_feature(x,nx,fs,SEG,topK,"Y4",cand);
    if(cand) fclose(cand);
    if(cand) printf("[cand] %s written (ratio>3.0)\n",candpath);
    free(x);
    return 0;
}
