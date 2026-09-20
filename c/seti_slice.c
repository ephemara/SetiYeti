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
    for (int i = 4; i < argc; i++) {
        if (!strcmp(argv[i],"--pol") && i+1 < argc) pol = atoi(argv[++i]);
        else if (!strcmp(argv[i],"--start") && i+1 < argc) start_block = atol(argv[++i]);
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
    long filesize = 0;
    { long cur = ftell(f); if (fseek(f,0,SEEK_END)==0) filesize = ftell(f); fseek(f,cur,SEEK_SET); }

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

    while (nblocks < start_block + max_blocks) {
        long blk_off = ftell(f);
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
        long blocsize=0;
        char* p=strstr(cards_txt,"BLOCSIZE");
        if (p) blocsize=atol(p+9);
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
        long hlen = 0;
        {
            static const char MAGIC[16] = "BACKEND = 'GUPPI";
            long probe = blk_off + (long)cards*80 + blocsize;
            if (probe < blk_off) probe = blk_off;
            static uint8_t win[16384];
            if (fseek(f, probe, SEEK_SET)==0) {
                size_t got = fread(win,1,sizeof(win),f);
                for (size_t i=0; i+16<=got; i++) {
                    if (!memcmp(win+i, MAGIC, 16)) {
                        long next = probe + (long)i;
                        hlen = (next - blk_off) - blocsize;
                        break;
                    }
                }
            }
            if (hlen <= 0 || hlen > 65536) hlen = 0;
            if (hlen == 0 && filesize > blocsize) {
                long c = filesize - blocsize;   // exact for a single complete block
                if (c > 0 && c <= 65536) hlen = c;
            }
            if (hlen == 0)
                hlen = (long)cards*80 + ((256 - ((long)cards*80)%256)%256);
        }
        long data_off = blk_off + hlen;
        fseek(f, data_off, SEEK_SET);
        long bidx = nblocks; // blocks read so far (including skipped)
        nblocks++;
        if (bidx < start_block || bidx >= start_block + max_blocks) {
            fseek(f, data_off + blocsize, SEEK_SET); // skip without reading
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
        long bpt = nchan*npol*nbits/8;  // bytes per time tick
        if (bpt <= 0) { fprintf(stderr,"bad geometry block %d\n",nblocks); break; }
        data=(uint8_t*)malloc(blocsize);
        if (fread(data,1,blocsize,f)!=(size_t)blocsize) { free(data); break; }
        long ntime = blocsize/bpt;
        int is2 = (nbits==2);
        int bmin=127, bmax=-128;
        for (long t=0;t<ntime;t++) {
            float v; int code=0;
            if (is2) {
                uint8_t b = data[t*bpt+chan];
                code=(b>>shift)&3;
                v=LUT[code];
            } else {
                int8_t sb = (int8_t)data[t*bpt+chan*npol+pol];
                v=(float)sb;
                if(sb<bmin)bmin=sb; if(sb>bmax)bmax=sb;
            }
            fwrite(&v,4,1,o);
            sum+=v; sumsq+=v*v; hist[code]++;
            if (ac_fill<AC_N) acbuf[ac_fill++]=v;
            total_samples++;
        }
        free(data);
        nblocks++;
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
