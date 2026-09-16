#include "gimbal.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
static int send(Gimbal *g,unsigned seq,int pan,int tilt,unsigned now) {
    char body[48],line[64];
    snprintf(body,sizeof(body),"P1,%u,%d,%d",seq,pan,tilt);
    snprintf(line,sizeof(line),"%s*%04X",body,gimbal_crc(body,strlen(body)));
    return gimbal_packet(g,line,now);
}
int main(void) {
    Gimbal g; gimbal_init(&g);
    assert(gimbal_crc("123456789",9)==0x29b1);
    assert(!gimbal_packet(&g,"P1,1,0,0*0000",0));
    assert(!send(&g,1,6100,0,0));
    assert(send(&g,1,4500,-3000,0));
    assert(!send(&g,1,0,0,1));
    float old=0;
    for(unsigned t=10;t<=3000;t+=10) {
        if(t%100==0) assert(send(&g,t/100+1,4500,-3000,t));
        gimbal_tick(&g,t,.01f);
        assert(g.pan>=old && g.pan<=45); assert(fabsf(g.pan_velocity)<=40.01f); old=g.pan;
    }
    assert(fabsf(g.pan-45)<.01f); assert(fabsf(g.tilt+30)<.01f);
    assert(send(&g,32,-6000,4500,3010));
    gimbal_tick(&g,4000,.01f); assert(g.pan==45 && g.pan_velocity==0);
    assert(send(&g,0,0,0,4010));
    assert(gimbal_pulse(-60)==1000 && gimbal_pulse(60)==2000);
    assert(gimbal_pulse(NAN)==1500);
    puts("firmware core tests passed");
}
