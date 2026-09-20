/* sy_io.h — SetiYeti vendored fast I/O helpers (single header, C99).
 * 64-bit file offsets on Windows (_fseeki64) + POSIX fseeko, whole-file
 * .f32 loader with size check, result-line printer. Keeps the hot loop clean.
 */
#ifndef SY_IO_H
#define SY_IO_H
#include <stdio.h>
#include <stdlib.h>
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
static inline float *sy_load_f32(const char *path, int *nx_out){
    FILE *f=fopen(path,"rb"); if(!f) return 0;
    if(SY_FSEEK(f,0,SEEK_END)!=0){fclose(f);return 0;}
    sy_off_t nb=(sy_off_t)SY_FTELL(f); SY_FSEEK(f,0,SEEK_SET);
    if(nb<=0||nb%4){fclose(f);return 0;}
    int nx=(int)(nb/4); float *x=(float*)malloc((size_t)nb);
    if(!x){fclose(f);return 0;}
    if(fread(x,1,(size_t)nb,f)!=(size_t)nb){free(x);fclose(f);return 0;}
    fclose(f); if(nx_out)*nx_out=nx; return x;
}
#endif
