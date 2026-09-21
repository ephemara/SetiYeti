// comb_scan.c - SetiYeti cyclostationary COMB + non-Gaussianity tester (C99, -lm only)
//
// WHY THIS EXISTS (Objective 1, M1): mvp_scan's fam_scan trigger fires on a
// SINGLE peak (fam_best >= 3.0). A single SCD bin can be RFI, a filterbank
// edge, or a noise excursion. A real digital modulation imprints a HARMONIC
// COMB (baud f0 with energy at 2*f0, 3*f0, ...) - Gardner-style. This tool
// scores exactly that, plus non-Gaussian tail statistics (coded traffic is
// not perfectly Gaussian; impulsive RFI is wildly non-Gaussian the other
// way), in ONE pass over a slice. Output contract:
//
//   RESULT comb=%d comb_score=%.2f f0_hz=%.1f members=%d nongauss=%d kurt=%.2f tailx=%.2f
//
// THE COMB RULE (shared with python/structure_pass.py - keep them identical):
//   peaks = top-15 Y2/Y4 bins (same spectra as fam_scan, SEG=32768);
//   f0 candidate = each peak bin b0 in 2..128;
//   members = peaks within +-1 bin of m*b0 for m = 1..8 (distinct peaks);
//   comb = 1 iff members >= 3 AND mean(member ratios) >= 6.0.
// Single-tone RFI (one bin, e.g. the ch0 standing line) can never satisfy
// members >= 3. Noise rarely aligns 3 harmonics - see --selftest.
//
// Usage: comb_scan <in.f32> [fs_Hz=2929687.5] [seg=32768]
//        comb_scan --selftest   (prove: comb fires on AM-comb, quiet on noise,
//                               nongauss fires on impulses only; rc=0 on PASS)
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <math.h>
#include "vendor/sy_fft.h"   /* BEAST: cached-twiddle FFT core */
#include "vendor/sy_stats.h" /* BEAST: quickselect median + comb rule */

static void fft_mag2(double* re, double* im, int n, double* out_pwr) {
    sy_fft_mag2(re, im, n, out_pwr);
}

static int cmp_d(const void*a,const void*b){double x=*(double*)a,y=*(double*)b;return(x<y?-1:x>y?1:0);}
static double median(double*v,int n){ return sy_median(v,n); }

/* Feature spectra: Y2 = x^2 (BPSK/chip energy), Y4 = (x^2-m)^2 (QPSK energy).
 * Identical construction to fam_scan.c (same SEG grid, same centering) so a
 * comb found here sits on the same bins mvp_scan already reports. */
static void feature_spectra(float* x, int nx, int SEG, double* c2, double* c4) {
    double* re=malloc(SEG*sizeof(double));
    double* im=malloc(SEG*sizeof(double));
    double* pwr=malloc(SEG*sizeof(double));
    double* acc2=calloc(SEG/2+1,sizeof(double));
    double* acc4=calloc(SEG/2+1,sizeof(double));
    double m2=0; { double s=0; int st=nx>200000?200000:nx; int i;
        for(i=0;i<st;i++){double v=x[i];s+=v*v;} m2=s/st; }
    int nseg=0, off, i;
    for(off=0; off+SEG<=nx; off+=SEG){
        double m=0;
        for(i=0;i<SEG;i++){double v=x[off+i];m+=v*v;} m/=SEG;
        for(i=0;i<SEG;i++){double v=x[off+i];re[i]=v*v-m;im[i]=0;}
        fft_mag2(re,im,SEG,pwr);
        for(i=0;i<=SEG/2;i++) acc2[i]+=pwr[i];
        for(i=0;i<SEG;i++){double v=x[off+i];double y=v*v-m2;re[i]=y*y;im[i]=0;}
        m=0; for(i=0;i<SEG;i++)m+=re[i]; m/=SEG;
        for(i=0;i<SEG;i++)re[i]-=m;
        fft_mag2(re,im,SEG,pwr);
        for(i=0;i<=SEG/2;i++) acc4[i]+=pwr[i];
        nseg++;
    }
    if (nseg<1) nseg=1;
    for(i=0;i<=SEG/2;i++){ acc2[i]/=nseg; acc4[i]/=nseg; }
    double med2=median(acc2+2,SEG/2-1), med4=median(acc4+2,SEG/2-1);
    if (med2<=0) med2=1; if (med4<=0) med4=1;
    for(i=0;i<=SEG/2;i++){ c2[i]=acc2[i]/med2; c4[i]=acc4[i]/med4; }
    free(re);free(im);free(pwr);free(acc2);free(acc4);
}

