"""Generate native editable feature parts in installed SolidWorks 2024.
All dimensions in mm here, converted to SI at the API boundary.
P0 is a fit/layout prototype, not a released overhead load-bearing assembly.
"""
import json
import math
import sys
from pathlib import Path
import pythoncom
import win32com.client as win32
from win32com.client import gencache

ROOT=Path(__file__).resolve().parent
P=json.loads((ROOT/'parameters.json').read_text())
TLB=r'C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\sldworks.tlb'
TEMPLATES=Path(r'C:\ProgramData\SOLIDWORKS\SOLIDWORKS 2024\templates')
info=pythoncom.LoadTypeLib(TLB).GetLibAttr()
api=gencache.EnsureModule(info[0],info[1],info[3],info[4])
sw=api.ISldWorks(win32.Dispatch('SldWorks.Application.32')._oleobj_)
sw.Visible=True
NULL=None
parts=[]

def cast(obj,kind): return getattr(api,kind)(obj._oleobj_)
def mm(v): return v/1000
def polygon(sk,points):
    for a,b in zip(points,points[1:]+points[:1]): sk.CreateLine(mm(a[0]),mm(a[1]),0,mm(b[0]),mm(b[1]),0)
def octagon(w,h,c): return [(-w/2+c,-h/2),(w/2-c,-h/2),(w/2,-h/2+c),(w/2,h/2-c),(w/2-c,h/2),(-w/2+c,h/2),(-w/2,h/2-c),(-w/2,-h/2+c)]
def circle(sk,x,y,d): sk.CreateCircleByRadius(mm(x),mm(y),0,mm(d/2))
def rectangle(sk,x1,y1,x2,y2): sk.CreateCornerRectangle(mm(x1),mm(y1),0,mm(x2),mm(y2),0)

def make(name,profile,thickness,color=(.29,.33,.38),position=(0,0,0),rotation=None):
    if '--assemble-only' in sys.argv:
        native=ROOT/'native'/f'{name}.SLDPRT'
        parts.append({'name':name,'path':str(native),'position':position,'rotation':rotation})
        sw.OpenDoc6(str(native),1,1,'',0,0)
        return
    doc=cast(sw.NewDocument(str(TEMPLATES/'gost-part.prtdot'),0,0,0),'IModelDoc2')
    doc.ClearSelection2(True)
    assert doc.Extension.SelectByID2('Спереди','PLANE',0,0,0,False,0,NULL,0)
    sk=doc.SketchManager; sk.InsertSketch(True); profile(sk)
    feature=doc.FeatureManager.FeatureExtrusion2(True,False,False,0,0,mm(thickness),0,False,False,False,False,0,0,False,False,False,False,True,True,True,0,0,False)
    if feature is None: raise RuntimeError(f'Extrusion failed: {name}')
    feature.Name=name
    doc.MaterialPropertyValues=win32.VARIANT(pythoncom.VT_ARRAY|pythoncom.VT_R8,[*color,.6,.8,.2,.1,0,0])
    doc.ShowNamedView2('*Isometric',7); doc.ViewZoomtofit2(); doc.ForceRebuild3(False)
    native=ROOT/'native'/f'{name}.SLDPRT'
    for folder in ('native','step','stl','previews'): (ROOT/folder).mkdir(exist_ok=True)
    # SaveAs3 returns a native error bitfield; zero means success.
    code=doc.SaveAs3(str(native),0,1)
    if code!=0: raise RuntimeError(f'Save failed {name}: {code}')
    for suffix in ('step','stl'):
        result=doc.Extension.SaveAs(str(ROOT/suffix/f'{name}.{suffix}'),0,3,NULL,0,0)
        if not result[0]: raise RuntimeError(f'Export failed {name} {suffix}: {result}')
    parts.append({'name':name,'path':str(native),'position':position,'rotation':rotation})
    print('CREATED',name,flush=True)
    return doc


