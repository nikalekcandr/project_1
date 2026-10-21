'use strict';
const KEY='genshtab-web-v1', START='2026-10-23', END='2026-12-31';
const modes={'Боевой':10,'Марш':7,'Тыловой':6,'Рубеж':4,'Оборона':3,'Увольнение':0};
const profiles=[{name:'Курсант',work:25,rest:5,text:'Мягкий вход: 25 минут работы, 5 минут отдыха.'},{name:'Солдат',work:50,rest:10,text:'Основной строй: 50 минут работы, 10 минут отдыха.'},{name:'Ветеран',work:75,rest:15,text:'Глубокая работа: 75 минут работы, 15 минут отдыха.'}];
const checks=[['order','Главный удар определён'],['phone','Телефон убран, место готово'],['focus','Первый штурм выполнен'],['body','Движение и питание — по плану'],['report','Вечерний доклад записан'],['sleep','Отбой назначен, сон от 7,5 часов']];
const phases=[{name:'Прорыв',start:'2026-10-23',end:'2026-11-01',days:10,text:'Собрать строй. Закрыть рубежи первого модуля, определить статус пересдач. SQL и расчистка учебных долгов.'},{name:'Наступление',start:'2026-11-02',end:'2026-11-29',days:28,text:'Модуль 2: ML, эконометрика, фининж и корпфин. Финальный проект по прогнозированию и рабочая версия Python-проекта.'},{name:'Решающий штурм',start:'2026-11-30',end:END,days:32,text:'Сессия и экзамены. План подготовки за 7 дней до рубежа. 31 декабря — итоговый разбор и курс на 2027 год.'}];
const $=id=>document.getElementById(id);
function localDate(d=new Date()){return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;}
function ordinal(s){return Date.parse(s+'T00:00:00Z')/86400000;}
function formatDate(s){return new Date(s+'T12:00:00').toLocaleDateString('ru-RU',{day:'numeric',month:'short'});}
function fresh(){return {schema:1,settings:{goal:630,work:50,rest:10,theme:'dark',density:'normal',sound:true,profile:'Солдат',modes:{...modes}},days:{},timer:null};}
let state=fresh(),storageOK=true;
try{const raw=localStorage.getItem(KEY);if(raw)state=validate(JSON.parse(raw));}catch(e){storageOK=false;}
function validate(raw){
 if(!raw||raw.schema!==1||!raw.settings||!raw.days||Array.isArray(raw.days)||typeof raw.days!=='object')throw Error('Неверный формат копии');
 const out=fresh(),s=raw.settings;
 for(const [k,min,max] of [['goal',1,1000],['work',5,120],['rest',1,60]]){if(!Number.isFinite(s[k])||s[k]<min||s[k]>max)throw Error('Некорректные настройки');out.settings[k]=s[k];}
 if(!['dark','light'].includes(s.theme)||!['normal','compact'].includes(s.density))throw Error('Неверная тема');
 Object.assign(out.settings,{theme:s.theme,density:s.density,sound:!!s.sound,profile:profiles.some(p=>p.name===s.profile)?s.profile:'Солдат'});
 for(const k of Object.keys(modes)){const n=s.modes?.[k];if(n!==undefined){if(!Number.isFinite(n)||n<0||n>16)throw Error('Некорректная норма');out.settings.modes[k]=n;}}
 for(const [key,d] of Object.entries(raw.days)){
  if(!/^\d{4}-\d{2}-\d{2}$/.test(key)||!Number.isFinite(ordinal(key))||!d||typeof d!=='object'||Array.isArray(d))throw Error('Неверная запись дня');
  if(Object.keys(out.days).length>=10000)throw Error('Слишком много записей');
  const n=Number(d.minutes||0);if(!Number.isFinite(n)||n<0||n>100000)throw Error('Неверное время');
  out.days[key]={order:String(d.order||'').slice(0,500),report:String(d.report||'').slice(0,3000),done:!!d.done,minutes:n,checks:{},mode:Object.hasOwn(modes,d.mode)?d.mode:defaultMode(key)};
  for(const [k] of checks)out.days[key].checks[k]=!!d.checks?.[k];
 }
 if(raw.timer){const t=raw.timer;if(typeof t!=='object'||!['work','rest'].includes(t.kind)||!Number.isFinite(t.duration)||t.duration<1||t.duration>7200||!Number.isFinite(t.remaining)||t.remaining<0||t.remaining>7200||typeof t.running!=='boolean'||!Number.isFinite(t.end)||!/^\d{4}-\d{2}-\d{2}$/.test(t.day)||typeof t.id!=='string')throw Error('Неверный таймер');out.timer={...t};}
 return out;
}
function defaultMode(key){const wd=new Date(key+'T12:00:00').getDay();return wd===0?'Тыловой':wd===4?'Марш':'Боевой';}
let today=localDate();
function day(key=today){return state.days[key]??(state.days[key]={order:'',report:'',done:false,minutes:0,checks:{},mode:defaultMode(key)});}
function save(){try{localStorage.setItem(KEY,JSON.stringify(state));storageOK=true;}catch(e){storageOK=false;toast('Не удалось сохранить. Экспортируй данные: хранилище браузера недоступно.');}}
let toastTimeout;
function toast(text){$('toast').textContent=text;$('toast').classList.add('show');clearTimeout(toastTimeout);toastTimeout=setTimeout(()=>$('toast').classList.remove('show'),4500);}
function applyAppearance(){document.documentElement.dataset.theme=state.settings.theme;document.documentElement.dataset.density=state.settings.density;}
const names={dashboard:['СТАВКА','Не ждать. Действовать.','70 дней, чтобы превратить намерения в результат.'],plan:['ПЛАН ОПЕРАЦИИ','От первого шага — до рубежа.','Три этапа. Десять недель. Ни одного потерянного результата.'],soldier:['РЕЖИМ СОЛДАТА','Приказ принят.','Настрой строй под себя. Дисциплина должна работать на тебя.'],journal:['БОЕВОЙ ЖУРНАЛ','Зафиксировать. Сделать вывод.','Честный доклад важнее красивой статистики.'],settings:['НАСТРОЙКИ','Свой порядок. Свой темп.','Настраивай нагрузку под жизнь, а не жизнь под счётчик.']};
let page='dashboard';
function navigate(key){if(!names[key])return;page=key;document.querySelectorAll('.page').forEach(el=>el.hidden=el.id!==key);document.querySelectorAll('[data-page]').forEach(el=>{el.classList.toggle('active',el.dataset.page===key);if(el.dataset.page===key)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');});const [name,title,sub]=names[key];$('page-name').textContent=name;$('title').textContent=title;$('subtitle').textContent=sub;$('settings-shortcut').hidden=key==='settings';if(key==='settings')renderSettings();if(key==='journal')renderJournal();if(key==='plan')renderCalendar();window.scrollTo({top:0,behavior:'instant'});}
document.querySelectorAll('[data-page]').forEach(b=>b.onclick=()=>navigate(b.dataset.page));document.querySelectorAll('[data-go]').forEach(b=>b.onclick=()=>navigate(b.dataset.go));$('settings-shortcut').onclick=()=>navigate('settings');
function renderPhases(){for(const id of ['phase-preview','phase-full']){$(id).replaceChildren();phases.forEach((p,i)=>{const a=document.createElement('article');a.className='phase'+(today>=p.start&&today<=p.end?' current':'');a.innerHTML=`<div class="phase-top"><span>ЭТАП 0${i+1}</span><span>${today>p.end?'РУБЕЖ ПРОЙДЕН':today>=p.start?'В ОПЕРАЦИИ':'ВПЕРЕДИ'}</span></div><h3>${p.name}</h3><p>${p.text}</p><div class="phase-days">${formatDate(p.start)} — ${formatDate(p.end)} <span> / ${p.days} дней</span></div>`;$(id).append(a);});}}
function renderChecks(){const d=day();$('daily-checks').replaceChildren();for(const [key,text] of checks){const l=document.createElement('label');l.className='daily-check';const input=document.createElement('input');input.type='checkbox';input.checked=!!d.checks[key];input.onchange=()=>{day().checks[key]=input.checked;save();renderMetrics();};l.append(input,document.createTextNode(text));$('daily-checks').append(l);}}
function renderMetrics(){const d=day(),days=Math.max(0,Math.min(70,ordinal(today)-ordinal(START)+1));$('day-number').textContent=String(days).padStart(2,'0');$('day-progress').value=days;$('days-caption').textContent=today<START?`До старта ${ordinal(START)-ordinal(today)} дн.`:today>END?'Кампания завершена':`Ещё ${70-days} дней после сегодняшнего`;$('campaign-status').textContent=today<START?'ПОДГОТОВКА К РАЗВЁРТЫВАНИЮ':today>END?'ОПЕРАЦИЯ ЗАВЕРШЕНА':'ОПЕРАЦИЯ ИДЁТ';const total=Object.entries(state.days).filter(([k])=>k>=START&&k<=END).reduce((n,[,v])=>n+v.minutes,0)/60;$('total-hours').textContent=Number(total.toFixed(1));$('hours-goal').textContent=`/ ${state.settings.goal} ч`;$('hours-progress').max=state.settings.goal;$('hours-progress').value=total;const left=Math.max(1,ordinal(END)-Math.max(ordinal(START),ordinal(today))+1);$('pace-caption').textContent=today>END?'Итог кампании':`Осталось ${Math.max(0,state.settings.goal-total).toFixed(1)} ч · ${(Math.max(0,state.settings.goal-total)/left).toFixed(1)} ч/день`;const n=checks.filter(([k])=>d.checks[k]).length;$('readiness').textContent=Math.round(n/6*100);$('ready-progress').value=n/6*100;$('check-count').textContent=`${n} / 6`;$('mode-label').textContent=d.mode;$('day-mode').value=d.mode;$('mode-caption').textContent=`Норма: ${state.settings.modes[d.mode]} ч · можно изменить`;$('today-focus').textContent=`${Math.round(d.minutes)} мин`;$('today-date').textContent=new Date(today+'T12:00:00').toLocaleDateString('ru-RU',{day:'numeric',month:'long'}).toUpperCase();}
function renderDay(){const d=day();$('order').value=d.order;$('order-done').checked=d.done;$('report').value=d.report;renderChecks();renderMetrics();}
for(const [id,key] of [['order','order'],['report','report']])$(id).oninput=()=>{day()[key]=$(id).value;save();};$('order-done').onchange=()=>{day().done=$('order-done').checked;save();};$('day-mode').onchange=()=>{day().mode=$('day-mode').value;save();renderMetrics();};$('to-order').onclick=()=>{$('order').scrollIntoView({behavior:'smooth',block:'center'});$('order').focus();};$('soldier-start').onclick=()=>{navigate('dashboard');$('order').focus();};$('defense').onclick=()=>{day().mode='Оборона';save();renderMetrics();toast('Оборона объявлена. Снизь нагрузку и восстановись.');navigate('dashboard');};
function renderProfiles(){$('profiles').replaceChildren();for(const p of profiles){const b=document.createElement('button');b.className='profile'+(state.settings.profile===p.name?' active':'');b.innerHTML=`<b>${p.name} ${state.settings.profile===p.name?'✓':''}</b><small>${p.text}</small>`;b.onclick=()=>{if(state.timer?.running){toast('Сначала приостанови текущий штурм.');return;}Object.assign(state.settings,{profile:p.name,work:p.work,rest:p.rest});state.timer=null;save();renderTimer();renderProfiles();toast(`Профиль «${p.name}» принят`);};$('profiles').append(b);}}
function newTimer(kind='work'){const duration=(kind==='work'?state.settings.work:state.settings.rest)*60;return {id:String(Date.now())+Math.random(),kind,duration,remaining:duration,running:false,end:0,day:today};}
function remaining(){const t=state.timer;return !t?state.settings.work*60:t.running?Math.max(0,Math.ceil((t.end-Date.now())/1000)):t.remaining;}
function renderTimer(){const t=state.timer,n=remaining();$('timer').textContent=`${String(Math.floor(n/60)).padStart(2,'0')}:${String(n%60).padStart(2,'0')}`;$('timer-start').textContent=t?.running?'Ⅱ Пауза':t?.kind==='rest'?'▶ Начать перерыв':t&&t.remaining<t.duration?'▶ Продолжить':'▶ Начать штурм';$('timer-state').textContent=t?.running?(t.kind==='rest'?'ВОССТАНОВЛЕНИЕ':'ШТУРМ ИДЁТ'):'ОЖИДАЕТ ПРИКАЗА';$('timer-hint').textContent=t?.kind==='rest'?'Встань. Вода. Движение.':'Телефон в сторону. Только задача.';}
$('timer-start').onclick=()=>{if(!state.timer)state.timer=newTimer();const t=state.timer;if(t.running){t.remaining=remaining();t.running=false;}else{t.end=Date.now()+t.remaining*1000;t.running=true;}save();renderTimer();};$('timer-reset').onclick=()=>{if(state.timer&&(state.timer.running||state.timer.remaining<state.timer.duration)&&!confirm('Прервать текущий блок? Незавершённое время не будет засчитано.'))return;state.timer=null;save();renderTimer();};
function beep(){if(!state.settings.sound)return;try{const ctx=new (window.AudioContext||window.webkitAudioContext)();const osc=ctx.createOscillator(),gain=ctx.createGain();osc.connect(gain);gain.connect(ctx.destination);gain.gain.value=.08;osc.frequency.value=660;osc.start();osc.stop(ctx.currentTime+.3);osc.onended=()=>ctx.close();}catch(e){/* звук может быть заблокирован браузером */}}
let finishing=false;
async function finishTimer(){
 if(finishing)return;
 finishing=true;
 const finish=()=>{
  // Внутри Web Lock читаем актуальное состояние: начисляет только одна вкладка.
  try{const raw=localStorage.getItem(KEY);if(raw)state=validate(JSON.parse(raw));}catch(e){/* в памяти остаётся действующий таймер */}
  const t=state.timer;
  if(!t?.running||remaining()>0)return;
  if(t.kind==='work'){
   const d=day(t.day);d.minutes+=t.duration/60;d.checks.focus=true;state.timer=newTimer('rest');
   toast('Штурм завершён. Время записано. Сделай перерыв.');
  }else{state.timer=newTimer('work');toast('Перерыв завершён. Готов к следующему штурму?');}
  save();beep();renderMetrics();renderChecks();
  if(page==='journal')renderJournal();
 };
 try{if(navigator.locks)await navigator.locks.request(KEY+'-timer',finish);else finish();}
 finally{finishing=false;renderTimer();}
}
function tick(){
 const next=localDate();
 if(today!==next){today=next;renderDay();renderPhases();if(page==='plan')renderCalendar();if(page==='journal')renderJournal();}
 if(state.timer?.running&&remaining()<=0)finishTimer();
 renderTimer();
 $('clock').textContent=new Date().toLocaleDateString('ru-RU',{day:'2-digit',month:'short'})+' / '+new Date().toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'});
}

function renderCalendar(){$('campaign-grid').replaceChildren();for(let i=0;i<70;i++){const key=new Date((ordinal(START)+i)*86400000).toISOString().slice(0,10),d=state.days[key];const b=document.createElement('button');b.className='day-cell'+(d?.done?' done':d&&(d.order||d.report||d.minutes)?' logged':'')+(key===today?' today':'');b.innerHTML=`${String(i+1).padStart(2,'0')}<small>${formatDate(key)}</small>`;b.setAttribute('aria-label',`${formatDate(key)}, день ${i+1}${d?.done?', главный удар выполнен':''}`);b.onclick=()=>{$('selected-day').hidden=false;$('selected-day').textContent=`День ${i+1} · ${formatDate(key)}\n${d?.order||'Приказ не записан'}\n${d?.report||'Доклада пока нет'}\nФокус: ${Math.round(d?.minutes||0)} мин${d?.done?' · Главный удар выполнен':''}`;};$('campaign-grid').append(b);}}
function renderJournal(){$('journal-list').replaceChildren();const entries=Object.entries(state.days).filter(([,d])=>d.report||d.order||d.minutes).sort(([a],[b])=>b.localeCompare(a));if(!entries.length){$('journal-list').textContent='Пока чисто. Первый приказ — начало истории.';return;}for(const [key,d] of entries.slice(0,100)){const a=document.createElement('article'),b=document.createElement('b'),p=document.createElement('p'),small=document.createElement('small');b.textContent=`${formatDate(key)} · ${d.mode}`;p.textContent=[d.order,d.report].filter(Boolean).join('\n');small.textContent=`${Math.round(d.minutes)} мин фокуса${d.done?' · Главный удар выполнен':''}`;a.append(b,p,small);$('journal-list').append(a);}}
$('add-time').onclick=()=>{const n=Number($('manual-minutes').value);if(!Number.isFinite(n)||n<1||n>720){toast('Введи от 1 до 720 минут.');return;}if(day().report.trim().length<10){toast('Сначала запиши конкретный результат в доклад (от 10 знаков).');return;}day().minutes+=n;$('manual-minutes').value='';save();renderMetrics();renderJournal();toast('Время и результат записаны.');};
function renderSettings(){const f=$('settings-form');for(const k of ['goal','work','rest','theme','density'])f.elements[k].value=state.settings[k];f.elements.sound.checked=state.settings.sound;$('mode-settings').replaceChildren();for(const k of Object.keys(modes)){const l=document.createElement('label'),i=document.createElement('input');i.type='number';i.min=0;i.max=16;i.step=.5;i.value=state.settings.modes[k];i.setAttribute('aria-label',`Норма ${k}, часов`);i.onchange=()=>{if(!i.value.trim()||!i.checkValidity()){i.value=state.settings.modes[k];toast('Норма: от 0 до 16 часов, шаг 0,5.');return;}state.settings.modes[k]=Number(i.value);save();renderMetrics();};l.append(document.createTextNode(k),i);$('mode-settings').append(l);}}
$('settings-form').onsubmit=e=>{e.preventDefault();const f=e.currentTarget;if(state.timer?.running&&(Number(f.elements.work.value)!==state.settings.work||Number(f.elements.rest.value)!==state.settings.rest)){toast('Приостанови штурм перед изменением длительности.');return;}const changed=Number(f.elements.work.value)!==state.settings.work||Number(f.elements.rest.value)!==state.settings.rest;for(const k of ['goal','work','rest'])state.settings[k]=Number(f.elements[k].value);for(const k of ['theme','density'])state.settings[k]=f.elements[k].value;state.settings.sound=f.elements.sound.checked;if(changed)state.timer=null;save();applyAppearance();renderMetrics();renderTimer();toast('Настройки штаба сохранены.');};
function exportData(){const blob=new Blob([JSON.stringify(state,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`genshtab-70-${today}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
$('export').onclick=exportData;$('export-side').onclick=exportData;
$('import').onchange=async e=>{const file=e.target.files[0];if(!file)return;try{if(file.size>5e6)throw Error('Размер копии — не более 5 МБ');const candidate=validate(JSON.parse(await file.text()));if(!confirm('Заменить текущий веб-журнал данными из копии? Сначала рекомендуем экспортировать текущие записи.'))return;state=candidate;save();applyAppearance();renderDay();renderSettings();renderProfiles();renderPhases();tick();toast('Копия восстановлена.');}catch(err){toast('Импорт отклонён: '+err.message);}finally{e.target.value='';}};
// Несколько открытых вкладок не должны одновременно начислять один штурм.
window.addEventListener('storage',e=>{if(e.key!==KEY||!e.newValue)return;try{state=validate(JSON.parse(e.newValue));applyAppearance();renderDay();renderProfiles();renderTimer();if(page==='journal')renderJournal();if(page==='plan')renderCalendar();if(page==='settings')renderSettings();}catch(err){toast('Не удалось прочитать изменения из другой вкладки.');}});
applyAppearance();renderDay();renderProfiles();renderPhases();tick();setInterval(tick,500);if(!storageOK)toast('Хранилище недоступно или копия повреждена. Сделай экспорт перед закрытием.');
