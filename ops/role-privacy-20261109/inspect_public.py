"""Read-only public HTML diagnostic for privacy footer. No account/API access."""
import requests
url="https://wilsonpark.pythonanywhere.com/?privacy_inspect=20261109"
r=requests.get(url,timeout=30)
html=r.text
status='<p id="pdObStatus" role="status"></p>'
dup='<a href="/privacy" target="_blank" rel="noopener noreferrer">Политика конфиденциальности</a>'
a=html.find(status)
b=html.find("</section>",a) if a>=0 else -1
footer=html[a:b] if a>=0 and b>a else ""
print("PUBLIC_HTTP",r.status_code,"HTML_BYTES",len(r.content))
print("PAGE_CONDITIONS",{
 "status_at":a,
 "section_end":b,
 "upper_privacy_link":'href="/privacy"' in html[:a] if a>=0 else False,
 "duplicate_below_status":dup in footer,
 "contact_email":"mailto:eurobaltictransfer@gmail.com" in html,
 "contact_telegram":"https://t.me/PrivatDraiv" in html,
 "lang_selector":'id="pdLangSelect"' in html,
 "welcome_telegram":'id="pdWelcomeTelegram"' in html,
 "first_footer_start":repr(footer[:500]) if footer else None,
 "policy_bar": "pd-privacy-bar" in html,
})
