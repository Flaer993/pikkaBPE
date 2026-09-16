#include "tusb.h"
#include <stdio.h>
#include <string.h>
/* TinyUSB laboratory VID/PID, not an assigned commercial product identity. */
static const tusb_desc_device_t device={
 .bLength=sizeof(tusb_desc_device_t),.bDescriptorType=TUSB_DESC_DEVICE,.bcdUSB=0x0200,
 .bDeviceClass=TUSB_CLASS_MISC,.bDeviceSubClass=MISC_SUBCLASS_COMMON,.bDeviceProtocol=MISC_PROTOCOL_IAD,
 .bMaxPacketSize0=64,.idVendor=0xcafe,.idProduct=0x4011,.bcdDevice=0x0101,
 .iManufacturer=1,.iProduct=2,.iSerialNumber=3,.bNumConfigurations=1
};
static const uint8_t config[]={
 TUD_CONFIG_DESCRIPTOR(1,2,0,TUD_CONFIG_DESC_LEN+TUD_CDC_DESC_LEN,0x00,100),
 TUD_CDC_DESCRIPTOR(0,4,0x81,8,0x02,0x82,64)
};
extern uint32_t device_uid[3];
uint8_t const *tud_descriptor_device_cb(void) { return (const uint8_t*)&device; }
uint8_t const *tud_descriptor_configuration_cb(uint8_t index) { (void)index; return config; }
uint16_t const *tud_descriptor_string_cb(uint8_t index,uint16_t langid) {
 (void)langid;
 static uint16_t descriptor[48];
 static char serial[25];
 if(index==0) { descriptor[0]=(TUSB_DESC_STRING<<8)|4; descriptor[1]=0x0409; return descriptor; }
 snprintf(serial,sizeof(serial),"%08lX%08lX%08lX",(unsigned long)device_uid[0],(unsigned long)device_uid[1],(unsigned long)device_uid[2]);
 const char *strings[]={"","pikkaBPE prototype","PB H503 Gimbal CDC",serial,"Gimbal control"};
 if(index>=sizeof(strings)/sizeof(strings[0])) return NULL;
 size_t length=strlen(strings[index]); if(length>47) length=47;
 for(size_t i=0;i<length;i++) descriptor[1+i]=(uint8_t)strings[index][i];
 descriptor[0]=(uint16_t)((TUSB_DESC_STRING<<8)|(2*length+2));
 return descriptor;
}
