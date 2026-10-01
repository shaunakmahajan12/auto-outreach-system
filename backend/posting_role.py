"""Read a public posting without credentials or JavaScript execution."""
import asyncio
import http.client
import ipaddress
import json
import re
import socket
import ssl
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from backend.security import Unavailable, public_url

MAX_BYTES = 2_000_000


def missing_role(value):
    return not value or bool(re.fullmatch(r'\s*(?:unknown(?: role| title)?|unavailable|n/a|not (?:provided|supplied|recorded|established)|(?:role|title) not (?:provided|supplied|established))\s*', value, re.I))


class PostingParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.scripts=[]; self.headings=[]; self.script=None; self.heading=None

    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag=='script' and attrs.get('type','').lower()=='application/ld+json':self.script=[]
        if tag=='h1':self.heading=[]

    def handle_data(self, data):
        if self.script is not None:self.script.append(data)
        if self.heading is not None:self.heading.append(data)

    def handle_endtag(self, tag):
        if tag=='script' and self.script is not None:
            self.scripts.append(''.join(self.script));self.script=None
        if tag=='h1' and self.heading is not None:
            self.headings.append(' '.join(self.heading));self.heading=None


def clean_title(value):
    if not isinstance(value,str):return None
    value=' '.join(value.split())
    if not 3<=len(value)<=200 or missing_role(value):return None
    if re.search(r'\b(captcha|access denied|sign in|log in|not found|job not available|no longer available|job has expired|job expired|verify you|page unavailable|something went wrong)\b',value,re.I):return None
    if value.lower() in ('careers','jobs','job openings','search jobs','join our team','opportunities','career opportunities'):return None
    return value


def extract_title(html):
    parser=PostingParser();parser.feed(html)
    titles=set()
    def walk(node):
        if isinstance(node,list):
            for item in node:walk(item)
        elif isinstance(node,dict):
            kind=node.get('@type',[])
            if isinstance(kind,str):kind=[kind]
            if isinstance(kind,list) and any(t in ('JobPosting','https://schema.org/JobPosting','http://schema.org/JobPosting') for t in kind):
                title=clean_title(node.get('title'))
                if title:titles.add(title)
            for value in node.values():
                if isinstance(value,(dict,list)):walk(value)
    for script in parser.scripts:
        try:walk(json.loads(script))
        except (ValueError,RecursionError):continue
    if len(titles)==1:return titles.pop(),'JobPosting structured data'
    if len(titles)>1:raise Unavailable('This page lists multiple roles. Open the individual posting or enter the role manually.')
    # A single heading is a candidate for the user to review, never a silent guess.
    headings={title for text in parser.headings if (title:=clean_title(text))}
    if len(headings)==1:return headings.pop(),'Posting heading'
    raise Unavailable('Could not identify one role on this page. It may require login or JavaScript, or the posting may have expired. Enter the role manually.')


class PublicConnection(http.client.HTTPSConnection):
    def connect(self):
        addresses=socket.getaddrinfo(self.host,443,type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise Unavailable('The posting must resolve to a public internet address.')
        # Connect to the validated address, retaining the original hostname for TLS.
        raw=socket.create_connection((addresses[0][4][0],443),timeout=self.timeout)
        try:self.sock=self._context.wrap_socket(raw,server_hostname=self.host)
        except BaseException:
            raw.close();raise


def fetch_posting(url):
    for _ in range(5):
        public_url(url)
        parsed=urlsplit(url)
        connection=PublicConnection(parsed.hostname,timeout=8,context=ssl.create_default_context())
        try:
            path=parsed.path or '/'
            if parsed.query:path+='?'+parsed.query
            connection.request('GET',path,headers={'User-Agent':'OutreachPostingReader/1.0','Accept':'text/html','Accept-Encoding':'identity'})
            response=connection.getresponse()
            if response.status in (301,302,303,307,308):
                location=response.getheader('Location')
                if not location:raise Unavailable('The posting redirected without a destination.')
                url=urljoin(url,location);continue
            if response.status!=200:raise Unavailable(f'The posting returned HTTP {response.status}. Open the link or enter the role manually.')
            if 'html' not in response.getheader('Content-Type','').lower():raise Unavailable('The posting did not return an HTML page.')
            body=response.read(MAX_BYTES+1)
            if len(body)>MAX_BYTES:raise Unavailable('The posting page is too large to read. Enter the role manually.')
            return body.decode('utf-8',errors='replace'),url
        finally:connection.close()
    raise Unavailable('The posting redirected too many times. Enter the role manually.')


async def inspect_posting(url):
    try:
        html,source=await asyncio.wait_for(asyncio.to_thread(fetch_posting,url),timeout=30)
        role,method=extract_title(html)
        return {'role':role,'source_url':source,'method':method}
    except (ValueError,OSError,http.client.HTTPException,asyncio.TimeoutError):
        raise Unavailable('Could not read this public posting. Open the link or enter the role manually.') from None


async def fill_next_missing_role(store):
    """Attempt each missing role once per posting URL; never enqueue outreach."""
    from backend.store import now
    rows=store.rows('''SELECT a.source_application_id,a.role,a.job_url FROM applications a
        LEFT JOIN posting_role_checks c ON c.application_id=a.source_application_id AND c.posting_url=a.job_url
        WHERE a.job_url IS NOT NULL AND a.job_url!='' AND c.application_id IS NULL
        ORDER BY a.source_created_at DESC''')
    row=next((r for r in rows if missing_role(r['role'])),None)
    if not row:return False
    aid=row['source_application_id'];url=row['job_url']
    with store.db() as db:
        db.execute('INSERT OR REPLACE INTO posting_role_checks VALUES(?,?,?,?,?)',(aid,url,'checking',None,now()))
    try:
        result=await inspect_posting(url)
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            current=db.execute('SELECT role,job_url,missing_fields FROM applications WHERE source_application_id=?',(aid,)).fetchone()
            if not current or current['job_url']!=url or not missing_role(current['role']):
                db.execute("UPDATE posting_role_checks SET status='skipped' WHERE application_id=?",(aid,))
                return True
            save=result['method']=='JobPosting structured data'
            db.execute('INSERT OR REPLACE INTO posting_roles VALUES(?,?,?,?,?,?,?)',
                (aid,result['role'],result['source_url'],url,result['method'],now(),now() if save else None))
            if save:
                missing=[f for f in json.loads(current['missing_fields']) if f!='role']
                db.execute('UPDATE applications SET role=?,missing_fields=? WHERE source_application_id=?',(result['role'],json.dumps(missing),aid))
            db.execute('UPDATE posting_role_checks SET status=?,checked_at=? WHERE application_id=?',('saved' if save else 'needs_review',now(),aid))
    except Unavailable as error:
        with store.db() as db:
            db.execute("UPDATE posting_role_checks SET status='unavailable',error=?,checked_at=? WHERE application_id=?",(str(error),now(),aid))
    return True
