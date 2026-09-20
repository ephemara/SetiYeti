// seti_slice.c - SetiYeti fast GUPPI slicer (portable C99, no deps)
// Layouts validated:
//   2-bit (blc2 M31): NCHAN=64, NPOL=4 reals packed 4/byte.
//     byte[t*64+chan] bits: [1:0]=pol0 [3:2]=pol1 [5:4]=pol2 [7:6]=pol3
//     codes: 00->-3.3359 01->-1.0 10->+1.0 11->+3.3359
//   8-bit (blc4 HIP): NCHAN=64, NPOL=4 int8 reals, 1 byte each.
//     byte[t*256+chan*4+pol] as signed int8 -> float
// NBITS/NPOL/NCHAN parsed per-block from header (assumed constant per file).
// Usage: seti_slice <raw> <chan 0-63> <out.f32> [max_blocks] [--pol 0..3]
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <math.h>

// ---------------------------------------------------------------------------
// 64-bit file offsets: on Windows (mingw) `long` is 32 bits and ftell/fseek
// wrap negative past 2 GiB. That silently misaligned every full-length scan
// of a 17 GB GUPPI file: headers 0-15 sit below the 2 GiB line and parse fine,
// header 16 is the first past it and the probe math overflows, landing the
// reader one block behind -> "no END". 1 GiB PART files never crossed the
// line, so this hid for months. Always use the 64-bit primitives for file
// positions; keep `long` for sample/slice counters only.
#ifdef _WIN32
  typedef long long sy_off_t;
  #define SY_FSEEK(f,o,w) _fseeki64((f),(o),(w))
  #define SY_FTELL(f)     _ftelli64((f))
#else
  #include <sys/types.h>
  typedef off_t sy_off_t;
  #define SY_FSEEK(f,o,w) fseeko((f),(o),(w))
  #define SY_FTELL(f)     ftello((f))
#endif

static const float LUT[4] = {-3.3359f, -1.0f, 1.0f, 3.3359f};

