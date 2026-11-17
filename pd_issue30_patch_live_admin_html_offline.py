"""Issue #30: SHA-pinned, OFFLINE ONLY HTML dispatcher integration patch.

Returns modified HTML in memory after GET and checksum. Does not write live
template or expose real files. Only effective when full server routes and
review schema are simultaneously installed in an authorized future release.
"""
import hashlib

EXPECTED_SHA256="d475f5b08f9466eb41ab7dd20db7dde59aecdae059927fc880ee7ab7ab1bddc0"

class HtmlPatchMismatch(RuntimeError):
    pass

def patch_source(raw):
    if type(raw) is not bytes or hashlib.sha256(raw).hexdigest()!=EXPECTED_SHA256:
        raise HtmlPatchMismatch("Live admin HTML source changed; abort release")
    text=raw.decode("utf-8")
    start=text.find("async function pdLoadDriverApplications(){")
    end=text.find("\n}",start)
    if start<0 or end<0 or end-start>7000:
        raise HtmlPatchMismatch("Unexpected live dispatcher function")
    old=text[start:end+2]
    anchor="    const actions=document.createElement('div');actions.className='actions';"
    # The current template uses 4 spaces of indentation at the action line.
    if old.count("const actions=document.createElement('div');actions.className='actions';")!=1:
        raise HtmlPatchMismatch("Dispatcher action anchor mismatch")
    lookup=(
        "const pdReviewData=await api('/api/admin/driver-applications/'+"
        "Number(a.telegram_id)+'/document-reviews');"
        "const pdRequired=Object.keys(requiredPhotos);"
        "const pdDocsApproved=pdRequired.every(side=>"
        "pdReviewData.documents?.[side]?.status==='approved');"
    )
    new=old.replace("const actions=document.createElement('div');actions.className='actions';",
                    lookup+"const actions=document.createElement('div');actions.className='actions';",1)
    current="missingPhotos.length>0||a.status==='stage2'"
    if old.count(current)!=1:
        raise HtmlPatchMismatch("Live approve-button predicate changed")
    new=new.replace(current,current+"||!pdDocsApproved",1)
    suffix="row.append(actions);area.append(row)}"
    if old.count(suffix)!=1:
        raise HtmlPatchMismatch("Dispatcher row append anchor changed")
    extension=(
       "const reviewButton=document.createElement('button');"
       "reviewButton.type='button';reviewButton.className='secondary';"
       "reviewButton.textContent=pdL('Проверить документы');"
       "reviewButton.onclick=async()=>{"
       "try{"
       "const panel=document.createElement('section');row.append(panel);"
       "panel.addEventListener('pd-issue30-review-updated',async()=>{"
       "try{"
       "const updated=await api('/api/admin/driver-applications/'+Number(a.telegram_id)+'/document-reviews');"
       "const ready=Object.keys(requiredPhotos).every(s=>updated.documents?.[s]?.status==='approved');"
       "const approveButton=actions.querySelector('button');"
       "if(approveButton){"
       "approveButton.disabled=!ready||a.status==='stage2'||a.status==='approved';"
       "approveButton.setAttribute('aria-disabled',String(approveButton.disabled));"
       "if(!approveButton.disabled){"
       "approveButton.classList.remove('pd-approval-blocked');"
       "approveButton.removeAttribute('title');"
       "actions.querySelectorAll('.pd-approval-blocked-reason').forEach(n=>n.remove());"
       "}"
       "}"
       "}catch(e){message(pdL(e.message),true)}"
       "});"
       "const mod=await import('/static/pd_issue30_admin_review.js');"
       "await mod.mountIssue30Review(panel,Number(a.telegram_id),"
       "window.Telegram?.WebApp?.initData||'');"
       "}catch(e){message(pdL(e.message),true)}};"
       "actions.append(reviewButton);"
    )
    new=new.replace(suffix,extension+suffix,1)
    out=text[:start]+new+text[end+2:]
    if out.count("mountIssue30Review(")!=1 or out.count("!pdDocsApproved")!=1:
        raise HtmlPatchMismatch("Expected one opt-in admin panel mount and server review gate")
    if out.count("async function pdLoadDriverApplications(){")!=1:
        raise HtmlPatchMismatch("Dispatcher function duplicated")
    return out
