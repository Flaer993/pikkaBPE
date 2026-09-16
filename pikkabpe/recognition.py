"""One persistent inference process; at most one frame in flight."""
import base64
import json
import sys
import time
from pathlib import Path
import cv2
from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal, QTimer


def describe(store,code,score,threshold):
    rows=store.rows('SELECT name FROM products WHERE barcode=?',(code,))
    if not rows: return 'Товар отсутствует в справочнике'
    if score<threshold: return f'Не уверен — возможно {rows[0]["name"]} · {score:.0%}'
    return f'{rows[0]["name"]} · {score:.0%}'


class Recognition(QObject):
    result=Signal(object)
    message=Signal(str)

    def __init__(self,parent=None):
        super().__init__(parent)
        self.process=None; self.ready=False; self.pending=None; self.sequence=0
        self.buffer=b''; self.errors=''; self.deadline=0
        self.watch=QTimer(self); self.watch.setInterval(1000); self.watch.timeout.connect(self.check_timeout); self.watch.start()

    def start(self,python,model):
        self.stop()
        if not Path(model).is_file(): raise ValueError('Файл активной модели не найден. Активируйте модель заново.')
        self.process=QProcess(self); p=self.process
        env=QProcessEnvironment.systemEnvironment(); env.insert('PYTHONIOENCODING','utf-8')
        if getattr(sys,'frozen',False):
            runtime=Path(sys._MEIPASS)/'inference-runtime'
            env.insert('PYTHONPATH',str(runtime)); p.setWorkingDirectory(str(runtime))
        p.setProcessEnvironment(env)
        p.readyReadStandardOutput.connect(self.read)
        p.readyReadStandardError.connect(lambda:self.read_errors(p))
        p.errorOccurred.connect(lambda e:self.failed('Не удалось запустить распознавание: '+p.errorString()))
        p.finished.connect(lambda code:self.failed('Процесс распознавания завершён. '+self.errors[-600:]))
        self.deadline=time.monotonic()+90
        p.start(python,['-u','-m','pikkabpe.train','--serve','--model',str(model)])
        self.message.emit('Загружается модель…')

    def read_errors(self,p):
        self.errors=(self.errors+bytes(p.readAllStandardError()).decode('utf-8',errors='replace'))[-4000:]

    def failed(self,message):
        self.stop(); self.message.emit(message)

    def check_timeout(self):
        if self.deadline and time.monotonic()>self.deadline:
            self.failed('Распознавание не отвечает. Выключите и включите его повторно.')

    def read(self):
        self.buffer+=bytes(self.process.readAllStandardOutput())
        while b'\n' in self.buffer:
            line,self.buffer=self.buffer.split(b'\n',1)
            try: data=json.loads(line)
            except (ValueError,UnicodeDecodeError): continue
            if data.get('ready'):
                self.ready=True; self.deadline=0
                self.message.emit('Модель готова · '+data.get('device',''))
            elif self.pending and data.get('id')==self.pending['id']:
                context=self.pending; self.pending=None; self.deadline=0
                self.result.emit({**data,**context})

    def submit(self,frame,roi,generation,manual=False):
        if not self.ready or self.pending: return False
        x,y,w,h=roi; height,width=frame.shape[:2]
        crop=frame[max(0,int(y*height)):min(height,int((y+h)*height)),max(0,int(x*width)):min(width,int((x+w)*width))]
        if not crop.size: return False
        scale=min(1,640/max(crop.shape[:2]))
        if scale<1: crop=cv2.resize(crop,None,fx=scale,fy=scale)
        ok,encoded=cv2.imencode('.jpg',crop,[cv2.IMWRITE_JPEG_QUALITY,90])
        if not ok: return False
        self.sequence+=1
        self.pending={'id':self.sequence,'roi':roi,'generation':generation,'manual':manual,'submitted':time.monotonic()}
        self.deadline=time.monotonic()+15
        payload={'id':self.sequence,'image':base64.b64encode(encoded).decode('ascii')}
        self.process.write((json.dumps(payload)+'\n').encode('utf-8'))
        return True

    def stop(self):
        p=self.process; self.process=None; self.ready=False; self.pending=None; self.buffer=b''; self.deadline=0; self.errors=''
        if p:
            p.blockSignals(True)
            if p.state()!=QProcess.NotRunning: p.kill(); p.waitForFinished(2000)
            p.deleteLater()
