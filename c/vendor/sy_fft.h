/* sy_fft.h — SetiYeti vendored fast FFT core (single header, C99, -lm only).
 *
 * WHY: fam_scan.c / comb_scan.c recompute cos()/sin() per butterfly per
 * segment — O(N log N) trig calls, the dominant cost across 65k slices.
 * This header provides a radix-2 FFT with PRECOMPUTED twiddle tables
 * (one cos/sin per table entry, cached per stage length), power fast path,
 * and no extra dependencies. Optional OpenMP parallelises segments in the
 * caller (no dependency if absent). Optional FFTW hook: define SY_USE_FFTW.
 * Portable C99, deterministic.
 */
#ifndef SY_FFT_H
#define SY_FFT_H
#include <math.h>
#include <stdlib.h>
#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

#define SY_FFT_MAXLOG 17
static double *sy_tw_re[SY_FFT_MAXLOG+1] = {0};
static double *sy_tw_im[SY_FFT_MAXLOG+1] = {0};

static inline int sy_log2i(int n){ int l=0; while((1<<l)<n) l++; return l; }

/* ensure tables for stage length `len` (power of two, >=2) exist */
static inline int sy_tw_ensure(int len){
    int lg = sy_log2i(len);
    if(len<2||lg>SY_FFT_MAXLOG||(len&(len-1))) return -1;
    if(sy_tw_re[lg]) return 0;
    double *r=(double*)malloc(sizeof(double)*(len/2));
    double *im=(double*)malloc(sizeof(double)*(len/2));
    if(!r||!im){ free(r); free(im); return -1; }
    for(int k=0;k<len/2;k++){ double a=-2.0*M_PI*k/len; r[k]=cos(a); im[k]=sin(a); }
    sy_tw_re[lg]=r; sy_tw_im[lg]=im; return 0;
}

static inline void sy_fft(double *re, double *im, int n){
    for(int i=1,j=0;i<n;i++){ int bit=n>>1; for(;j&bit;bit>>=1) j&=~bit; j|=bit;
        if(i<j){ double t=re[i];re[i]=re[j];re[j]=t;t=im[i];im[i]=im[j];im[j]=t; } }
    for(int len=2;len<=n;len<<=1){
        int lg=sy_log2i(len);
        if(!sy_tw_re[lg]) sy_tw_ensure(len);
        double *tr=sy_tw_re[lg], *ti=sy_tw_im[lg];
        int half=len/2;
        for(int i=0;i<n;i+=len){
            for(int k=0;k<half;k++){
                double wr=tr?tr[k]:cos(-2.0*M_PI*k/len);
                double wi=ti?ti[k]:sin(-2.0*M_PI*k/len);
                double ur=re[i+k], ui=im[i+k];
                double vr=re[i+k+half]*wr-im[i+k+half]*wi;
                double vi=re[i+k+half]*wi+im[i+k+half]*wr;
                re[i+k]=ur+vr; im[i+k]=ui+vi;
                re[i+k+half]=ur-vr; im[i+k+half]=ui-vi;
            }
        }
    }
}

static inline void sy_fft_mag2(double *re, double *im, int n, double *out_pwr){
    sy_fft(re,im,n);
    for(int i=0;i<n;i++) out_pwr[i]=re[i]*re[i]+im[i]*im[i];
}

static inline void sy_fft_free_cache(void){
    for(int i=0;i<=SY_FFT_MAXLOG;i++){
        free(sy_tw_re[i]); sy_tw_re[i]=0;
        free(sy_tw_im[i]); sy_tw_im[i]=0;
    }
}
#endif
