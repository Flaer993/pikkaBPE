"""Build actual Cortex-M33 USB CDC firmware with GNU Arm Embedded tools."""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]

def main():
 parser=argparse.ArgumentParser(); parser.add_argument('--gcc',default=shutil.which('arm-none-eabi-gcc')); args=parser.parse_args()
 if not args.gcc: parser.error('arm-none-eabi-gcc is required; set PATH or --gcc')
 gcc=Path(args.gcc).resolve(); deps=Path(os.environ.get('PIKKABPE_DEPS',ROOT/'build'/'firmware-deps')).resolve()
 for name in ('tinyusb','device','hal','cmsis'):
  if not (deps/name/'.pikka-commit').exists(): raise RuntimeError('Run scripts/fetch_firmware_deps.py first')
 out=ROOT/'build'/'pb_h503'; out.mkdir(parents=True,exist_ok=True)
 hal=deps/'hal'; tiny=deps/'tinyusb'; device=deps/'device'
 sources=[ROOT/'firmware'/'src'/'gimbal.c',ROOT/'firmware'/'pb_h503'/'main.c',ROOT/'firmware'/'pb_h503'/'usb_descriptors.c',ROOT/'firmware'/'pb_h503'/'syscalls.c',
  device/'Source'/'Templates'/'system_stm32h5xx.c',device/'Source'/'Templates'/'gcc'/'startup_stm32h503xx.s']
 for name in ['hal','hal_cortex','hal_rcc','hal_rcc_ex','hal_gpio','hal_pwr','hal_pwr_ex','hal_flash','hal_flash_ex','hal_tim','hal_tim_ex','hal_dma','hal_dma_ex']:
  sources.append(hal/'Src'/('stm32h5xx_'+name+'.c'))
 for path in ['tusb.c','common/tusb_fifo.c','device/usbd.c','class/cdc/cdc_device.c','portable/st/stm32_fsdev/dcd_stm32_fsdev.c','portable/st/stm32_fsdev/fsdev_common.c']:
  sources.append(tiny/'src'/path)
 includes=[ROOT/'firmware'/'include',ROOT/'firmware'/'pb_h503',hal/'Inc',hal/'Inc'/'Legacy',device/'Include',deps/'cmsis'/'CMSIS'/'Core'/'Include',tiny/'src']
 arch=['-mcpu=cortex-m33','-mthumb','-mfloat-abi=hard','-mfpu=fpv5-sp-d16']
 flags=arch+['-std=gnu11','-Os','-g3','-ffunction-sections','-fdata-sections','-DSTM32H503xx','-DUSE_HAL_DRIVER','-Wall','-Wextra']+['-I'+str(p) for p in includes]
 def compile_source(source):
  obj=out/(source.stem+'.o')
  subprocess.run([str(gcc),*flags,'-c',str(source),'-o',str(obj)],check=True)
  return obj
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool: objects=list(pool.map(compile_source,sources))
 # Use the matching upstream H503 128K/32K memory map, with libc retained.
 linker=(tiny/'hw/bsp/stm32h5/linker/STM32H503xx_FLASH.ld').read_text()
 linker=linker.replace('    libc.a ( * )','').replace('    libm.a ( * )','').replace('    libgcc.a ( * )','')
 (out/'memory.ld').write_text(linker)
 elf=out/'pikkaBPE-PB-H503-USB.elf'
 subprocess.run([str(gcc),*arch,'--specs=nano.specs','--specs=nosys.specs','-nostartfiles',*[str(x) for x in objects],'-T'+str(out/'memory.ld'),'-Wl,--gc-sections','-Wl,--print-memory-usage','-Wl,-Map='+str(out/'firmware.map'),'-Wl,--start-group','-lc','-lm','-Wl,--end-group','-o',str(elf)],check=True)
 suffix='.exe' if os.name=='nt' else ''
 for format,extension in [('binary','bin'),('ihex','hex')]:
  subprocess.run([str(gcc.with_name('arm-none-eabi-objcopy'+suffix)),'-O',format,str(elf),str(elf.with_suffix('.'+extension))],check=True)
 report={'board':'PB_MCU01_H503 / schematic V1.0','mcu':'STM32H503CBT6','transport':'native USB CDC','flash_address':'0x08000000','hardware_tested':False,'compiler':subprocess.check_output([str(gcc),'--version'],text=True).splitlines()[0],'sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [elf,elf.with_suffix('.bin'),elf.with_suffix('.hex')]}}
 (out/'build-report.json').write_text(json.dumps(report,indent=2))
 notices=out/'licenses'; notices.mkdir(exist_ok=True)
 for name in ('tinyusb','device','hal','cmsis'):
  for license in (deps/name).glob('LICENSE*'):
   if license.is_file(): shutil.copy2(license,notices/(name+'-'+license.name))
 (out/'SHA256SUMS.txt').write_text('\n'.join(digest+'  '+name for name,digest in report['sha256'].items())+'\n')
 print(json.dumps(report,indent=2))

if __name__=='__main__': main()
