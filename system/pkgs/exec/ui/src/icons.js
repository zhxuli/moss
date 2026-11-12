const PATHS = {
  all: '<path d="M12 3.2 3.5 7 12 10.8 20.5 7z"/><path d="M3.5 12 12 15.8 20.5 12"/>'
     + '<path d="M3.5 16.6 12 20.4 20.5 16.6"/>',
  code: '<path d="M9 7.5 4.5 12 9 16.5"/><path d="M15 7.5 19.5 12 15 16.5"/>',
  shell: '<circle cx="12" cy="12" r="8.5"/><path d="M9.5 9.5 12 12l-2.5 2.5"/>',
  terminal: '<rect x="3" y="4.5" width="18" height="15" rx="3"/>'
          + '<path d="M7.5 10 10 12.2 7.5 14.4"/><path d="M13 14.4h4"/>',
  globe: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17"/>'
       + '<path d="M12 3.5c2.4 2.6 2.4 14.4 0 17-2.4-2.6-2.4-14.4 0-17z"/>',
  folder: '<path d="M3.5 7.2a2 2 0 0 1 2-2h3.3l1.9 2.1h7.8a2 2 0 0 1 2 2v6.5'
        + 'a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
  doc: '<path d="M6.5 3.5h6.6l4.9 4.9v11.1a1 1 0 0 1-1 1H6.5a1 1 0 0 1-1-1V4.5'
     + 'a1 1 0 0 1 1-1z"/><path d="M13 3.5v5h5"/>',
  expand: '<path d="M7 5.5 12 10.5 17 5.5"/><path d="M7 12.5 12 17.5 17 12.5"/>',
  collapse: '<path d="M7 17.5 12 12.5 17 17.5"/><path d="M7 10.5 12 5.5 17 10.5"/>',
};

export function iconFor(name) {
  return '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
       + 'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">'
       + (PATHS[name] || PATHS.all) + '</svg>';
}