def ceiling(sk):
    p=P['ceiling']; polygon(sk,octagon(p['width'],p['depth'],p['corner_cut']))
    for x in [-p['hole_pitch_x']/2,p['hole_pitch_x']/2]:
        for y in [-p['hole_pitch_y']/2,p['hole_pitch_y']/2]: circle(sk,x,y,p['clearance_M5'])
    for x in [-36,36]:
        for y in [-25,25]: circle(sk,x,y,3.4)
    rectangle(sk,45,-8,58,8)
    circle(sk,-53,0,5) # tether eye; steel tether must anchor independently

def deck(sk):
    polygon(sk,octagon(105,80,12))
    s=P['servo']; l=s['body_length']+s['body_clearance']; w=s['body_width']+s['body_clearance']; offset=s['shaft_offset_from_body_center']
    rectangle(sk,offset-l/2,-w/2,offset+l/2,w/2)
    for x in [offset-s['mount_pitch_long']/2,offset+s['mount_pitch_long']/2]:
        for y in [-5,5]: circle(sk,x,y,3.4)
    for x in [-36,36]:
        for y in [-25,25]: circle(sk,x,y,3.4)
    for x,y in [(0,29),(0,-29),(-29,0)]: circle(sk,x,y,3.4)

def bearing_housing(sk):
    polygon(sk,octagon(72,72,15)); circle(sk,0,0,42.2)
    for x,y in [(0,29),(0,-29),(-29,0)]: circle(sk,x,y,3.4)

def retaining_ring(sk):
    polygon(sk,octagon(72,72,15)); circle(sk,0,0,36)
    for x,y in [(0,29),(0,-29),(-29,0)]: circle(sk,x,y,3.4)

def journal(sk):
    circle(sk,0,0,29.85); circle(sk,0,0,8)
    # Example horn bolt circle: drill/adjust to actual metal horn after measurement.
    for x,y in [(-9,0),(9,0),(0,9),(0,-9)]: circle(sk,x,y,3.2)

def yoke(sk):
    polygon(sk,octagon(160,78,14)); circle(sk,0,0,8)
    for x,y in [(-9,0),(9,0),(0,9),(0,-9)]: circle(sk,x,y,3.2)
    for x in [-68,68]:
        for y in [-24,24]: circle(sk,x,y,3.4)

def cheek_drive(sk):
    polygon(sk,[(-38,0),(38,0),(38,62),(22,88),(-22,88),(-38,62)])
    s=P['servo']; cy=57; offset=s['shaft_offset_from_body_center']
    rectangle(sk,-(s['body_width']+.6)/2,cy-offset-(s['body_length']+.6)/2,(s['body_width']+.6)/2,cy-offset+(s['body_length']+.6)/2)
    for x in [-5,5]:
        for y in [cy-offset-s['mount_pitch_long']/2,cy-offset+s['mount_pitch_long']/2]: circle(sk,x,y,3.4)
    for x in [-24,24]: circle(sk,x,10,3.4)

def cheek_idler(sk):
    polygon(sk,[(-38,0),(38,0),(38,62),(22,88),(-22,88),(-38,62)])
    circle(sk,0,57,22.2) # 608 idler bearing
    for x in [-24,24]: circle(sk,x,10,3.4)

def tray(sk):
    polygon(sk,octagon(126,85,12))
    rectangle(sk,-3.3,-15,3.3,15) # 1/4-20 screw adjustment slot
    for x in [-53,53]:
        for y in [-26,26]: circle(sk,x,y,3.4)

def tray_ear(sk):
    polygon(sk,[(-33,0),(33,0),(33,24),(20,45),(-20,45),(-33,24)])
    circle(sk,0,25,8.2)
    for x,y in [(-9,25),(9,25),(0,16),(0,34)]: circle(sk,x,y,3.2)
    for x in [-24,24]: circle(sk,x,8,3.4)

