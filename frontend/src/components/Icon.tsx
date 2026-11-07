// Icon set from the mockup (24px stroke icons).
const IC: Record<string, string> = {
  play: '<path d="M7 4l13 8-13 8z"/>', pause: '<path d="M7 4h3v16H7zM14 4h3v16h-3z"/>',
  upload: '<path d="M12 16V4M7 9l5-5 5 5M4 20h16"/>', check: '<path d="M4 12l5 5L20 6"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
  video: '<rect x="3" y="6" width="13" height="12" rx="2"/><path d="M16 10l5-3v10l-5-3"/>',
  learn: '<path d="M3 8l9-4 9 4-9 4zM7 10v5c3 2 7 2 10 0v-5"/>', tag: '<path d="M3 12V4h8l10 10-8 8z"/><circle cx="7.5" cy="8.5" r="1"/>',
  vol: '<path d="M4 9h4l5-4v14l-5-4H4zM17 8c2 2 2 6 0 8"/>', out: '<path d="M9 4H5v16h4M16 8l4 4-4 4M20 12H9"/>',
  swap: '<path d="M4 8h14l-4-4M20 16H6l4 4"/>',
  split: '<path d="M12 3v18M5 8l-3 4 3 4M19 8l3 4-3 4"/>', flag: '<path d="M5 21V4M5 4h12l-2 4 2 4H5"/>',
  dl: '<path d="M12 4v12M7 11l5 5 5-5M4 20h16"/>', sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M21 13A9 9 0 1111 3a7 7 0 0010 10z"/>', heart: '<path d="M12 21s-7-4.5-9-9a5 5 0 019-3 5 5 0 019 3c-2 4.5-9 9-9 9z"/>',
  phone: '<rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/>', car: '<path d="M3 13l2-5h14l2 5v5H3zM7 18v2M17 18v2"/><circle cx="7.5" cy="14.5" r="1"/><circle cx="16.5" cy="14.5" r="1"/>',
  pot: '<path d="M4 10h16v6a4 4 0 01-4 4H8a4 4 0 01-4-4zM2 10h20M9 6c0-1 1-2 1-3M14 6c0-1 1-2 1-3"/>',
  full: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>', redo: '<path d="M20 7v5h-5M20 12a8 8 0 10-2.3 5.7"/>',
};

export const DOMAIN_ICON: Record<string, string> = { "First aid": "heart", "Phone repair": "phone", "Car care": "car", Cooking: "pot" };

export function Icon({ name, className = "i" }: { name: string; className?: string }) {
  return <svg className={className} viewBox="0 0 24 24" aria-hidden="true" dangerouslySetInnerHTML={{ __html: IC[name] || "" }} />;
}
