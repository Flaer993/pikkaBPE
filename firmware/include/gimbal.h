#ifndef PIKKA_GIMBAL_H
#define PIKKA_GIMBAL_H
#include <stdint.h>
#include <stddef.h>
typedef struct {
    float pan, tilt, pan_velocity, tilt_velocity, target_pan, target_tilt;
    uint32_t last_packet;
    uint16_t sequence;
    int enabled, have_sequence;
} Gimbal;
void gimbal_init(Gimbal *g);
int gimbal_packet(Gimbal *g, const char *line, uint32_t now_ms);
void gimbal_tick(Gimbal *g, uint32_t now_ms, float dt);
uint16_t gimbal_pulse(float degrees);
uint16_t gimbal_crc(const char *data, size_t length);
#endif
