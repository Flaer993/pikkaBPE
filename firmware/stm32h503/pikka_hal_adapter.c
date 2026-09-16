/* Integrate into a CubeMX project for the VERIFIED PB_MCU01_H503A pinout.
 * This file deliberately does not guess USB-UART routing or connector pins.
 * Timer: 1 MHz counter, ARR=19999 (50 Hz), PWM mode 1, two channels.
 * UART: 115200, 8N1. Call app_rx_byte from the MAIN loop, not an ISR.
 * Receive UART with a bounded DMA/ring queue; overflow discards the whole line.
 */
#include "main.h"
#include "gimbal.h"
#include <stdio.h>
#include <string.h>

static Gimbal g;
static TIM_HandleTypeDef *timer;
static UART_HandleTypeDef *uart;
static uint32_t pan_channel,tilt_channel,last_tick;
static char rx_line[64];
static unsigned rx_len;
static int dropping;

void app_init(TIM_HandleTypeDef *pwm, uint32_t pan, uint32_t tilt, UART_HandleTypeDef *serial) {
    timer=pwm; uart=serial; pan_channel=pan; tilt_channel=tilt;
    gimbal_init(&g); last_tick=HAL_GetTick();
    __HAL_TIM_SET_COMPARE(timer,pan_channel,1500);
    __HAL_TIM_SET_COMPARE(timer,tilt_channel,1500);
    /* Servo power OFF while mechanically centering horn before first start. */
    HAL_TIM_PWM_Start(timer,pan_channel); HAL_TIM_PWM_Start(timer,tilt_channel);
}

void app_rx_byte(uint8_t byte) {
    if(byte=='\r') return;
    if(byte=='\n') {
        rx_line[rx_len]=0;
        if(!dropping && gimbal_packet(&g,rx_line,HAL_GetTick())) {
            char reply[48];
            int len=snprintf(reply,sizeof(reply),"ACK,%u,%d,%d\n",g.sequence,(int)(g.pan*100),(int)(g.tilt*100));
            HAL_UART_Transmit(uart,(uint8_t*)reply,(uint16_t)len,10);
        }
        rx_len=0; dropping=0;
    } else if(!dropping) {
        if(rx_len>=sizeof(rx_line)-1) { dropping=1; rx_len=0; }
        else rx_line[rx_len++]=(char)byte;
    }
}

void app_poll(void) {
    uint32_t now=HAL_GetTick(), elapsed=now-last_tick;
    if(elapsed>=10) {
        if(elapsed>50) { g.target_pan=g.pan; g.target_tilt=g.tilt; g.pan_velocity=g.tilt_velocity=0; }
        else gimbal_tick(&g,now,elapsed/1000.0f);
        last_tick=now;
        __HAL_TIM_SET_COMPARE(timer,pan_channel,gimbal_pulse(g.pan));
        __HAL_TIM_SET_COMPARE(timer,tilt_channel,gimbal_pulse(g.tilt));
    }
}
