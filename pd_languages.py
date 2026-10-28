"""Shared RU/LT/EN presentation layer. Business values remain canonical."""
import json,re,html
from pathlib import Path
from html.parser import HTMLParser
from flask import request,render_template,make_response
ROOT=Path(__file__).resolve().parent
UI=json.loads((ROOT/'pd_translations.json').read_text())
LANGS={'ru','lt','en'}
def language():
    query=request.args.get('lang')
    cookie=request.cookies.get('pd_lang')
    return query if query in LANGS else cookie if cookie in LANGS else 'ru'
def response_for(content,lang):
    response=make_response(content)
    response.headers['Content-Language']=lang
    response.headers['Cache-Control']='private, no-store'
    response.headers['Vary']='Cookie'
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    if request.args.get('lang') in LANGS:
        response.set_cookie('pd_lang',lang,max_age=180*86400,secure=True,samesite='Lax')
    return response
class Markup(HTMLParser):
    def __init__(self,lang):
        super().__init__(convert_charrefs=False)
        self.lang=lang;self.words=UI.get(lang,{});self.parts=[];self.raw=None
    def text(self,s):
        stripped=s.strip()
        if stripped not in self.words:return s
        start=len(s)-len(s.lstrip());end=len(s.rstrip())
        return s[:start]+self.words[stripped]+s[end:]
    def start(self,tag):
        raw=self.get_starttag_text()
        if tag in ('script','style'):self.raw=tag
        if tag=='html':raw=re.sub(r'\blang=([\"\']).*?\1','lang="'+self.lang+'"',raw,count=1)
        if not self.raw:
            raw=re.sub(r'(\b(?:placeholder|aria-label|title|alt)\s*=\s*)([\"\'])(.*?)\2',lambda m:m[1]+m[2]+html.escape(self.text(html.unescape(m[3])),quote=True)+m[2],raw)
            raw=re.sub(r'\bhref=([\"\'])(/(?:privacy|legal|driver-privacy))\1',lambda m:'href='+m[1]+m[2]+'?lang='+self.lang+m[1],raw)
        self.parts.append(raw)
    def handle_starttag(self,tag,attrs):self.start(tag)
    def handle_startendtag(self,tag,attrs):self.start(tag)
    def handle_endtag(self,tag):
        self.parts.append('</'+tag+'>')
        if tag==self.raw:self.raw=None
    def handle_data(self,s):self.parts.append(s if self.raw else self.text(s))
    def handle_entityref(self,n):self.parts.append('&'+n+';')
    def handle_charref(self,n):self.parts.append('&#'+n+';')
    def handle_comment(self,s):self.parts.append('<!--'+s+'-->')
    def handle_decl(self,s):self.parts.append('<!'+s+'>')
def render_index():
    lang=language()
    content=render_template('index.html',pd_lang=lang,pd_ui=UI.get(lang,{}))
    parser=Markup(lang);parser.feed(content);parser.close()
    return response_for(''.join(parser.parts),lang)
def render_document(kind):
    if kind not in {'privacy','legal'}:raise ValueError('Unknown document')
    lang=language()
    return response_for(render_template(kind+'_'+lang+'.html'),lang)
