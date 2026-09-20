
#include <stdio.h>
#include "vendor/sy_stats.h"
int main(void){
    /* deterministic corpus: arithmetic, plateaus, spikes, bit patterns */
    double t[][8] = {
        {5,1,4,2,8,0,0,0}, {7,7,7,7,7,0,0,0}, {1,2,3,4,5,6,7,8},
        {8,7,6,5,4,3,2,1}, {0,0,0,100,0,0,0,0}, {-3,-1,-1,0,2,2,9,9},
    };
    int ns[] = {5,4,8,8,7,8};
    for(int c=0;c<6;c++){
        double m = sy_median(t[c], ns[c]);
        printf("%.6f\n", m);
    }
    return 0;
}
