// vm_sandbox.c - SetiYeti universal execution tester (dependency-free C99)
// Feeds candidate bitstreams into minimal universal machines with cycle budget,
// scores structured vs random via SUBLEQ locality + Golay G24 syndrome test.
// Usage: vm_sandbox <bits.bin>  (raw bytes, MSB-first bits)  [max_cycles]
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

// --- SUBLEQ OISC: mem[] of int32, triplets [a,b,c] ---
int run_subleq(int32_t* mem, int n, int budget, long* out_writes, double* out_locality) {
    int32_t pc=0; int steps=0; long writes=0; long local=0; int32_t last_b=-1000000;
    while (steps<budget) {
        if (pc<0||pc+2>=n) break;
        int32_t a=mem[pc], b=mem[pc+1], c=mem[pc+2];
        if (a<0||a>=n||b<0||b>=n) break; // halt on OOB (random junk halts fast)
        if (c<0||c>=n) break;
        mem[b]-=mem[a]; writes++;
        if (last_b>=0 && abs(b-last_b)<16) local++;
        last_b=b;
        pc = (mem[b]<=0)? c : pc+3;
        steps++;
        if (steps>10 && writes==0) break;
    }
    *out_writes=writes;
    *out_locality=writes? (double)local/(double)writes:0;
    return steps;
}

int main(int argc,char**argv){
    if(argc<2){fprintf(stderr,"usage: %s <bits.bin> [budget]\n",argv[0]);return 2;}
    int budget=argc>2?atoi(argv[2]):200000;
    FILE*f=fopen(argv[1],"rb"); if(!f){perror("fopen");return 1;}
    fseek(f,0,SEEK_END); long nb=ftell(f); fseek(f,0,SEEK_SET);
    uint8_t*buf=(uint8_t*)malloc(nb); fread(buf,1,nb,f); fclose(f);
    // entropy gate: constant/low-entropy streams (zero-runs, rails) pass syndrome
    // trivially (all-zero word, zero syndrome). No verdict without information.
    {
        long ones=0; int seen[256]={0}; int distinct=0;
        for(long i=0;i<nb;i++){ unsigned b=buf[i];
            ones+=__builtin_popcount(b);
            if(!seen[b]){seen[b]=1;distinct++;} }
        double frac=(double)ones/(double)(nb*8);
        if(frac<0.30||frac>0.70||distinct<16){
            printf("entropy_gate=BLOCK (ones=%.3f distinct=%d): no information, no verdict\n",
                   frac,distinct);
            free(buf); return 0;
        }
        printf("entropy_gate=pass (ones=%.3f distinct=%d)\n",frac,distinct);
    }
    // pack bits MSB-first into int32 mem (8 bits -> accumulate, need 32-bit words)
    long nbits=nb*8L;
    int nwords=(int)((nbits+31)/32);
    if(nwords<16) nwords=16;
    if(nwords>8192) nwords=8192; // cap sandbox 32KB
    int32_t*mem=(int32_t*)calloc(nwords,4);
    for(long i=0;i<(long)nwords*32 && i<nbits;i++){
        int byte=buf[i>>3]; int bit=(byte>>(7-(i&7)))&1;
        mem[i>>5]|=(bit<<(31-(i&31)));
    }
    // mask to small address space so random junk halts but structured loops run
    for(int i=0;i<nwords;i++){ mem[i]=abs(mem[i])%nwords; }
    long writes=0; double loc=0;
    int steps=run_subleq(mem,nwords,budget,&writes,&loc);
    // compressibility proxy: count distinct values touched (structured = few hot addrs)
    printf("words=%d steps=%d writes=%ld locality=%.3f\n",nwords,steps,writes,loc);
    double score = (writes>100?1:0)*0.4 + (loc>0.3?1:0)*0.3 + (steps>5000&&steps<budget?1:0)*0.3;
    printf("verdict_score=%.2f %s\n",score, score>=0.6?"CANDIDATE-structure":"noise-like");
    // --- Golay G23 cyclic syndrome (core of extended G24): g=x^11+x^9+x^7+x^6+x^5+x+1 ---
    // Random baseline: P(syndrome wt<=2) = 67/2048 ~= 3.27%, wt<=3 ~= 11.33%.
    // Engineered G24 stream at correct alignment: hit rate >> baseline.
    {
        const uint32_t G = 0xAE3; // 12-bit generator (x^11..x^0)
        long nbits2 = nbits > 200000 ? 200000 : nbits; // cap for speed
        double best2=0,best3=0; int besta=0;
        for(int align=0;align<23;align++){
            long wins=0,h2=0,h3=0;
            for(long w=align; w+23<=nbits2; w+=23){
                // build 23-bit word MSB-first
                uint32_t wd=0;
                for(int i=0;i<23;i++){
                    long bi=w+i; int byte=buf[bi>>3]; int bit=(byte>>(7-(bi&7)))&1;
                    wd=(wd<<1)|bit;
                }
                // poly mod: divide 23-bit word by 12-bit generator
                uint32_t r=wd;
                for(int k=22;k>=11;k--) if(r&(1u<<k)) r^=(G<<(k-11));
                int wt=__builtin_popcount(r&0x7FF);
                wins++; if(wt<=2)h2++; if(wt<=3)h3++;
            }
            if(wins==0) continue;
            double f2=(double)h2/(double)wins, f3=(double)h3/(double)wins;
            if(f2>best2){best2=f2;best3=f3;besta=align;}
        }
        printf("golay best_align=%d win_rate_wt<=2=%.4f (rand~0.0327) wt<=3=%.4f (rand~0.1133)\n",besta,best2,best3);
        int golay_hit = (best2>0.06)?1:0; // ~2x random at strict threshold
        printf("golay_flag=%s\n",golay_hit?"CANDIDATE-golay":"noise-like");
        double combined = score*0.6 + (golay_hit?0.4:0.0);
        if (golay_hit && combined < 0.75) combined = 0.75; // engineered codeword alone is enough
        printf("combined=%.2f %s\n",combined, combined>=0.6?"CANDIDATE":(golay_hit||score>=0.6?"WATCH":"noise-like"));
    }
    free(buf); free(mem);
    return 0;
}
