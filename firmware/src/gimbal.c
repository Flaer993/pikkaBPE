#include "gimbal.h"
#include <math.h>
#include <stdio.h>
#include <string.h>

/* Conservative travel until this particular MG995 pair is calibrated. */
#define PAN_LIMIT 60.0f
#define TILT_LIMIT 45.0f
#define MAX_VELOCITY 40.0f
#define ACCELERATION 80.0f
#define WATCHDOG_MS 600u

void gimbal_init(Gimbal *g) { memset(g,0,sizeof(*g)); }
uint16_t gimbal_crc(const char *data,size_t length) {
    uint16_t crc=0xffff;
    for(size_t i=0;i<length;i++) {
        crc^=(uint16_t)((uint8_t)data[i])<<8;
        for(int j=0;j<8;j++) crc=(uint16_t)((crc&0x8000)?(crc<<1)^0x1021:crc<<1);
    }
    return crc;
}

int gimbal_packet(Gimbal *g,const char *line,uint32_t now_ms) {
    size_t length=strlen(line);
    if(length<12 || length>63) return 0;
    const char *star=strchr(line,'*');
    if(!star || strlen(star+1)!=4) return 0;
    unsigned crc=0;
    for(int i=1;i<=4;i++) {
        char c=star[i]; unsigned v;
        if(c>='0'&&c<='9') v=(unsigned)(c-'0');
        else if(c>='A'&&c<='F') v=(unsigned)(c-'A'+10);
        else return 0;
        crc=(crc<<4)|v;
    }
    if(gimbal_crc(line,(size_t)(star-line))!=crc) return 0;
    unsigned sequence; int pan,tilt,n=0;
    if(sscanf(line,"P1,%5u,%6d,%6d%n",&sequence,&pan,&tilt,&n)!=3 || line+n!=star) return 0;
    if(sequence>65535 || pan<-6000 || pan>6000 || tilt<-4500 || tilt>4500) return 0;
    /* Host may reconnect with a reset sequence only after link watchdog expiry. */
    if(g->have_sequence && (uint32_t)(now_ms-g->last_packet)<=WATCHDOG_MS) {
        uint16_t delta=(uint16_t)((uint16_t)sequence-g->sequence);
        if(delta==0 || delta>=32768) return 0;
    }
    g->sequence=(uint16_t)sequence; g->have_sequence=1;
    g->target_pan=pan/100.0f; g->target_tilt=tilt/100.0f;
    g->last_packet=now_ms; g->enabled=1;
    return 1;
}

static void axis(float *position,float *velocity,float target,float dt) {
    float distance=target-*position;
    float wanted=fminf(MAX_VELOCITY,sqrtf(2*ACCELERATION*fabsf(distance)));
    if(distance<0) wanted=-wanted;
    float change=fmaxf(-ACCELERATION*dt,fminf(ACCELERATION*dt,wanted-*velocity));
    *velocity+=change;
    float step=*velocity*dt;
    if((distance>=0 && step>=distance)||(distance<0 && step<=distance)) { *position=target; *velocity=0; }
    else *position+=step;
}

void gimbal_tick(Gimbal *g,uint32_t now_ms,float dt) {
    if(!g->enabled || !isfinite(dt) || dt<=0 || dt>.05f) return;
    if((uint32_t)(now_ms-g->last_packet)>WATCHDOG_MS) {
        /* Hold current command; do not relax an overhead payload on link loss. */
        g->target_pan=g->pan; g->target_tilt=g->tilt;
        g->pan_velocity=g->tilt_velocity=0;
        return;
    }
    axis(&g->pan,&g->pan_velocity,g->target_pan,dt);
    axis(&g->tilt,&g->tilt_velocity,g->target_tilt,dt);
    g->pan=fmaxf(-PAN_LIMIT,fminf(PAN_LIMIT,g->pan));
    g->tilt=fmaxf(-TILT_LIMIT,fminf(TILT_LIMIT,g->tilt));
}

uint16_t gimbal_pulse(float degrees) {
    if(!isfinite(degrees)) return 1500;
    degrees=fmaxf(-60,fminf(60,degrees));
    return (uint16_t)lroundf(1500+degrees*(500.0f/60.0f));
}