typedef struct { int bin; double ratio; } peak_t;
static int cmp_peak(const void*a,const void*b){
    double x=((peak_t*)b)->ratio - ((peak_t*)a)->ratio;
    return (x>0)-(x<0);
}

/* top-15 peaks over max(Y2,Y4), non-max suppression +-3 bins (as fam_scan). */
static int top_peaks(double* c2, double* c4, int SEG, peak_t* out, int want) {
    int B=SEG/2, i, k, got=0;
    int* taken=calloc(B+1,sizeof(int));
    for(k=0;k<want;k++){
        int bi=-1; double bv=0;
        for(i=2;i<=B;i++){
            if(taken[i]) continue;
            double v = c2[i]>c4[i]?c2[i]:c4[i];
            if(v>bv){bv=v;bi=i;}
        }
        if(bi<0) break;
        for(i=bi-3;i<=bi+3;i++) if(i>=0&&i<=B) taken[i]=1;
        out[got].bin=bi; out[got].ratio=bv; got++;
    }
    free(taken);
    return got;
}

/* THE COMB RULE: >=3 distinct peaks on harmonics m*b0 (m=1..8, +-1 bin),
 * mean member ratio >= 6.0. Returns member count; sets *score, *f0bin. */
static int comb_rule(peak_t* pk, int npk, int B, double* score, int* f0bin) {
    int b0, m, i, best_n=0; double best_s=0; int best_b=0;
    for(b0=2;b0<=128;b0++){
        double tot=0; int n=0;
        for(m=1;m<=8;m++){
            int tgt=m*b0;
            if(tgt>B) break;
            int lo=tgt-1<2?2:tgt-1, hi=tgt+1>B?B:tgt+1, hit=-1;
            for(i=0;i<npk;i++)
                if(pk[i].bin>=lo&&pk[i].bin<=hi){hit=i;break;}
            if(hit>=0){tot+=pk[hit].ratio;n++;}
        }
        double s = n? tot/n : 0;
        if(n>=3 && (n>best_n || (n==best_n && s>best_s))){
            best_n=n; best_s=s; best_b=b0;
        }
    }
    *score=best_s; *f0bin=best_b;
    return (best_n>=3 && best_s>=6.0) ? best_n : 0;
}

/* Non-Gaussianity: excess kurtosis + 4-sigma tail excess vs Gaussian. */
static void nongauss_stats(float* x, int nx, double* kurt, double* tailx) {
    double m=0; int i;
    int st = nx>524288?524288:nx;
    for(i=0;i<st;i++) m+=x[i];
    m/=st;
    double v=0; for(i=0;i<st;i++){double d=x[i]-m;v+=d*d;}
    v/=st; double sd=sqrt(v); if(sd<=0){*kurt=0;*tailx=0;return;}
    double k=0; long tail=0;
    for(i=0;i<st;i++){double z=(x[i]-m)/sd;k+=z*z*z*z;if(z>4||z<-4)tail++;}
    *kurt=k/st-3.0;
    *tailx=((double)tail/st)/6.33e-5;
}

/* Line-density (THICKET) count: bins where max(Y2,Y4) exceeds 10x.
 * WHY: a dense intermod thicket (measured: 60+ lines at 20-80x in
 * TRAPPIST OFF b1/ch57 and Kepler ON b21/ch52, same backend family)
 * games the comb rule - with a line in every bin, 3+ accidental harmonic
 * alignments are near-certain and the mean member ratio stays high
 * (measured comb scores 17-60 on pure thicket). A real baud comb puts
 * energy in a FEW bins (members + sidelobes, <15); a thicket lights up
 * dozens. The comb rule cannot tell them apart; this count can. */
#define THICKET_RATIO 10.0
#define THICKET_MIN 25
static int thicket_count(double* c2, double* c4, int SEG) {
    int n = 0, i;
    for (i = 2; i <= SEG / 2; i++) {
        double v = c2[i] > c4[i] ? c2[i] : c4[i];
        if (v >= THICKET_RATIO) n++;
    }
    return n;
}

