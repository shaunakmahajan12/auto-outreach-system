export function linkedinUrl(value) {
  if (typeof value !== 'string' || /[\s\\\x00-\x1f]/.test(value)) throw new Error('Invalid profile URL');
  let url;
  try { url = new URL(value); }
  catch { throw new Error('The LinkedIn profile URL is missing or invalid.'); }
  if (url.protocol !== 'https:' || !['linkedin.com', 'www.linkedin.com'].includes(url.hostname) || url.username || url.password || url.port || !/^\/in\/[A-Za-z0-9_%-]+\/?$/.test(url.pathname)) throw new Error('Only LinkedIn profile URLs may be opened');
  return `https://www.linkedin.com${url.pathname.replace(/\/$/, '')}`;
}

export async function copyMessage(text, clipboard) {
  if (typeof text !== 'string' || !text) return {copied: false, copyError: 'The displayed draft is empty.'};
  try {
    await clipboard.writeText(text);
    return {copied: true, text};
  } catch {
    return {copied: false, text, copyError: 'Clipboard access was denied. Select the displayed text and copy it manually.'};
  }
}

export function openProfile(value, browser) {
  let url;
  try { url = linkedinUrl(value); }
  catch (error) { return {opened: false, openError: error instanceof Error ? error.message : 'The LinkedIn profile URL is missing or invalid.'}; }
  try {
    const popup = browser.open(url, '_blank');
    if (!popup) return {opened: false, url, openError: 'The profile did not open. Your browser may have blocked the new tab.'};
    popup.opener = null;
    return {opened: true, url};
  } catch {
    return {opened: false, url, openError: 'The profile could not be opened in a new tab.'};
  }
}

// Uses the displayed text directly and never records a sent event.
export async function copyAndOpen(prepared, browser, clipboard) {
  const opened = openProfile(prepared?.url, browser);
  const copied = await copyMessage(prepared?.text, clipboard);
  return {...opened, ...copied, prepared: {url: opened.url, text: prepared?.text}};
}
