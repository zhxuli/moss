const ICONS = {
  "folder-plus": "<path d='M12 10v6' /> <path d='M9 13h6' /> <path d='M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z' />",
  "folder-open": "<path d='m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2' />",
  "folder": "<path d='M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z' />",
  "trash-2": "<path d='M10 11v6' /> <path d='M14 11v6' /> <path d='M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6' /> <path d='M3 6h18' /> <path d='M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2' />",
  "save": "<path d='M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z' /> <path d='M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7' /> <path d='M7 3v4a1 1 0 0 0 1 1h7' />",
  "undo-2": "<path d='M9 14 4 9l5-5' /> <path d='M4 9h10.5a5.5 5.5 0 0 1 5.5 5.5a5.5 5.5 0 0 1-5.5 5.5H11' />",
  "refresh-cw": "<path d='M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8' /> <path d='M21 3v5h-5' /> <path d='M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16' /> <path d='M8 16H3v5' />",
  "layers": "<path d='M12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83z' /> <path d='M2 12a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 12' /> <path d='M2 17a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 17' />",
  "eraser": "<path d='M21 21H8a2 2 0 0 1-1.42-.587l-3.994-3.999a2 2 0 0 1 0-2.828l10-10a2 2 0 0 1 2.829 0l5.999 6a2 2 0 0 1 0 2.828L12.834 21' /> <path d='m5.082 11.09 8.828 8.828' />",
  "circle-alert": "<circle cx='12' cy='12' r='10' /> <line x1='12' x2='12' y1='8' y2='12' /> <line x1='12' x2='12.01' y1='16' y2='16' />",
  "check": "<path d='M20 6 9 17l-5-5' />",
  "x": "<path d='M18 6 6 18' /> <path d='m6 6 12 12' />",
  "file-plus": "<path d='M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z' /> <path d='M14 2v5a1 1 0 0 0 1 1h5' /> <path d='M9 15h6' /> <path d='M12 18v-6' />",
  "history": "<path d='M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8' /> <path d='M3 3v5h5' /> <path d='M12 7v5l4 2' />",
  "pencil": "<path d='M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z' /> <path d='m15 5 4 4' />",
  "info": "<circle cx='12' cy='12' r='10' /> <path d='M12 16v-4' /> <path d='M12 8h.01' />",
  "plus": "<path d='M5 12h14' /> <path d='M12 5v14' />",
  "wand-2": "<path d='m21.64 3.64-1.28-1.28a1.21 1.21 0 0 0-1.72 0L2.36 18.64a1.21 1.21 0 0 0 0 1.72l1.28 1.28a1.2 1.2 0 0 0 1.72 0L21.64 5.36a1.2 1.2 0 0 0 0-1.72' /> <path d='m14 7 3 3' /> <path d='M5 6v4' /> <path d='M19 14v4' /> <path d='M10 2v2' /> <path d='M7 8H3' /> <path d='M21 16h-4' /> <path d='M11 3H9' />",
  "alert-triangle": "<path d='m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3' /> <path d='M12 9v4' /> <path d='M12 17h.01' />",
  "folder-input": "<path d='M2 9V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H20a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-1' /> <path d='M2 13h10' /> <path d='m9 16 3-3-3-3' />",
  "folder-search": "<path d='M10.7 20H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H20a2 2 0 0 1 2 2v4.1' /> <path d='m21 21-1.9-1.9' /> <circle cx='17' cy='17' r='3' />",
  "grip-vertical": "<circle cx='9' cy='12' r='1' /> <circle cx='9' cy='5' r='1' /> <circle cx='9' cy='19' r='1' /> <circle cx='15' cy='12' r='1' /> <circle cx='15' cy='5' r='1' /> <circle cx='15' cy='19' r='1' />",
  "copy": "<rect width='14' height='14' x='8' y='8' rx='2' ry='2' /> <path d='M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2' />",
  "edit-3": "<path d='M13 21h8' /> <path d='M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z' />",
  "trash": "<path d='M10 11v6' /> <path d='M14 11v6' /> <path d='M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6' /> <path d='M3 6h18' /> <path d='M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2' />",
  "file-plus-2": "<path d='M11.35 22H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.706.706l3.588 3.588A2.4 2.4 0 0 1 20 8v5.35' /> <path d='M14 2v5a1 1 0 0 0 1 1h5' /> <path d='M14 19h6' /> <path d='M17 16v6' />",
  "rotate-ccw": "<path d='M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8' /> <path d='M3 3v5h5' />",
  "check-circle-2": "<circle cx='12' cy='12' r='10' /> <path d='m16 9-5.5 5.5L8 12' />",
  "x-circle": "<circle cx='12' cy='12' r='10' /> <path d='m15 9-6 6' /> <path d='m9 9 6 6' />",
  "chevron-down": "<path d='m6 9 6 6 6-6' />",
  "chevron-right": "<path d='m9 18 6-6-6-6' />",
  "lock": "<rect width='18' height='11' x='3' y='11' rx='2' ry='2' /> <path d='M7 11V7a5 5 0 0 1 10 0v4' />",
};

function icon(name, cls) {
  const path = ICONS[name] || ICONS["info"];
  return '<svg class="' + (cls || "i") + '" viewBox="0 0 24 24" fill="none" ' +
         'stroke="currentColor" stroke-width="1.5" stroke-linecap="round" ' +
         'stroke-linejoin="round" aria-hidden="true">' + path + '</svg>';
}
