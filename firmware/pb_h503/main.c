/* PB_MCU01_H503 schematic V1.0: STM32H503CBT6, USB PA11/PA12,
 * pan = H1.5 PA0 TIM2_CH1 AF1, tilt = H1.6 PA1 TIM2_CH2 AF1.
 * GPIO remains without PWM until the first validated host command.
 */
#include "stm32h5xx_hal.h"
#include "tusb.h"
#include "gimbal.h"
#include <stdio.h>

uint32_t device_uid[3];
static TIM_HandleTypeDef timer;
static Gimbal gimbal;
static int armed;

static void fault(void) {
 __disable_irq();
 /* Stop CPU activity. Existing timer output holds the last command. */
 while(1) { __WFI(); }
}
void HardFault_Handler(void) { fault(); }
void SysTick_Handler(void) { HAL_IncTick(); }
void USB_DRD_FS_IRQHandler(void) { tusb_int_handler(0,true); }
uint32_t tusb_time_millis_api(void) { return HAL_GetTick(); }
void _init(void) {}

static void clocks(void) {
 __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE0);
 while(!__HAL_PWR_GET_FLAG(PWR_FLAG_VOSRDY)) {}
 RCC_OscInitTypeDef osc={0};
 osc.OscillatorType=RCC_OSCILLATORTYPE_HSI|RCC_OSCILLATORTYPE_HSI48;
 osc.HSIState=RCC_HSI_ON; osc.HSIDiv=RCC_HSI_DIV1;
 osc.HSICalibrationValue=RCC_HSICALIBRATION_DEFAULT;
 osc.HSI48State=RCC_HSI48_ON; osc.PLL.PLLState=RCC_PLL_NONE;
 if(HAL_RCC_OscConfig(&osc)!=HAL_OK) fault();
 RCC_ClkInitTypeDef clk={0};
 clk.ClockType=RCC_CLOCKTYPE_SYSCLK|RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2|RCC_CLOCKTYPE_PCLK3;
 clk.SYSCLKSource=RCC_SYSCLKSOURCE_HSI; clk.AHBCLKDivider=RCC_SYSCLK_DIV1;
 clk.APB1CLKDivider=RCC_HCLK_DIV1; clk.APB2CLKDivider=RCC_HCLK_DIV1; clk.APB3CLKDivider=RCC_HCLK_DIV1;
 if(HAL_RCC_ClockConfig(&clk,FLASH_LATENCY_2)!=HAL_OK) fault();
 SystemCoreClockUpdate();
 RCC_PeriphCLKInitTypeDef usb={0};
 usb.PeriphClockSelection=RCC_PERIPHCLK_USB; usb.UsbClockSelection=RCC_USBCLKSOURCE_HSI48;
 if(HAL_RCCEx_PeriphCLKConfig(&usb)!=HAL_OK) fault();
 __HAL_RCC_CRS_CLK_ENABLE();
 RCC_CRSInitTypeDef crs={0};
 crs.Prescaler=RCC_CRS_SYNC_DIV1; crs.Source=RCC_CRS_SYNC_SOURCE_USB;
 crs.Polarity=RCC_CRS_SYNC_POLARITY_RISING;
 crs.ReloadValue=__HAL_RCC_CRS_RELOADVALUE_CALCULATE(48000000,1000);
 crs.ErrorLimitValue=34; crs.HSI48CalibrationValue=32;
 HAL_RCCEx_CRSConfig(&crs);
}

