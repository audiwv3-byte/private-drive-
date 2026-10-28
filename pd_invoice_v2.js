/* PRIVATE DRIVE: authenticated invoice downloads and administrator issuance. */
function pdIT(ru,en,lt){return window.PD_LANG==='en'?en:window.PD_LANG==='lt'?lt:ru}
function pdInvoiceDialog(title){
 const dialog=document.createElement('dialog');dialog.className='pd-invoice-dialog';
 dialog.style.cssText='max-width:560px;width:92%;max-height:88vh;overflow:auto;background:#151515;color:#f3ebdc;border:1px solid #b59a60;border-radius:18px;padding:24px';
 const h=document.createElement('h2');h.textContent=title;dialog.append(h);
 const error=document.createElement('p');error.setAttribute('role','alert');error.style.color='#ffbb9d';
 const fields=document.createElement('div');dialog.append(fields,error);
 const buttons=document.createElement('div');buttons.className='actions';dialog.append(buttons);
 const close=document.createElement('button');close.type='button';close.className='secondary';close.textContent=pdIT('Закрыть','Close','Uždaryti');close.onclick=()=>dialog.close();buttons.append(close);
 dialog.addEventListener('close',()=>dialog.remove());document.body.append(dialog);
 return {dialog,fields,error,buttons};
}
function pdInvoiceField(box,name,label,value='',type='text'){
 const wrapper=document.createElement('label');wrapper.textContent=label;const input=document.createElement('input');input.type=type;input.name=name;input.value=value;input.maxLength=type==='number'?30:500;wrapper.append(input);box.append(wrapper);return input;
}
async function pdInvoiceSettings(){
 if(!admin)return;
 try{
 const saved=(await api('/api/admin/invoice-settings')).settings;
 const ui=pdInvoiceDialog(pdIT('Реквизиты для счетов','Invoice settings','Sąskaitų rekvizitai'));
 const controls={};
 const fields=[['seller_name',pdIT('Имя и фамилия продавца','Seller full name','Pardavėjo vardas ir pavardė')],['seller_address',pdIT('Полный адрес продавца','Seller full address','Visas pardavėjo adresas')],['seller_iv',pdIT('Номер индивидуальной деятельности','Individual activity number','Individualios veiklos pažymos numeris')],['seller_vat',pdIT('PVM-код','VAT ID','PVM kodas')]];
 for(const [key,label]of fields)controls[key]=pdInvoiceField(ui.fields,key,label,saved[key]||'');
 const label=document.createElement('label');label.textContent=pdIT('Актуальный режим PVM','Current VAT regime','Aktualus PVM režimas');const mode=document.createElement('select');
 for(const [value,text]of [['',pdIT('Выберите по данным VMI','Select according to VMI','Pasirinkite pagal VMI')],['standard21',pdIT('Обычный PVM — 21%','Standard VAT — 21%','Įprastas PVM — 21%')],['svs',pdIT('SVS в Литве — без начисления PVM','Lithuanian SVS — no VAT charged','SVS Lietuvoje — PVM neskaičiuojamas')],['manual',pdIT('Другая ставка — с основанием','Other rate — specify legal basis','Kitas tarifas — nurodykite pagrindą')]]){const o=document.createElement('option');o.value=value;o.textContent=text;mode.append(o)}
 mode.value=saved.tax_mode||'';label.append(mode);ui.fields.append(label);controls.tax_mode=mode;
 controls.tax_rate=pdInvoiceField(ui.fields,'tax_rate',pdIT('Ставка для другого режима, %','Other VAT rate, %','Kitas PVM tarifas, %'),saved.tax_rate||'','number');controls.tax_rate.min='0';controls.tax_rate.max='100';controls.tax_rate.step='0.01';
 controls.tax_basis=pdInvoiceField(ui.fields,'tax_basis',pdIT('Основание другой ставки','Legal basis for other rate','Kito tarifo teisinis pagrindas'),saved.tax_basis||'');
 const confirmLabel=document.createElement('label'),confirm=document.createElement('input');confirm.type='checkbox';confirm.style.width='auto';confirmLabel.append(confirm,document.createTextNode(' '+pdIT('Реквизиты и режим PVM проверены по актуальным данным','Details and VAT regime checked against current records','Rekvizitai ir PVM režimas patikrinti pagal aktualius duomenis')));ui.fields.append(confirmLabel);
 const save=document.createElement('button');save.type='button';save.textContent=pdIT('Сохранить реквизиты','Save settings','Išsaugoti rekvizitus');ui.buttons.prepend(save);
 save.onclick=async()=>{save.disabled=true;try{const payload={confirmed:confirm.checked};for(const[key,input]of Object.entries(controls))payload[key]=input.value;await api('/api/admin/invoice-settings',payload);ui.dialog.close();message(pdIT('Реквизиты сохранены','Settings saved','Rekvizitai išsaugoti'))}catch(e){ui.error.textContent=pdL(e.message)}finally{save.disabled=false}};
 ui.dialog.showModal();
 }catch(e){message(pdL(e.message),true)}
}
async function pdInvoiceIssue(orderId){
 if(!admin)return;
 try{
 const settings=(await api('/api/admin/invoice-settings')).settings;
 if(!settings.tax_mode||!settings.seller_address){message(pdIT('Сначала заполните реквизиты и режим PVM','Complete invoice settings and VAT regime first','Pirmiausia užpildykite rekvizitus ir PVM režimą'),true);await pdInvoiceSettings();return}
 const order=(pdOrdersCache||[]).find(o=>Number(o.id)===Number(orderId));
 const ui=pdInvoiceDialog(pdIT('Счёт по заказу №','Invoice for order #','Sąskaita užsakymui Nr. ')+orderId);
 const info=document.createElement('p');info.textContent=pdIT('Сумма включает PVM по выбранному режиму. Подтвердите применимость режима к этому маршруту. Выпущенный PDF сохраняется без последующего изменения.','The amount includes VAT under the selected regime. Confirm this regime applies to the route. The issued PDF is saved unchanged.','Suma apima PVM pagal pasirinktą režimą. Patvirtinkite jo taikymą šiam maršrutui. Išrašytas PDF išsaugomas nekeičiamas.');ui.fields.append(info);
 const name=pdInvoiceField(ui.fields,'buyer_name',pdIT('Имя и фамилия / название покупателя','Buyer full name / company','Pirkėjo vardas ir pavardė / pavadinimas'),order?.customer?.name||order?.name||'');
 const address=pdInvoiceField(ui.fields,'buyer_address',pdIT('Полный адрес покупателя','Buyer full address','Visas pirkėjo adresas'));
 const code=pdInvoiceField(ui.fields,'buyer_code',pdIT('Код компании, если применимо','Company code, if applicable','Įmonės kodas, jei taikoma'));
 const vat=pdInvoiceField(ui.fields,'buyer_vat',pdIT('PVM-код покупателя, если есть','Buyer VAT ID, if applicable','Pirkėjo PVM kodas, jei yra'));
 const confirmLabel=document.createElement('label'),confirm=document.createElement('input');confirm.type='checkbox';confirm.style.width='auto';confirmLabel.append(confirm,document.createTextNode(' '+pdIT('Реквизиты покупателя и режим PVM для этой поездки проверены','Buyer details and VAT regime for this trip verified','Pirkėjo rekvizitai ir šios kelionės PVM režimas patikrinti')));ui.fields.append(confirmLabel);
 const issue=document.createElement('button');issue.type='button';issue.textContent=pdIT('Выпустить и сохранить PDF','Issue and save PDF','Išrašyti ir išsaugoti PDF');ui.buttons.prepend(issue);
 issue.onclick=async()=>{issue.disabled=true;try{await api('/api/admin/invoices/'+Number(orderId),{buyer_name:name.value,buyer_address:address.value,buyer_code:code.value,buyer_vat:vat.value,tax_confirmed:confirm.checked});ui.dialog.close();await pdReload();await pdDownloadInvoice(orderId)}catch(e){ui.error.textContent=pdL(e.message)}finally{issue.disabled=false}};
 ui.dialog.showModal();
 }catch(e){message(pdL(e.message),true)}
}
async function pdDownloadInvoice(orderId){
 try{const r=await fetch('/api/invoices/'+Number(orderId)+'/pdf',{headers:{'X-Telegram-Init-Data':initData},cache:'no-store'});if(!r.ok){let body={};try{body=await r.json()}catch(e){}throw new Error(body.error||pdIT('PDF недоступен','PDF unavailable','PDF nepasiekiamas'))}const blob=await r.blob();if(!blob.type.includes('pdf'))throw new Error(pdIT('Некорректный формат файла','Invalid file format','Neteisingas failo formatas'));const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='PRIVATE_DRIVE_Order_'+Number(orderId)+'.pdf';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),60000)}catch(e){message(pdL(e.message),true)}
}
async function pdSendInvoice(orderId){try{await api('/api/admin/invoices/'+Number(orderId)+'/send',{});message(pdIT('PDF отправлен пассажиру в Telegram','PDF sent to passenger via Telegram','PDF išsiųstas keleiviui per Telegram'))}catch(e){message(pdL(e.message),true)}}
function pdInvoiceButton(label,action){const b=document.createElement('button');b.type='button';b.className='secondary pay-choice';b.textContent=label;b.onclick=action;return b}
function pdInvoiceAdminButtons(){
 if(!admin)return;
 const pane=$('pdFinancePane');if(!pane)return;
 if(!$('pdInvoiceSettingsButton')){const b=pdInvoiceButton(pdIT('Реквизиты для счетов','Invoice settings','Sąskaitų rekvizitai'),pdInvoiceSettings);b.id='pdInvoiceSettingsButton';pane.prepend(b)}
 pane.querySelectorAll(':scope > p').forEach(e=>{if(e.textContent.includes('PVM/SVS'))e.textContent=pdIT('Счета выпускаются после завершения поездки. PDF сохраняется в архиве и доступен пассажиру в разделе «Поездки».','Invoices are issued after a trip is completed. PDFs are archived and available to the passenger under Trips.','Sąskaitos išrašomos užbaigus kelionę. PDF saugomi archyve ir pasiekiami keleiviui skiltyje Kelionės.')});
 pane.querySelectorAll('#pdFinances .item').forEach(row=>{if(row.querySelector('[data-pd-invoice-issue]'))return;const match=row.textContent.match(/(?:Заказ\s*№|Order\s*#|Užsakymas\s*Nr\.?\s*)(\d+)/i);if(!match)return;const id=Number(match[1]),order=(pdOrdersCache||[]).find(o=>Number(o.id)===id);if(order?.status!=='Выполнена')return;const b=pdInvoiceButton(pdIT('Выпустить счёт PDF','Issue invoice PDF','Išrašyti PDF sąskaitą'),()=>pdInvoiceIssue(id));b.dataset.pdInvoiceIssue='1';row.append(b)})
}
async function pdInvoiceArchiveRefresh(){
 if(!admin)return;pdInvoiceAdminButtons();
 try{const rows=(await api('/api/admin/finance/invoices')).invoices||[],box=$('pdInvoiceArchive');if(!box)return;box.replaceChildren();const h=document.createElement('h2');h.textContent=pdIT('Архив счетов PDF','Invoice PDF archive','PDF sąskaitų archyvas');box.append(h);
 if(!rows.length){const p=document.createElement('p');p.textContent=pdIT('Счетов пока нет','No invoices yet','Sąskaitų dar nėra');box.append(p)}
 for(const r of rows){const item=document.createElement('article');item.className='item';const p=document.createElement('p');p.textContent=r.serial+' · №'+r.order_id+' · '+r.total_eur+' EUR · '+r.buyer_name;item.append(p);if(r.has_pdf){item.append(pdInvoiceButton(pdIT('Скачать PDF','Download PDF','Atsisiųsti PDF'),()=>pdDownloadInvoice(r.order_id)),pdInvoiceButton(pdIT('Отправить PDF пассажиру','Send PDF to passenger','Siųsti PDF keleiviui'),()=>pdSendInvoice(r.order_id)))}else{const note=document.createElement('p');note.textContent=pdIT('Старый документ без сохранённого PDF','Legacy record without archived PDF','Senas įrašas be išsaugoto PDF');item.append(note)}box.append(item)}
 }catch(e){message(pdL(e.message),true)}
}
const pdInvoicePreviousRender=pdRenderCurrent;pdRenderCurrent=function(){pdInvoicePreviousRender();pdInvoiceAdminButtons()};
const pdInvoicePreviousReload=pdReload;pdReload=async function(){await pdInvoicePreviousReload();await pdInvoiceArchiveRefresh()};
const pdInvoicePreviousOrders=loadOrders;loadOrders=async function(){await pdInvoicePreviousOrders();try{const rows=(await api('/api/invoices')).invoices||[];const ids=new Set(rows.map(r=>Number(r.order_id)));document.querySelectorAll('#orders article').forEach(row=>{const match=row.textContent.match(/№\s*(\d+)/);if(!match||!ids.has(Number(match[1]))||row.querySelector('[data-pd-invoice-download]'))return;const id=Number(match[1]),b=pdInvoiceButton(pdIT('Скачать счёт PDF','Download invoice PDF','Atsisiųsti PDF sąskaitą'),()=>pdDownloadInvoice(id));b.dataset.pdInvoiceDownload='1';row.append(b)})}catch(e){message(pdL(e.message),true)}};
pdInvoiceAdminButtons();
