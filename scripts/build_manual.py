from pathlib import Path
import re
from xml.sax.saxutils import escape
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, PageBreak, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.enums import TA_LEFT

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output'/'pdf'; OUT.mkdir(parents=True,exist_ok=True)
FONT=Path('C:/Windows/Fonts')
pdfmetrics.registerFont(TTFont('UI',str(FONT/'arial.ttf')))
pdfmetrics.registerFont(TTFont('UI-Bold',str(FONT/'arialbd.ttf')))
styles=getSampleStyleSheet()
styles.add(ParagraphStyle(name='BodyRU',fontName='UI',fontSize=10,leading=15,spaceAfter=9,textColor=HexColor('#27323b'),wordWrap='CJK'))
styles.add(ParagraphStyle(name='HeadingRU',fontName='UI-Bold',fontSize=19,leading=24,spaceAfter=16,textColor=HexColor('#d36721')))
styles.add(ParagraphStyle(name='TitleRU',fontName='UI-Bold',fontSize=34,leading=42,spaceAfter=18,textColor=HexColor('#27323b')))

def footer(c,doc):
    c.setStrokeColor(HexColor('#f5822b')); c.line(42,40,553,40)
    c.setFont('UI',8); c.setFillColor(HexColor('#64717c'))
    c.drawString(42,26,'pikkāBPE / 0.1.2 / P0 / домашний прототип')
    c.drawRightString(553,26,str(doc.page))

story=[Spacer(1,35),Paragraph('pikkāBPE',styles['TitleRU']),Paragraph('Камера. Подвес. Операторский учёт.',styles['HeadingRU']),Paragraph('Минимальная документация / 16 сентября 2026',styles['BodyRU'])]
preview=ROOT/'cad'/'previews'/'assembly.png'
if preview.exists(): story.append(Image(str(preview),width=490,height=350))
story.append(Paragraph('Этап 1: домашний стенд. CAD P0 - компоновка для проверки посадок. Складской учёт подтверждает оператор. Прошивка USB CDC собрана, проверка на плате впереди.',styles['BodyRU']))
story.append(PageBreak())
text=(ROOT/'docs'/'manual.md').read_text(encoding='utf-8')
for section in text.split('\n## ')[1:]:
    heading,body=section.split('\n',1)
    story.append(Paragraph(escape(heading),styles['HeadingRU']))
    if heading.startswith('02.'):
        preview=ROOT/'data'/'client-preview.png'
        if preview.exists(): story.append(Image(str(preview),width=490,height=315)); story.append(Spacer(1,12))
    for paragraph in re.split(r'\n\s*\n',body.strip()):
        value=escape(' '.join(paragraph.splitlines()))
        story.append(Paragraph(value,styles['BodyRU']))
    story.append(PageBreak())
story.pop()
SimpleDocTemplate(str(OUT/'pikkaBPE-manual.pdf'),pagesize=(595.28,841.89),rightMargin=42,leftMargin=42,topMargin=42,bottomMargin=55,title='pikkāBPE / Prototype manual',author='pikkāBPE project').build(story,onFirstPage=footer,onLaterPages=footer)
print(OUT/'pikkaBPE-manual.pdf')