static void peripherals(void) {
 __HAL_RCC_GPIOA_CLK_ENABLE(); __HAL_RCC_GPIOC_CLK_ENABLE(); __HAL_RCC_TIM2_CLK_ENABLE();
 GPIO_InitTypeDef pin={0};
 pin.Pin=GPIO_PIN_0|GPIO_PIN_1; pin.Mode=GPIO_MODE_AF_PP;
 pin.Pull=GPIO_NOPULL; pin.Speed=GPIO_SPEED_FREQ_LOW; pin.Alternate=GPIO_AF1_TIM2;
 HAL_GPIO_Init(GPIOA,&pin);
 pin.Pin=GPIO_PIN_13; pin.Mode=GPIO_MODE_OUTPUT_PP; pin.Alternate=0;
 HAL_GPIO_Init(GPIOC,&pin); HAL_GPIO_WritePin(GPIOC,GPIO_PIN_13,GPIO_PIN_SET); /* active-low LED */
 timer.Instance=TIM2; timer.Init.Prescaler=HAL_RCC_GetPCLK1Freq()/1000000U-1U;
 timer.Init.CounterMode=TIM_COUNTERMODE_UP; timer.Init.Period=19999;
 timer.Init.ClockDivision=TIM_CLOCKDIVISION_DIV1; timer.Init.AutoReloadPreload=TIM_AUTORELOAD_PRELOAD_ENABLE;
 if(HAL_TIM_PWM_Init(&timer)!=HAL_OK) fault();
 TIM_OC_InitTypeDef output={0};
 output.OCMode=TIM_OCMODE_PWM1; output.Pulse=1500;
 output.OCPolarity=TIM_OCPOLARITY_HIGH; output.OCFastMode=TIM_OCFAST_DISABLE;
 if(HAL_TIM_PWM_ConfigChannel(&timer,&output,TIM_CHANNEL_1)!=HAL_OK) fault();
 if(HAL_TIM_PWM_ConfigChannel(&timer,&output,TIM_CHANNEL_2)!=HAL_OK) fault();
 /* Native USB: the peripheral owns PA11/PA12. No UART AF mapping here. */
 pin.Pin=GPIO_PIN_11|GPIO_PIN_12; pin.Mode=GPIO_MODE_INPUT; pin.Pull=GPIO_NOPULL; pin.Alternate=0;
 HAL_GPIO_Init(GPIOA,&pin); __HAL_RCC_USB_CLK_ENABLE();
 NVIC_SetPriority(USB_DRD_FS_IRQn,5);
}

static void receive(void) {
 static char line[64]; static unsigned used; static int dropping;
 unsigned budget=256; /* Bound parsing time to keep motion updates responsive. */
 while(budget-- && tud_cdc_available()) {
  char byte=(char)tud_cdc_read_char();
  if(byte=='\r') continue;
  if(byte=='\n') {
   line[used]=0;
   if(!dropping && gimbal_packet(&gimbal,line,HAL_GetTick())) {
    if(!armed) {
     if(HAL_TIM_PWM_Start(&timer,TIM_CHANNEL_1)!=HAL_OK || HAL_TIM_PWM_Start(&timer,TIM_CHANNEL_2)!=HAL_OK) fault();
     armed=1;
    }
    char ack[48];
    int length=snprintf(ack,sizeof(ack),"ACK,%u,%d,%d\n",gimbal.sequence,(int)(gimbal.pan*100),(int)(gimbal.tilt*100));
    if(tud_cdc_write_available()>=(uint32_t)length) tud_cdc_write(ack,(uint32_t)length);
   }
   used=0; dropping=0;
  } else if(!dropping) {
   if(used>=sizeof(line)-1 || byte<32 || byte>126) { used=0; dropping=1; }
   else line[used++]=byte;
  }
 }
 tud_cdc_write_flush();
}

int main(void) {
 /* Read UID before any optional instruction cache enable (STM32H5 erratum). */
 for(unsigned i=0;i<3;i++) device_uid[i]=((volatile uint32_t*)UID_BASE)[i];
 HAL_Init(); clocks(); peripherals(); gimbal_init(&gimbal);
 tusb_rhport_init_t init={.role=TUSB_ROLE_DEVICE,.speed=TUSB_SPEED_FULL};
 if(!tusb_init(0,&init)) fault();
 uint32_t last=HAL_GetTick();
 while(1) {
  tud_task(); receive();
  uint32_t now=HAL_GetTick(),elapsed=now-last;
  if(elapsed>=10) {
   if(elapsed>50) {
    gimbal.target_pan=gimbal.pan; gimbal.target_tilt=gimbal.tilt;
    gimbal.pan_velocity=gimbal.tilt_velocity=0;
   } else gimbal_tick(&gimbal,now,elapsed/1000.0f);
   last=now;
   __HAL_TIM_SET_COMPARE(&timer,TIM_CHANNEL_1,gimbal_pulse(gimbal.pan));
   __HAL_TIM_SET_COMPARE(&timer,TIM_CHANNEL_2,gimbal_pulse(gimbal.tilt));
   HAL_GPIO_WritePin(GPIOC,GPIO_PIN_13,tud_mounted()?GPIO_PIN_RESET:GPIO_PIN_SET);
  }
 }
}