int main(int argc, char** argv) {
    if (argc < 4) {
        fprintf(stderr, "usage: %s <raw> <chan 0-63> <out.f32> [max_blocks] [--pol N]\n", argv[0]);
        return 2;
    }
    const char* rawpath = argv[1];
    int chan = atoi(argv[2]);
    const char* outpath = argv[3];
    int max_blocks = 1<<30;
    int pol = 0;
    long start_block = 0;
    int layout_force = -1;   /* -1 auto, 0=time-major, 1=chan/pol-blocked, 2=chan/pol-interleaved */
    for (int i = 4; i < argc; i++) {
        if (!strcmp(argv[i],"--pol") && i+1 < argc) pol = atoi(argv[++i]);
        else if (!strcmp(argv[i],"--start") && i+1 < argc) start_block = atol(argv[++i]);
        else if (!strcmp(argv[i],"--layout") && i+1 < argc) layout_force = atoi(argv[++i]);
        else max_blocks = atoi(argv[i]);
    }
    if (chan < 0 || chan > 63) { fprintf(stderr,"chan must be 0-63\n"); return 2; }
    if (pol < 0 || pol > 3) { fprintf(stderr,"pol must be 0-3\n"); return 2; }
    int shift = pol*2;

    FILE* f = fopen(rawpath,"rb");
    if (!f) { perror("fopen raw"); return 1; }
    FILE* o = fopen(outpath,"wb");
    if (!o) { perror("fopen out"); fclose(f); return 1; }

    // file size (needed to solve single-block header padding exactly)
    sy_off_t filesize = 0;
    { sy_off_t cur = SY_FTELL(f); if (SY_FSEEK(f,0,SEEK_END)==0) filesize = SY_FTELL(f); SY_FSEEK(f,cur,SEEK_SET); }

    uint8_t* hdrbuf = (uint8_t*)malloc(300*80);
    long total_samples = 0;
    double sum=0, sumsq=0;
    long hist[4]={0,0,0,0};
    int nblocks=0;
    // autocorr accumulators on first 200k samples
    const int AC_N = 200000;
    float* acbuf = (float*)malloc(sizeof(float)*AC_N);
    int ac_fill=0;

    const int lags[] = {1,7,64,256,1024,4096,16384};
    const int NLAG = sizeof(lags)/sizeof(lags[0]);

    // Block memory layout. Detected once from block 0, then reused:
    //   1 = channel-major  [chan][pol][time]  (BL/newer backends)
    //   0 = time-major     [time][chan][pol]  (classic GUPPI)
    //   -1 = not yet determined
    // NOTE: auto-detection needs a non-flat bandpass. Data that is dead, or a
    // receiver with a flat passband, cannot self-identify - use --layout 0|1.
    int layout = layout_force;

    while (nblocks < start_block + max_blocks) {
        sy_off_t blk_off = SY_FTELL(f);
        // read cards until END-aligned
        int cards=0;
        char cards_txt[300*80+1];
        memset(cards_txt,0,sizeof(cards_txt));
        int found_end=0;
        for (int i=0;i<300;i++) {
            uint8_t card[80];
            if (fread(card,1,80,f)!=80) goto done;
            cards++;
            memcpy(cards_txt+(i*80),card,80);
            if (card[0]=='E'&&card[1]=='N'&&card[2]=='D') { found_end=1; break; }
        }
        if (!found_end) { fprintf(stderr,"no END at block %d off %ld\n",nblocks,blk_off); break; }

        // BLOCSIZE first: needed to locate the next block's header.
        sy_off_t blocsize=0;
        char* p=strstr(cards_txt,"BLOCSIZE");
        if (p) blocsize=(sy_off_t)atoll(p+9);
        if (blocsize<=0) { fprintf(stderr,"bad BLOCSIZE block %d\n",nblocks); break; }

        // ---- header padding: DO NOT HARDCODE ----------------------------
        // GUPPI pads the card region to an alignment that VARIES by era:
        //   2016 blc2 (M31) : 2880-byte FITS blocks  (header 8640)
        //   2016+ GUPPI     : 256-byte alignment     (W75N 6400, TRAPPIST 6656)
        // Guessing wrong misaligns the payload *and* makes the next block's
        // header search land past its card region ("no END") -> only block 0
        // ever parses. So solve for it instead:
        //   1. probe forward from end-of-cards+blocsize for the next "BACKEND"
        //      card -> hlen = (next_header - blk_off) - blocsize
        //   2. single complete block -> hlen = filesize - blocsize
        //   3. otherwise fall back to 256 (modern GUPPI default)
        sy_off_t hlen = 0;
        {
            static const char MAGIC[] = "BACKEND = 'GUPPI";
            sy_off_t probe = blk_off + (sy_off_t)cards*80 + blocsize;
            static uint8_t win[16384];
            if (SY_FSEEK(f, probe, SEEK_SET)==0) {
                size_t got = fread(win,1,sizeof(win),f);
                for (size_t i=0; i+16<=got; i++) {
                    if (!memcmp(win+i, MAGIC, 16)) {
                        sy_off_t next = probe + (sy_off_t)i;
                        hlen = (next - blk_off) - blocsize;
                        break;
                    }
                }
            }
            if (hlen <= 0 || hlen > 65536) hlen = 0;
            if (hlen == 0 && filesize > blocsize) {
                sy_off_t c = filesize - blocsize;   // exact for a single complete block
                if (c > 0 && c <= 65536) hlen = c;
            }
            if (hlen == 0)
                hlen = (sy_off_t)cards*80 + ((256 - ((sy_off_t)cards*80)%256)%256);
        }
        sy_off_t data_off = blk_off + hlen;
        SY_FSEEK(f, data_off, SEEK_SET);
        long bidx = nblocks; // blocks read so far (including skipped)
        nblocks++;
        if (bidx < start_block || bidx >= start_block + max_blocks) {
            SY_FSEEK(f, data_off + blocsize, SEEK_SET); // skip without reading
            if (bidx >= start_block + max_blocks) break;
            continue;
        }
        uint8_t* data=NULL;
        // parse geometry from header (first block sets file geometry)
        long nchan=64, npol=4;
        int nbits=2;
        { char *q, *e;
          q=strstr(cards_txt,"OBSNCHAN"); if(!q) q=strstr(cards_txt,"NCHAN");
          if(q && (e=strchr(q,'='))) nchan=atol(e+1);
          q=strstr(cards_txt,"NPOL");
          if(q && (e=strchr(q,'='))) npol=atol(e+1);
          q=strstr(cards_txt,"NBITS");
          if(q && (e=strchr(q,'='))) nbits=atoi(e+1); }
        long bpt = nchan*npol*nbits/8;  // bytes per time tick (time-major layout)
        if (bpt <= 0) { fprintf(stderr,"bad geometry block %d\n",nblocks); break; }
        data=(uint8_t*)malloc(blocsize);
        if (fread(data,1,blocsize,f)!=(size_t)blocsize) { free(data); break; }
        int is2 = (nbits==2);

        // ---- memory-layout detection (once) ----------------------------
        // Three layouts are in the wild. Getting this wrong does NOT look like
        // garbage - it looks like white noise, because a wrong stride walks
        // linearly through the block and mixes every channel and polarization
        // together. It also manufactures strong spurious structure (a swept
        // bandpass sawtooth, and a line at exactly fs/4 from mixing the
        // interleaved polarizations) which detectors then report as signals.
        //
        //   0 = time-major      [time][chan][pol]   classic GUPPI
        //       off = t*(nchan*npol) + chan*npol + pol
        //   1 = chan-major, pol-blocked   [chan][pol][time]
        //       off = (chan*npol + pol)*seglen + t
        //   2 = chan-major, pol-INTERLEAVED  [chan][time][pol]
        //       off = chan*per_ch + t*npol + pol     <- 2017 BL/dibas files
        //
        // Discriminate by interleave autocorrelation (decisive, see below):
        //   interleaved [chan][time][pol] -> ac[1]~0 (adjacent bytes are
        //     different pols, near-independent feeds) but ac[npol] large
        //     (bytes npol apart are the same pol, correlated by bandpass)
        //   pol-blocked [chan][pol][time] -> adjacent bytes are the same pol,
        //     so ac[1] carries the correlation and ac[npol] <= ac[1]
        // The previous phase-RMS test sat on a coin-flip threshold (healthy
        // A/B vs CR/CI rms ratio 1.199 against a >1.2 cutoff) and flipped
        // block to block, silently mixing two different reads in one scan.
        if (layout < 0) {
            if (nbits != 8) {
                layout = 0;                     // 2-bit path keeps classic layout
            } else {
                double ac1=0, acN=0, den=0;
                const int probe_ch[4] = {16, 28, 40, 52};   // mid-band, avoid edges
                long per_c = blocsize/nchan;
                for (int k=0;k<4;k++) {
                    int c = probe_ch[k];
                    const uint8_t* p2 = data + (long)c*per_c;
                    long n = per_c; if (n > 262144) n = 262144;  // 256k samples plenty
                    if (n < 2*(long)npol+2) continue;
                    double m=0; for (long i=0;i<n;i++) m += (int8_t)p2[i];
                    m /= n;
                    for (long i=0;i<n;i++){ double v=(int8_t)p2[i]-m; den += v*v; }
                    for (long i=0;i+1<n;i++)    ac1 += ((int8_t)p2[i]-m)*((int8_t)p2[i+1]-m);
                    for (long i=0;i+npol<n;i++) acN += ((int8_t)p2[i]-m)*((int8_t)p2[i+npol]-m);
                }
                if (den>0) { ac1/=den; acN/=den; }
                if (fabs(ac1) > 0.005 || fabs(acN) > 0.005) {
                    layout = (fabs(acN) > 1.5*fabs(ac1)) ? 2 : 1;
                    fprintf(stderr, "(layout probe: ac1=%.4f ac%d=%.4f -> %s)\n",
                            ac1, (int)npol, acN,
                            layout==2 ? "interleaved" : "pol-blocked");
                } else {
                    layout = 2;    // both ~0: white/dead data, default modern era
                }
            }
            fprintf(stderr, "(layout: %s)\n",
                    layout==2 ? "chan-major, pol-interleaved [chan][time][pol]"
                  : layout==1 ? "chan-major, pol-blocked [chan][pol][time]"
                              : "time-major [time][chan][pol]");
        }

        long per_ch = blocsize/nchan;
        long ntime;
        if (layout==2)      ntime = per_ch/npol;
        else if (layout==1) ntime = blocsize/(long)(nchan*npol);
        else                ntime = blocsize/bpt;

        int bmin=127, bmax=-128;
        for (long t=0;t<ntime;t++) {
            float v; int code=0;
            if (is2) {
                uint8_t b = layout ? data[(long)(chan*npol+pol)*(blocsize/(nchan*npol)) + t]
                                   : data[t*bpt+chan];
                code=(b>>shift)&3;
                v=LUT[code];
            } else {
                long off;
                if (layout==2)      off = (long)chan*per_ch + t*npol + pol;
                else if (layout==1) off = (long)(chan*npol+pol)*(blocsize/(long)(nchan*npol)) + t;
                else                off = t*bpt + chan*npol + pol;
                int8_t sb = (int8_t)data[off];
                v=(float)sb;
                if (sb<bmin) bmin=sb;
                if (sb>bmax) bmax=sb;
            }
            fwrite(&v,4,1,o);
            sum+=v; sumsq+=v*v; hist[code]++;
            if (ac_fill<AC_N) acbuf[ac_fill++]=v;
            total_samples++;
        }
        free(data);
        // NOTE: do NOT increment nblocks again here. The loop already increments
        // it once per block at the top; a second increment made `--blocks N`
        // read only ~N/2 blocks (7 requested -> 4 read, silently).
        if (!is2) printf("(8-bit range %d..%d)\n",bmin,bmax);
    }
done:
    fclose(f); fclose(o);
    double mean = total_samples? sum/total_samples:0;
    double var = total_samples? sumsq/total_samples-mean*mean:0;
    printf("blocks=%d samples=%ld chan=%d pol=%d\n",nblocks,total_samples,chan,pol);
    printf("mean=%.4f rms=%.4f hist00=%ld hist01=%ld hist10=%ld hist11=%ld\n",
        mean,sqrt(var),hist[0],hist[1],hist[2],hist[3]);
    // autocorr on acbuf
    int n=ac_fill;
    if (n>10000) {
        double e=0; for(int i=0;i<n;i++) e+=acbuf[i]*acbuf[i];
        for(int li=0;li<NLAG;li++){
            int L=lags[li]; double c=0;
            for(int i=0;i+ L<n;i++) c+=acbuf[i]*acbuf[i+L];
            printf("Rxx lag %-6d norm=%.5f\n",L,c/e);
        }
    }
    free(hdrbuf); free(acbuf);
    return 0;
}
