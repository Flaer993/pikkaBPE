"""CRC-protected serial target protocol shared with portable C firmware."""
import binascii
import time
import serial


def packet(seq, pan, tilt):
    if not (-60 <= pan <= 60 and -45 <= tilt <= 45):
        raise ValueError('Угол за пределами предварительной калибровки')
    body = f'P1,{seq % 65536},{round(pan*100)},{round(tilt*100)}'.encode('ascii')
    return body + f'*{binascii.crc_hqx(body, 0xffff):04X}\n'.encode('ascii')


class Link:
    def __init__(self):
        self.port = None
        self.seq = 0
        self.last_rx = 0.0
        self.status = 'Не подключён'
        self.buffer = b''

    def open(self, name):
        self.close()
        self.port = serial.Serial(name, 115200, timeout=0, write_timeout=.1)
        self.status = 'Ожидание ответа MCU'

    def send(self, pan, tilt):
        if self.port:
            self.seq = (self.seq+1) % 65536
            self.port.write(packet(self.seq, pan, tilt))
            self.buffer = (self.buffer + self.port.read(512))[-2048:]
            while b'\n' in self.buffer:
                line, self.buffer = self.buffer.split(b'\n', 1)
                if line.startswith(b'ACK,'):
                    self.last_rx = time.monotonic()
                    self.status = line.decode('ascii', errors='replace')
            if time.monotonic() - self.last_rx > 1:
                self.status = 'Нет подтверждения MCU'

    def close(self):
        if self.port:
            self.port.close()
        self.port = None
        self.status = 'Не подключён'