static int analyze(float* x, int nx, double fs, int SEG,
                   int* members, double* score, double* f0,
                   int* nongauss, double* kurt, double* tailx,
                   int* nlines10) {
    double* c2=malloc((SEG/2+1)*sizeof(double));
    double* c4=malloc((SEG/2+1)*sizeof(double));
    feature_spectra(x,nx,SEG,c2,c4);
    peak_t pk[15];
    int npk=top_peaks(c2,c4,SEG,pk,15);
    int f0b=0; double s=0;
    int n = comb_rule(pk,npk,SEG/2,&s,&f0b);
    *members=n; *score=s; *f0 = n? f0b*fs/SEG : 0;
    nongauss_stats(x,nx,kurt,tailx);
    *nongauss = (*kurt>1.0 || *tailx>3.0) ? 1 : 0;
    *nlines10 = thicket_count(c2,c4,SEG);
    free(c2);free(c4);
    return (n>0)?1:0;
}

/* Deterministic PRNG (xorshift64*) so --selftest is exactly reproducible. */
static uint64_t rng_s = 0x123456789abcdefULL;
static double rnorm(void){
    /* Box-Muller from xorshift uniform */
    rng_s ^= rng_s>>12; rng_s ^= rng_s<<25; rng_s ^= rng_s>>27;
    double u1=((rng_s*0x2545F4914F6CDD1DULL)>>11)*1.1102230246251565e-16+1e-300;
    rng_s ^= rng_s>>12; rng_s ^= rng_s<<25; rng_s ^= rng_s>>27;
    double u2=((rng_s*0x2545F4914F6CDD1DULL)>>11)*1.1102230246251565e-16;
    return sqrt(-2.0*log(u1))*cos(2*M_PI*u2);
}

