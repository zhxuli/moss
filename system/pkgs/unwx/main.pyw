#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信小程序反编译工具 (WeChat 4.0 / XWeChat radium) —— tkinter 图形版
两个版面: 「小程序列表」(扫描+还原) / 「输出目录」(已还原产物管理)
右键菜单: 浏览/导出到输出目录/导出并另存为/删除/启动微信开发者工具并打开
依赖: Python3 标准库 + tools/KillWxapkg.exe  (无需第三方库)
"""
import os, re, sys, json, threading, subprocess, shutil, tempfile, datetime, tkinter as tk
from tkinter import ttk, messagebox, filedialog

try:
    _bf = __file__
except NameError:
    _bf = sys.path[0] if (len(sys.path) > 0 and sys.path[0]) else os.getcwd()
BASE = os.path.dirname(os.path.abspath(_bf))
USERS_BASE = os.path.join(os.environ.get('APPDATA',''), 'Tencent','xwechat','radium','users')
# 宿主 moss 注入的插件专属数据目录 (= user_data/state/unwx)；老 pa 的 PA_* 与插件目录作兜底
DATA_DIR = os.environ.get('MOSS_PLUGIN_DATA_DIR') or os.environ.get('PA_PLUGIN_DATA_DIR') or BASE
TOOL = os.path.join(BASE,'tools','KillWxapkg.exe')
OUT_ROOT = os.path.join(DATA_DIR, 'output')   # 默认输出目录: 插件数据目录下的纯英文 output 文件夹
PREFS = os.path.join(DATA_DIR,'prefs.json')

def load_prefs():
    try: return json.load(open(PREFS,encoding='utf-8'))
    except Exception: return {}

def save_prefs(d):
    try:
        # 懒加载：只有真正写入配置时才创建数据目录
        if not os.path.isdir(DATA_DIR): os.makedirs(DATA_DIR, exist_ok=True)
        json.dump(d, open(PREFS,'w',encoding='utf-8'), ensure_ascii=False, indent=2)
    except Exception: pass

# ---------------- 名称探测(XOR 正文, 无需 AES) ----------------
def probe_name(appid, d):
    try:
        files=[f for f in os.listdir(d) if f.lower().endswith('.wxapkg')]
        if not files: return ''
        f=[x for x in files if '__APP__' in x.upper()] or [max(files,key=lambda n:os.path.getsize(os.path.join(d,n)))]
        data=open(os.path.join(d,f[0]),'rb').read()
        if data[:6]!=b'V1MMWX' or len(data)<1031: return ''
        xor=ord(appid[-2]) if len(appid)>=2 else 0x66
        body=bytearray(data[1030:])
        for i in range(len(body)): body[i]^=xor
        txt=bytes(body).decode('utf-8','ignore')
        m=re.search(r'"navigationBarTitleText"\s*:\s*"([^"]+)"',txt)
        if m: return m.group(1)
        m=re.search(r'"projectname"\s*:\s*"([^"]+)"',txt)
        if m: return m.group(1)
    except Exception: pass
    return ''

# ---------------- 扫描 ----------------
def scan():
    entries=[]
    if not os.path.isdir(USERS_BASE): return entries
    for user in os.listdir(USERS_BASE):
        pkg=os.path.join(USERS_BASE,user,'applet','packages')
        if not os.path.isdir(pkg): continue
        for appid in os.listdir(pkg):
            ap=os.path.join(pkg,appid)
            if not os.path.isdir(ap): continue
            for ver in os.listdir(ap):
                vp=os.path.join(ap,ver)
                if not os.path.isdir(vp): continue
                wxs=[]
                for root,_,files in os.walk(vp):
                    for n in files:
                        if n.lower().endswith('.wxapkg'):
                            fp=os.path.join(root,n); wxs.append((fp,os.path.getsize(fp),os.path.getmtime(fp)))
                if not wxs: continue
                entries.append(dict(appid=appid,user=user,version=ver,dir=vp,files=len(wxs),
                                    size=sum(x[1] for x in wxs),newest=max(x[2] for x in wxs)))
    by={}
    for e in entries:
        if e['appid'] not in by or e['newest']>by[e['appid']]['newest']: by[e['appid']]=e
    out=sorted(by.values(),key=lambda e:-e['newest'])
    for e in out:
        e['name']=probe_name(e['appid'],e['dir']) or e['appid']
        e['main']=('主包' if any('__APP__' in os.path.basename(fp) for fp in _wxs(e['dir'])) else '分包')
    return out

def _wxs(d):
    r=[]
    for root,_,files in os.walk(d):
        for n in files:
            if n.lower().endswith('.wxapkg'): r.append(os.path.join(root,n))
    return r

def fmt(ts): return datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')
def dir_size(d):
    s=0
    for root,_,files in os.walk(d):
        for n in files:
            try: s+=os.path.getsize(os.path.join(root,n))
            except: pass
    return s

# ---------------- 还原 ----------------
def restore(e, outdir, log):
    stage=tempfile.mkdtemp(prefix='stage_'+e['appid']+'_')
    log('>> 还原: %s (%s · 版本 %s)' % (e['appid'], e['user'], e['version']))
    args=[TOOL,'-in',e['dir'],'-id',e['appid'],'-out',stage,'-restore','-pretty','-save']
    log('   运行 KillWxapkg 整目录还原 ...')
    try:
        flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
        p=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=1800,creationflags=flags)
        tail='\n'.join(((p.stdout or b'').decode('utf-8','ignore')).splitlines()[-5:])
        if tail: log('   KillWxapkg 尾部:\n   '+tail.replace('\n','\n   '))
        if p.returncode!=0: log('   KillWxapkg 退出码 %s' % p.returncode)
    except Exception as er:
        log('   KillWxapkg 执行失败: %s' % er); raise
    for r2,_,fs in os.walk(stage):
        for n in fs:
            if n.lower().endswith('.wxapkg'):
                try: os.remove(os.path.join(r2,n))
                except: pass
    stripped=0
    for r2,_,fs in os.walk(stage):
        for n in fs:
            if n.lower().endswith('.json'):
                fp=os.path.join(r2,n)
                try:
                    j=json.load(open(fp,encoding='utf-8-sig'))
                    if isinstance(j,dict) and 'i18nKey' in j:
                        del j['i18nKey']; json.dump(j,open(fp,'w',encoding='utf-8'),ensure_ascii=False,indent=2); stripped+=1
                except: pass
    pcd=os.path.join(stage,'project.config.json')
    if not os.path.exists(pcd):
        json.dump({'description':e['appid'],'packOptions':{'ignore':[],'include':[]},
                   'setting':{'urlCheck':False,'es6':True,'postcss':True,'minified':True,'compileHotReLoad':True},
                   'compileType':'miniprogram','appid':e['appid'],'projectname':e['appid'],'condition':{}},
                  open(pcd,'w',encoding='utf-8'),ensure_ascii=False,indent=2)
        log('   (原包无 project.config.json, 补了中性配置)')
    else:
        log('   (已保留原版 project.config.json, 未注入任何内容)')
    out=os.path.join(outdir,e['appid'])
    shutil.copytree(stage,out,dirs_exist_ok=True)
    stale=os.path.join(out,'生成说明.txt')
    if os.path.exists(stale):
        try: os.remove(stale)
        except: pass
    shutil.rmtree(stage,ignore_errors=True)
    log('   完成: 已清 i18nKey %d 个; 输出目录: %s' % (stripped,out))
    return out

# ---------------- 微信开发者工具 ----------------
def find_devtools():
    cands=[
        r'C:\Program Files (x86)\Tencent\WeChatDevTools\cli.bat',
        r'C:\Program Files (x86)\Tencent\WeChatDevTools\wechatdevtools.exe',
        r'%USERPROFILE%\AppData\Local\微信开发者工具\cli.bat',
        r'%USERPROFILE%\AppData\Local\微信web开发者工具\cli.bat',
        r'C:\Program Files (x86)\Tencent\微信web开发者工具\cli.bat',
        r'C:\Program Files\Tencent\微信开发者工具\cli.bat',
        r'C:\Program Files (x86)\Tencent\微信开发者工具\cli.bat',
    ]
    for c in cands:
        p=os.path.expandvars(c)
        if os.path.exists(p): return p
    return None

def open_devtools(project_dir, log):
    # 打开前确保 project.config.json 有 appid(用文件夹名=AppID), 否则 cli open 可能不加载
    pcd=os.path.join(project_dir,'project.config.json')
    try:
        if os.path.exists(pcd):
            j=json.load(open(pcd,encoding='utf-8-sig'))
            if not j.get('appid'):
                j['appid']=os.path.basename(os.path.normpath(project_dir))
                json.dump(j,open(pcd,'w',encoding='utf-8'),ensure_ascii=False,indent=2)
                log('  (为打开已补上 appid: %s)' % j['appid'])
    except Exception: pass
    tool=find_devtools()
    if not tool:
        log('  未找到微信开发者工具(请手动: 开发者工具→导入项目→选该目录)')
        return
    # 微信开发者工具 CLI 对非 ASCII 项目路径支持差: 若含中文等, 复制到 ASCII 临时目录再打开
    ascii_dir=project_dir
    if any(ord(c)>127 for c in project_dir):
        sandbox=os.path.join(os.environ.get('TEMP','C:/Temp'),'_wxdt_open', os.path.basename(os.path.normpath(project_dir)))
        try:
            shutil.copytree(project_dir, sandbox, dirs_exist_ok=True)
            ascii_dir=sandbox
            log('  (路径含非ASCII, 已复制到临时ASCII目录再打开: %s)' % sandbox)
        except Exception as er:
            log('  复制临时目录失败(仍用原路径): %s' % er)
    log('  启动微信开发者工具打开: '+ascii_dir)
    log('  [提示] 若只启动工具而未加载项目: 请在开发者工具 设置→安全设置 勾选【开启服务端口】后重试; 或把输出目录改成纯英文路径')
    flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    try:
        if tool.lower().endswith('.bat'):
            subprocess.Popen(['cmd','/d','/c',tool,'open','--project',ascii_dir], creationflags=flags)
        else:
            subprocess.Popen([tool,'open','--project',ascii_dir], creationflags=flags)
    except Exception as er:
        log('  启动失败: %s' % er)

# ---------------- GUI ----------------
class App:
    def __init__(self,root):
        self.root=root; root.title('微信小程序反编译工具 · tkinter 版'); root.geometry('1120x720')
        prefs=load_prefs()
        self.outVar=tk.StringVar(value=prefs.get('out_root') or OUT_ROOT)
        try: os.makedirs(self.outVar.get().strip(), exist_ok=True)
        except Exception: pass
        top=tk.Frame(root,padx=10,pady=8); top.pack(fill='x')
        tk.Label(top,text='输出目录:').pack(side='left')
        tk.Entry(top,textvariable=self.outVar,width=54).pack(side='left',padx=4)
        tk.Button(top,text='浏览',command=self._pickout).pack(side='left',padx=4)
        tk.Button(top,text='重新扫描',command=self._rescan,bg='#4A6FFF',fg='white').pack(side='left',padx=8)
        tk.Label(top,text=' 缓存根: '+USERS_BASE,fg='#888').pack(side='left')
        self.outVar.trace_add('write',lambda *a:save_prefs({'out_root':self.outVar.get()}))

        self.nb=ttk.Notebook(root); self.nb.pack(fill='both',expand=True,padx=8,pady=(0,4))
        # ---- Tab1 小程序列表 ----
        self.scanTab=ttk.Frame(self.nb); self.nb.add(self.scanTab,text='小程序列表')
        srow=ttk.Frame(self.scanTab); srow.pack(fill='x',padx=4,pady=4)
        tk.Button(srow,text='还原选中项',command=self.do_restore,bg='#00B4A0',fg='white').pack(side='left')
        self.forceVar=tk.BooleanVar(value=False)
        tk.Checkbutton(srow,text='强制重导出(覆盖已有)',variable=self.forceVar).pack(side='left',padx=10)
        tk.Label(srow,text='(右键菜单: 浏览/导出/另存为/删除/打开工具)',fg='#999').pack(side='left',padx=12)
        sbody=ttk.Frame(self.scanTab); sbody.pack(fill='both',expand=True,padx=4)
        self.s_tree=ttk.Treeview(sbody,columns=('seq','appid','name','ver','main','files','size','newest'),show='headings')
        h={'seq':'#','appid':'AppID','name':'名称','ver':'版本','main':'包','files':'文件数','size':'大小(MB)','newest':'最近时间'}
        w={'seq':34,'appid':150,'name':180,'ver':60,'main':46,'files':60,'size':70,'newest':130}
        self._cfg(self.s_tree,h,w)
        sv=ttk.Scrollbar(sbody,command=self.s_tree.yview); self.s_tree.configure(yscrollcommand=sv.set)
        self.s_tree.pack(side='left',fill='both',expand=True); sv.pack(side='left',fill='y')
        self.s_ec=[]
        # ---- Tab2 输出目录 ----
        self.outTab=ttk.Frame(self.nb); self.nb.add(self.outTab,text='输出目录')
        orow=ttk.Frame(self.outTab); orow.pack(fill='x',padx=4,pady=4)
        tk.Button(orow,text='刷新',command=self.refresh_out,bg='#4A6FFF',fg='white').pack(side='left')
        tk.Button(orow,text='清空输出目录',command=self._clear_out,bg='#FF4D4F',fg='white').pack(side='left',padx=8)
        tk.Button(orow,text='打开输出目录',command=lambda:self._browse(self.outVar.get())).pack(side='left',padx=8)
        tk.Label(orow,text='(右键菜单: 浏览/打开工具/另存/删除)',fg='#999').pack(side='left',padx=12)
        obody=ttk.Frame(self.outTab); obody.pack(fill='both',expand=True,padx=4)
        self.o_tree=ttk.Treeview(obody,columns=('appid','name','size','mtime'),show='headings')
        h2={'appid':'AppID','name':'名称','size':'大小(MB)','mtime':'生成时间'}
        w2={'appid':170,'name':200,'size':90,'mtime':150}
        self._cfg(self.o_tree,h2,w2)
        osv=ttk.Scrollbar(obody,command=self.o_tree.yview); self.o_tree.configure(yscrollcommand=osv.set)
        self.o_tree.pack(side='left',fill='both',expand=True); osv.pack(side='left',fill='y')
        self.o_ec=[]
        # context menus
        self.smenu=tk.Menu(self.root,tearoff=0)
        for label,cmd in [('浏览源文件目录',self.sbrowse),('导出到输出目录',self.sexport),('导出并另存为',self.sexportas),('启动微信开发者工具并打开',self.sopentool),('删除导出产物',self.sdel)]:
            self.smenu.add_command(label=label,command=cmd)
        self.omenu=tk.Menu(self.root,tearoff=0)
        for label,cmd in [('浏览',self.obrowse),('启动微信开发者工具并打开',self.oopentool),('删除',self.odel)]:
            self.omenu.add_command(label=label,command=cmd)
        self.s_tree.bind('<Button-3>',self._smenu)
        self.o_tree.bind('<Button-3>',self._omenu)
        # bottom: status + log
        bot=tk.Frame(root,padx=8,pady=4); bot.pack(fill='x')
        self.status=tk.Label(bot,text='就绪',fg='#666'); self.status.pack(side='left')
        logf=tk.Frame(root,padx=8,pady=8); logf.pack(fill='both',expand=True)
        tk.Label(logf,text='日志').pack(anchor='w')
        self.log=tk.Text(logf,height=8,state='disabled')
        scb=tk.Scrollbar(logf,command=self.log.yview); self.log.configure(yscrollcommand=scb.set)
        self.log.pack(side='left',fill='both',expand=True); scb.pack(side='left',fill='y')
        root.protocol('WM_DELETE_WINDOW',self.on_close)
        self.refresh_scan(); self.refresh_out()

    def _cfg(self,t,h,w):
        for c in h:
            t.heading(c,text=h[c]); t.column(c,width=w[c],anchor='w' if c in('appid','name','newest','mtime') else 'center')

    def logline(self,s):
        self.log.configure(state='normal'); self.log.insert('end',s+'\n'); self.log.see('end'); self.log.configure(state='disabled'); self.root.update_idletasks()

    def _browse(self,d): 
        if os.path.isdir(d): os.startfile(d)
        else: messagebox.showinfo('提示','目录不存在: '+d)

    def _pickout(self):
        d=filedialog.askdirectory(initialdir=self.outVar.get())
        if d: self.outVar.set(d)

    def _require_outdir(self):
        d=self.outVar.get().strip()
        if d: return d
        messagebox.showinfo('提示','还没有设置输出目录,请现在选择一个。')
        d=filedialog.askdirectory(title='选择输出目录', initialdir=os.path.expanduser('~'))
        if d:
            self.outVar.set(d)   # trace 会自动写入 prefs.json,下次记住
            return d
        return ''

    def _rescan(self): self.refresh_scan()

    # ---- scan ----
    def refresh_scan(self):
        self.s_tree.delete(*self.s_tree.get_children()); self.logline('扫描所有用户缓存 ...')
        self.s_ec=scan(); self.status.config(text='共 %d 个小程序' % len(self.s_ec))
        for i,e in enumerate(self.s_ec):
            self.s_tree.insert('','end',iid=str(i),values=(i+1,e['appid'],e['name'],e['version'],e['main'],e['files'],round(e['size']/1048576,1),fmt(e['newest'])))
        self.logline('完成: %d 个小程序' % len(self.s_ec))
    def _sel_scan(self):
        sel=self.s_tree.selection()
        return (int(sel[0]) if sel and sel[0].isdigit() else None)
    def _entry(self):
        i=self._sel_scan()
        return self.s_ec[i] if i is not None and 0<=i<len(self.s_ec) else None
    def do_restore(self):
        e=self._entry()
        if not e: messagebox.showinfo('提示','请先在列表里选中要还原的小程序'); return
        outdir=self._require_outdir()
        if not outdir: return
        out=os.path.join(outdir,e['appid'])
        if os.path.isdir(out) and not self.forceVar.get():
            if not messagebox.askyesno('覆盖确认','输出目录已有该工程:\n%s\n\n是否覆盖重新导出?'%out):
                self.logline('已取消(目标已存在, 未勾选强制重导出)'); return
        self.status.config(text='还原中: '+e['appid']+' ...')
        threading.Thread(target=self._work,args=(e,outdir),daemon=True).start()
    def _work(self,e,outdir,act=None):
        try:
            out=restore(e,outdir,self.logline)
            self.root.after(0,lambda:(self.status.config(text='完成: '+e['appid']), self.refresh_out()))
            if act: self.root.after(0,lambda:act(out))
        except Exception as er:
            self.root.after(0,lambda:(self.status.config(text='失败: %s'%er), self.logline('  失败: %s'%er)))
    def _smenu(self,ev):
        iid=self.s_tree.identify_row(ev.y)
        if iid: self.s_tree.selection_set(iid)
        self.smenu.tk_popup(ev.x_root,ev.y_root)
    def sbrowse(self):
        e=self._entry()
        if e: self._browse(e['dir'])
    def sexport(self):
        e=self._entry()
        if e: self.do_restore()
    def sexportas(self):
        e=self._entry()
        if not e: return
        d=filedialog.askdirectory(title='导出并另存为',initialdir=self.outVar.get())
        if d: threading.Thread(target=self._work,args=(e,d),daemon=True).start()
    def sopentool(self):
        e=self._entry()
        if not e: return
        outdir=self._require_outdir()
        if not outdir: return
        out=os.path.join(outdir,e['appid'])
        if not os.path.isdir(out):
            self.status.config(text='先导出再打开 ...')
            threading.Thread(target=self._work,args=(e,self.outVar.get(),lambda o:open_devtools(o,self.logline)),daemon=True).start()
        else: open_devtools(out,self.logline)
    def sdel(self):
        e=self._entry()
        if not e: return
        outdir=self._require_outdir()
        if not outdir: return
        target=os.path.join(outdir,e['appid'])
        if not os.path.isdir(target): messagebox.showinfo('提示','输出目录下没有该 AppID 的导出产物'); return
        if messagebox.askyesno('确认删除','删除导出的工程?\n'+target):
            shutil.rmtree(target,ignore_errors=True); self.refresh_out(); self.logline('已删除导出产物: '+target)

    # ---- output ----
    def refresh_out(self):
        self.o_tree.delete(*self.o_tree.get_children()); O_ROOT=self.outVar.get().strip()
        rows=[]
        if not O_ROOT:
            self.status.config(text='未设置输出目录'); self.o_ec=[]; return
        if os.path.isdir(O_ROOT):
            for n in os.listdir(O_ROOT):
                p=os.path.join(O_ROOT,n)
                if os.path.isdir(p):
                    nm=n
                    try:
                        aj=json.load(open(os.path.join(p,'app.json'),encoding='utf-8-sig'))
                        nm=aj.get('window',{}).get('navigationBarTitleText') or n
                    except: pass
                    st=os.stat(p); rows.append(dict(appid=n,name=nm,size=dir_size(p),mtime=st.st_mtime,dir=p))
        rows=sorted(rows,key=lambda x:-x['mtime']); self.o_ec=rows
        for i,r in enumerate(rows):
            self.o_tree.insert('','end',iid=str(i),values=(r['appid'],r['name'],round(r['size']/1048576,1),fmt(r['mtime'])))
        self.status.config(text='输出目录共 %d 个工程' % len(rows))
    def _self_out(self):
        sel=self.o_tree.selection()
        return self.o_ec[int(sel[0])] if sel and sel[0].isdigit() and int(sel[0])<len(self.o_ec) else None
    def _omenu(self,ev):
        iid=self.o_tree.identify_row(ev.y)
        if iid: self.o_tree.selection_set(iid)
        self.omenu.tk_popup(ev.x_root,ev.y_root)
    def obrowse(self):
        r=self._self_out()
        if r: self._browse(r['dir'])
    def oopentool(self):
        r=self._self_out()
        if r: open_devtools(r['dir'],self.logline)
    def odel(self):
        r=self._self_out()
        if not r: return
        if messagebox.askyesno('确认删除','删除该导出的工程?\n'+r['dir']):
            shutil.rmtree(r['dir'],ignore_errors=True); self.refresh_out(); self.logline('已删除: '+r['dir'])
    def _clear_out(self):
        O_ROOT=self._require_outdir()
        if not O_ROOT: return
        if not os.path.isdir(O_ROOT): return
        if messagebox.askyesno('确认清空','清空输出目录下的所有已导出工程?\n'+O_ROOT):
            n=0
            for x in os.listdir(O_ROOT):
                p=os.path.join(O_ROOT,x)
                if os.path.isdir(p): shutil.rmtree(p,ignore_errors=True); n+=1
            self.refresh_out(); self.logline('已清空 %d 个工程' % n)

    def on_close(self):
        save_prefs({'out_root':self.outVar.get()}); self.root.destroy()

if __name__=='__main__':
    root=tk.Tk(); App(root); root.mainloop()