def corner(sk):
    polygon(sk,[(-10,0),(10,0),(10,20),(4,20),(4,6),(-10,6)])

def spacer(sk):
    polygon(sk,octagon(12,12,2)); circle(sk,0,0,3.4)

def main():
    sw.CloseDoc(str(ROOT/'native'/'pikkaBPE_P0.SLDASM'))
    make('01_Ceiling_M5',ceiling,P['ceiling']['thickness'])
    make('02_Pan_servo_deck',deck,6,position=(0,0,50))
    make('03_Bearing_housing_6806',bearing_housing,7.2,position=(0,0,58))
    make('04_Bearing_retainer',retaining_ring,2.8,(.95,.35,.07),position=(0,0,65.2))
    make('05_Pan_horn_journal',journal,11.8,(.95,.35,.07),position=(0,0,58))
    make('06_Rotating_yoke',yoke,6,position=(0,0,70))
    # Local x -> assembly y, local y -> assembly z, local z -> assembly x.
    rot=[0,1,0,0,0,1,1,0,0]
    make('07_Tilt_drive_cheek',cheek_drive,6,position=(-80,0,76),rotation=rot)
    make('08_Tilt_idler_cheek',cheek_idler,6,position=(74,0,76),rotation=rot)
    make('09_C920_tripod_tray',tray,5,position=(0,0,158))
    make('10_Camera_side_ear',tray_ear,5,(.95,.35,.07),position=(-63,0,158),rotation=[0,1,0,0,0,-1,-1,0,0])
    make('11_Standoff_46mm',spacer,46,position=(-36,-25,4))
    make('12_Corner_cleat',corner,12,(.95,.35,.07),position=(-68,-24,76))
    doc=cast(sw.NewDocument(str(TEMPLATES/'gost-assy.asmdot'),0,0,0),'IModelDoc2'); assembly=cast(doc,'IAssemblyDoc')
    util=cast(sw.GetMathUtility(),'IMathUtility')
    # Cleat remains a separate fit coupon, not an installed un-drilled bracket.
    placements=[p for p in parts if p['name']!='12_Corner_cleat']
    for x,y in [(-36,25),(36,-25),(36,25)]: placements.append({**parts[10],'position':(x,y,4)})
    placements.append({**parts[9],'position':(68,0,158),'rotation':[0,1,0,0,0,-1,-1,0,0]})
    for p in placements:
        component=assembly.AddComponent5(p['path'],0,'',False,'',0,0,0)
        if component is None: raise RuntimeError('Assembly insertion failed: '+p['name'])
        component=cast(component,'IComponent2')
        rotation=p['rotation'] or [1,0,0,0,1,0,0,0,1]
        transform=util.CreateTransform(win32.VARIANT(pythoncom.VT_ARRAY|pythoncom.VT_R8,[*rotation,*[mm(x) for x in p['position']],1,0,0,0]))
        component.Transform2=transform
        component.Select4(False,NULL,False); assembly.FixComponent(); doc.ClearSelection2(True)
    doc.ShowNamedView2('*Isometric',7); doc.ViewZoomtofit2(); doc.ForceRebuild3(False)
    code=doc.SaveAs3(str(ROOT/'native'/'pikkaBPE_P0.SLDASM'),0,1)
    if code: raise RuntimeError('Assembly save failed '+str(code))
    assert doc.Extension.SaveAs(str(ROOT/'step'/'pikkaBPE_P0.step'),0,3,NULL,0,0)[0]
    (ROOT/'build-report.json').write_text(json.dumps({'revision':P['revision'],'solidworks':sw.RevisionNumber(),'parts':parts,'placements':len(placements),'assembly_type':'fixed layout; not a kinematic simulation','unverified':['servo mounting holes','horn pattern','shaft retention and metal load path','corner cleat drill patterns','ceiling substrate','clearance through swept motion']},indent=2),encoding='utf-8')
    print('ASSEMBLY SAVED',flush=True)

if __name__=='__main__': main()