static int selftest(void) {
    const int N=524288, SEG=32768;
    const double fs=2929687.5;
    float* x=malloc(N*sizeof(float));
    int i, ok=1, members, nongauss, nl10; double score,f0,kurt,tailx,comb;
    /* 1. noise only: Gaussian sigma 14 (8-bit-like). comb=0, nongauss=0. */
    rng_s=0x123456789abcdefULL;
    for(i=0;i<N;i++) x[i]=(float)(14.0*rnorm());
    comb=analyze(x,N,fs,SEG,&members,&score,&f0,&nongauss,&kurt,&tailx,&nl10);
    printf("[selftest] noise: comb=%d(score=%.2f) nongauss=%d(kurt=%.2f tailx=%.2f) lines10=%d %s\n",
           comb!=0,score,nongauss,kurt,tailx,nl10,
           (!comb&&!nongauss&&nl10<THICKET_MIN)?"PASS":"FAIL");
    ok = ok && !comb && !nongauss && nl10<THICKET_MIN;
    /* 2. AM comb at 1431.3 Hz (=16 FAM bins: exact grid harmonic family).
     * Envelope modulation -> Y2 lines at f0,2f0,... -> comb must fire. */
    rng_s=0xabcdef123456789ULL;
    for(i=0;i<N;i++){
        double t=i/fs;
        double env=1.0+0.6*(sin(2*M_PI*1431.3*t)>0?1.0:-1.0);
        x[i]=(float)(14.0*rnorm()*env);
    }
    comb=analyze(x,N,fs,SEG,&members,&score,&f0,&nongauss,&kurt,&tailx,&nl10);
    {
        /* a REAL baud comb lights a few bins: the fence must stay down */
        int f0ok = comb && fabs(f0-1431.3)<120.0 && nl10<THICKET_MIN;
        printf("[selftest] am-comb1431: comb=%d(score=%.2f f0=%.0f members=%d) lines10=%d %s\n",
               comb!=0,score,f0,members,nl10, f0ok?"PASS":"FAIL");
        ok = ok && f0ok;
    }
    /* 3. sparse impulses (20-sigma, 40 hits): nongauss=1, comb=0. */
    rng_s=0x987654321abcdefULL;
    for(i=0;i<N;i++) x[i]=(float)(14.0*rnorm());
    for(i=0;i<40;i++) x[(i*13107+11)%N]=(float)(20.0*14.0);
    comb=analyze(x,N,fs,SEG,&members,&score,&f0,&nongauss,&kurt,&tailx,&nl10);
    printf("[selftest] impulses: comb=%d nongauss=%d(kurt=%.2f tailx=%.2f) %s\n",
           comb!=0,nongauss,kurt,tailx,
           (!comb&&nongauss)?"PASS":"FAIL");
    ok = ok && !comb && nongauss;
    /* 4. single line WITHOUT baud (the ch0-line case): comb must NOT fire.
     * Calibrated proxy: A=4 vs noise 14 gives a Y2 single line ~5x (a real
     * standing line: direct-spectrum visible, cyclo-quiet, fam 2-5x) whose
     * sinc sidelobes sit below the floor. A 200-amplitude coherent tone is
     * NOT this class: its sidelobes + x^2 cross-terms genuinely imprint
     * harmonic structure (measured: fires), as would any saturating carrier. */
    rng_s=0x1111111111111111ULL;
    for(i=0;i<N;i++){
        double t=i/fs;
        x[i]=(float)(14.0*rnorm()+4.0*sin(2*M_PI*5000.0*t));
    }
    comb=analyze(x,N,fs,SEG,&members,&score,&f0,&nongauss,&kurt,&tailx,&nl10);
    printf("[selftest] single-tone: comb=%d(score=%.2f members=%d) lines10=%d %s\n",
           comb!=0,score,members,nl10, (!comb&&nl10<THICKET_MIN)?"PASS":"FAIL");
    ok = ok && !comb && nl10<THICKET_MIN;
    /* 5. intermod thicket: 60 tones ~80 Hz apart (measured: TRAPPIST OFF
     * b1/ch57 + Kepler ON b21/ch52 carry 60+ lines at 20-80x spaced ~6 Hz
     * in Y2). A DENSE quasi-regular forest games the comb rule: with a
     * line in nearly every bin, accidental harmonic alignments are certain
     * and the mean member ratio stays high (measured comb scores 17-60 on
     * pure thicket). nlines10 MUST catch what the comb rule cannot. */
    rng_s=0x5555555555555555ULL;
    for(i=0;i<N;i++) x[i]=(float)(14.0*rnorm());
    for(int k=0;k<60;k++){
        rng_s ^= rng_s>>12; rng_s ^= rng_s<<25; rng_s ^= rng_s>>27;
        double fk = 300.0 + k*80.0 + ((rng_s>>11)%4000)/100.0 - 20.0;
        double ph = ((rng_s>>23)%628)/100.0;
        for(i=0;i<N;i++){ double t=i/fs; x[i]+=(float)(10.0*sin(2*M_PI*fk*t+ph)); }
    }
    comb=analyze(x,N,fs,SEG,&members,&score,&f0,&nongauss,&kurt,&tailx,&nl10);
    printf("[selftest] thicket60: comb=%d(score=%.2f members=%d) thicket=%d %s\n",
           comb!=0,score,members,nl10>=THICKET_MIN,
           (comb&&nl10>=THICKET_MIN)?"PASS":"FAIL");
    ok = ok && comb && nl10>=THICKET_MIN;
    free(x);
    printf("[selftest] %s\n", ok?"ALL PASS":"FAILURES PRESENT");
    return ok?0:1;
}

int main(int argc,char**argv){
    if(argc>1&&!strcmp(argv[1],"--selftest")) return selftest();
    if(argc<2){fprintf(stderr,"usage: %s <in.f32> [fs] [seg] | --selftest\n",argv[0]);return 2;}
    double fs=argc>2?atof(argv[2]):2929687.5;
    int SEG=argc>3?atoi(argv[3]):32768;
    FILE*f=fopen(argv[1],"rb"); if(!f){perror("fopen");return 1;}
    fseek(f,0,SEEK_END); long nb=ftell(f); fseek(f,0,SEEK_SET);
    int nx=(int)(nb/4);
    float* x=malloc(nb); if(fread(x,1,nb,f)!=(size_t)nb){perror("fread");return 1;} fclose(f);
    int members,nongauss,nl10; double score,f0,kurt,tailx;
    int c=analyze(x,nx,fs,SEG,&members,&score,&f0,&nongauss,&kurt,&tailx,&nl10);
    printf("comb_peaks=15 segs=%d\n", nx/SEG);
    printf("RESULT comb=%d comb_score=%.2f f0_hz=%.1f members=%d "
           "nongauss=%d kurt=%.2f tailx=%.2f nlines10=%d thicket=%d\n",
           c,score,f0,members,nongauss,kurt,tailx,nl10,
           (nl10>=THICKET_MIN)?1:0);
    free(x);
    return 0;
}
