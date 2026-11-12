import ctypes
import tkinter as tk
from tkinter import ttk, messagebox

import core

FONT = ('Microsoft YaHei UI', 10)

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

LABEL_BY_TYPE = {k: v['label'] for k, v in core.TYPES.items()}
TYPE_BY_LABEL = {v: k for k, v in LABEL_BY_TYPE.items()}

def run_gui():
    root = tk.Tk()
    root.title('快捷执行 (基础界面)')
    root.geometry('800x540')
    root.eval('tk::PlaceWindow . center')

    frame_left = tk.Frame(root, width=210)
    frame_left.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=10)
    tk.Label(frame_left, text='命令列表', font=(FONT[0], 10, 'bold')).pack(anchor=tk.W, pady=(0, 5))

    list_scroll = ttk.Scrollbar(frame_left)
    list_scroll.pack(side=tk.RIGHT, fill=tk.Y)
    listbox = tk.Listbox(frame_left, font=FONT, yscrollcommand=list_scroll.set, activestyle='none')
    listbox.pack(fill=tk.BOTH, expand=True)
    list_scroll.config(command=listbox.yview)

    frame_right = tk.Frame(root)
    frame_right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10, pady=10)

    tk.Label(frame_right, text='激活命令 (英文字母):').grid(row=0, column=0, sticky=tk.W, pady=4)
    entry_alias = tk.Entry(frame_right, font=FONT)
    entry_alias.grid(row=0, column=1, sticky=tk.EW, pady=4)

    tk.Label(frame_right, text='执行方式:').grid(row=1, column=0, sticky=tk.W, pady=4)
    type_box = ttk.Combobox(frame_right, state='readonly', font=FONT,
                            values=[LABEL_BY_TYPE[k] for k in core.TYPES])
    type_box.grid(row=1, column=1, sticky=tk.EW, pady=4)

    tk.Label(frame_right, text='工作目录:').grid(row=2, column=0, sticky=tk.W, pady=4)
    entry_cwd = tk.Entry(frame_right, font=FONT)
    entry_cwd.grid(row=2, column=1, sticky=tk.EW, pady=4)

    tk.Label(frame_right, text='描述:').grid(row=3, column=0, sticky=tk.W, pady=4)
    entry_desc = tk.Entry(frame_right, font=FONT)
    entry_desc.grid(row=3, column=1, sticky=tk.EW, pady=4)

    tk.Label(frame_right, text='内容 / 代码:').grid(row=4, column=0, sticky=tk.NW, pady=4)
    text_frame = tk.Frame(frame_right)
    text_frame.grid(row=4, column=1, sticky=tk.NSEW, pady=4)
    frame_right.rowconfigure(4, weight=1)
    frame_right.columnconfigure(1, weight=1)
    text_scroll = ttk.Scrollbar(text_frame)
    text_scroll.pack(side=tk.RIGHT, fill=tk.Y)
    text_code = tk.Text(text_frame, font=('Consolas', 10), yscrollcommand=text_scroll.set, undo=True)
    text_code.pack(fill=tk.BOTH, expand=True)
    text_scroll.config(command=text_code.yview)

    hint = tk.Label(frame_right, text='', anchor='w', fg='#8a8a8e', font=(FONT[0], 9))
    hint.grid(row=5, column=0, columnspan=2, sticky=tk.EW)

    btn_frame = tk.Frame(frame_right)
    btn_frame.grid(row=6, column=0, columnspan=2, sticky=tk.EW, pady=10)
    status = tk.Label(root, text='', anchor='w', fg='#666')
    status.pack(side=tk.BOTTOM, fill=tk.X, padx=10)

    state = {'commands': core.load_all_commands(), 'original': None,
             'raw': None, 'codes': {}, 'shown_type': 'python'}

    def stash_code():
        state['codes'][state['shown_type']] = text_code.get('1.0', tk.END).rstrip('\n')

    def refresh_list(keep=None):
        state['commands'] = core.load_all_commands()
        listbox.delete(0, tk.END)
        for item in state['commands']:
            label = LABEL_BY_TYPE.get(item['type'], item['type'])
            listbox.insert(tk.END, '%s  ·  %s' % (item['alias'], label))
        if keep:
            for i, item in enumerate(state['commands']):
                if item['alias'] == keep:
                    listbox.selection_set(i)
                    break

    def set_hint():
        spec = core.TYPES.get(TYPE_BY_LABEL.get(type_box.get(), 'python'), core.TYPES['python'])
        hint.config(text=spec['hint'])

    def on_type_change(_event=None):
        if state['raw'] is None:
            set_hint()
            return
        stash_code()
        new_type = TYPE_BY_LABEL.get(type_box.get(), 'python')
        text_code.delete('1.0', tk.END)
        text_code.insert(tk.END, state['codes'].get(new_type, ''))
        state['shown_type'] = new_type
        set_hint()

    def clear_form():
        listbox.selection_clear(0, tk.END)
        state['original'] = None
        state['raw'] = None
        state['codes'] = {}
        state['shown_type'] = 'python'
        entry_alias.config(state=tk.NORMAL)
        entry_alias.delete(0, tk.END)
        entry_cwd.delete(0, tk.END)
        entry_desc.delete(0, tk.END)
        type_box.set(LABEL_BY_TYPE['python'])
        text_code.delete('1.0', tk.END)
        set_hint()
        status.config(text='新建命令')

    def on_select(_event=None):
        sel = listbox.curselection()
        if not sel:
            return
        raw = core.load_command(state['commands'][sel[0]]['alias'])
        state['raw'] = raw
        state['original'] = raw['alias']
        state['codes'] = dict(raw.get('codes') or {})
        state['shown_type'] = raw['type']
        entry_alias.config(state=tk.NORMAL)
        entry_alias.delete(0, tk.END)
        entry_alias.insert(0, raw['alias'])
        entry_cwd.delete(0, tk.END)
        entry_cwd.insert(0, raw.get('cwd', ''))
        entry_desc.delete(0, tk.END)
        entry_desc.insert(0, raw.get('description', ''))
        type_box.set(LABEL_BY_TYPE.get(raw['type'], LABEL_BY_TYPE['python']))
        text_code.delete('1.0', tk.END)
        text_code.insert(tk.END, raw.get('code', ''))
        set_hint()
        status.config(text='正在编辑 %s' % raw['alias'])

    def save_item():
        payload = dict(state['raw'] or {})
        payload.pop('code', None)
        stash_code()
        payload.update({
            'alias': entry_alias.get(),
            'type': TYPE_BY_LABEL.get(type_box.get(), 'python'),
            'description': entry_desc.get(),
            'codes': state['codes'],
            'cwd': entry_cwd.get(),
        })
        ok, result = core.save_command(payload, state['original'])
        if not ok:
            messagebox.showwarning('无法保存', result)
            return
        state['original'] = result
        refresh_list(keep=result)
        status.config(text='已保存 %s' % result)

    def delete_item():
        sel = listbox.curselection()
        if not sel:
            messagebox.showwarning('提示', '请先在左侧选择要删除的命令。')
            return
        alias = state['commands'][sel[0]]['alias']
        if not messagebox.askyesno('确认', "确定要删除命令 '%s' 吗？\n对应的文件将被永久删除。" % alias):
            return
        ok, result = core.delete_command(alias)
        if not ok:
            messagebox.showerror('删除失败', result)
            return
        clear_form()
        refresh_list()
        status.config(text='已删除 %s' % alias)

    def run_item():
        sel = listbox.curselection()
        if not sel:
            messagebox.showwarning('提示', '请先在左侧选择要运行的命令。')
            return
        core.open_in_new_console(state['commands'][sel[0]]['alias'])

    def reveal():
        core.ensure_cmds_dir()
        import os
        os.startfile(core.CMDS_DIR)

    tk.Button(btn_frame, text='运行', command=run_item, width=8).pack(side=tk.LEFT, padx=2)
    tk.Button(btn_frame, text='+ 新建', command=clear_form, width=8).pack(side=tk.LEFT, padx=2)
    tk.Button(btn_frame, text='保存', command=save_item, width=8).pack(side=tk.LEFT, padx=2)
    tk.Button(btn_frame, text='删除', command=delete_item, width=8).pack(side=tk.LEFT, padx=2)
    tk.Button(btn_frame, text='数据目录', command=reveal, width=10).pack(side=tk.RIGHT, padx=2)

    type_box.bind('<<ComboboxSelected>>', on_type_change)
    listbox.bind('<<ListboxSelect>>', on_select)
    refresh_list()
    if state['commands']:
        listbox.selection_set(0)
        on_select()
    else:
        clear_form()
    root.mainloop()
