'use strict';
const $ = id => document.getElementById(id);
let csrfToken = '', user = null, authMode = 'login', page = 1, pages = 1;
let selected = null, selectionVersion = 0, editId = null, inlineAction = null, reportId = null;
let listVersion = 0, adminVersion = 0, reportVersion = 0;
const message = (text, tone='info') => { $('message').textContent = text; $('message').hidden=!text; $('message').dataset.tone=tone; };
function focusSection(id){ $(id).scrollIntoView({block:'start',behavior:'smooth'}); const heading=$(id).querySelector('[tabindex]'); if(heading) heading.focus({preventScroll:true}); }
function emptyState(list,title,description=''){ const li=document.createElement('li'); li.className='empty-state'; const icon=document.createElement('span');icon.className='empty-symbol';icon.textContent='☰';icon.setAttribute('aria-hidden','true');const strong=document.createElement('strong');strong.textContent=title;const text=document.createElement('span');text.textContent=description;li.append(icon,strong,text);list.append(li); }
const show = id => { for (const name of ['auth','welcome','board','admin']) $(name).hidden = name !== id; if(id!=='board')listVersion++;if(id!=='admin'){adminVersion++;reportVersion++;} };
const values = form => Object.fromEntries(new FormData(form));
async function refreshCSRF(){ const r=await fetch('/api/auth/csrf'); csrfToken=(await r.json()).csrf_token; }
async function api(path, method='GET', body){
  const response=await fetch('/api'+path,{method,headers:{'Content-Type':'application/json','X-CSRF-Token':csrfToken},body:body===undefined?undefined:JSON.stringify(body)});
  let data; try{data=await response.json();}catch{throw Error('서버 응답을 읽지 못했습니다. 잠시 후 다시 시도해주세요.');}
  if(!response.ok){ if(response.status===401 && user){user=null;closeDetail();navigation();mode('login');} throw Error((data.detail||'요청에 실패했습니다.')+(response.status===429?' '+response.headers.get('Retry-After')+'초 후 재시도하세요.':'')); }
  return data;
}
function navigation(){ $('navigation').hidden=!user; $('guest-label').hidden=!!user; $('nickname').textContent=user?.nickname||''; $('admin-link').hidden=user?.role!=='ADMIN'; if(user?.role!=='ADMIN'){adminVersion++;reportVersion++;$('rules').replaceChildren();$('reports').replaceChildren();$('report-detail').hidden=true;$('report-form').reset();$('report-target').textContent='';$('report-reason').textContent='';$('report-handler').textContent='';reportId=null;} }
function button(text, action){const b=document.createElement('button');b.type='button';b.textContent=text;b.addEventListener('click',()=>run(action,b));return b;}
async function run(action, control){if(control)control.disabled=true;message('');try{await action();}catch(e){message(e.message,'error');$('message').scrollIntoView({block:'nearest'});}finally{if(control)control.disabled=control.id==='prev'?page<=1:control.id==='next'?page>=pages:false;}}
function bind(id,action){$(id).addEventListener('click',e=>run(action,e.currentTarget));}
function form(id,action){$(id).addEventListener('submit',async e=>{e.preventDefault();const target=e.target;if(target.dataset.busy==='true')return;target.dataset.busy='true';try{await run(()=>action(values(target),target),e.submitter||target.querySelector('button[type="submit"],button:not([type])'));}finally{target.dataset.busy='false';}});}
function mode(name){
  authMode=name;show('auth');$('auth-form').reset();
  $('nickname-field').hidden=name!=='signup';$('password-field').hidden=name==='forgot';$('forgot-note').hidden=name!=='forgot';
  $('auth-form').elements.password.required=name!=='forgot';$('auth-form').elements.nickname.required=name==='signup';
  $('auth-form').elements.password.autocomplete=name==='signup'?'new-password':'current-password';
  $('auth-form').elements.password.minLength=name==='signup'?8:1;
  $('auth-title').textContent={login:'로그인',signup:'회원가입',forgot:'비밀번호 찾기'}[name];
  $('auth-description').textContent={login:'다시 만나 반가워요. 이야기를 이어가 볼까요?',signup:'새로운 이야기를 함께 나눌 준비가 되셨나요?',forgot:'비밀번호 찾기 화면을 미리 확인해보세요.'}[name];
  $('auth-submit').textContent=name==='forgot'?'목업 확인':$('auth-title').textContent;
  for(const item of ['login','signup','forgot'])$(item+'-mode').setAttribute('aria-current',String(item===name));
  message('');
}
function closeDetail(){selected=null;editId=null;selectionVersion++;$('detail').hidden=true;$('editor').hidden=true;$('inline').hidden=true;inlineAction=null;$('post-form').reset();$('inline-fields').replaceChildren();$('comment-form').reset();$('post-title').textContent='';$('post-content').textContent='';$('comments').replaceChildren();$('post-actions').replaceChildren();$('post-form').elements.password.required=false;}
async function loadPosts(){
  const version=++listVersion;
  const query=new URLSearchParams({...values($('search-form')),page});
  const data=await api('/posts?'+query);
  if(version!==listVersion||!user)return;
  page=data.page;pages=data.pages;
  const list=$('posts');list.replaceChildren();
  $('post-count').textContent=String(data.total);
  const searching=!!values($('search-form')).q.trim();
  $('list-summary').textContent=searching?'검색 결과 · 최신순':'최신 글부터 · 10개씩 보기';
  if(!data.items.length)emptyState(list,searching?'검색 결과가 없습니다.':'아직 등록된 이야기가 없어요.',searching?'다른 검색어로 다시 찾아보세요.':'첫 번째 이야기를 남겨보세요.');
  for(const post of data.items){
    const li=document.createElement('li');const link=button('',()=>openPost(post.id));link.className='post-link';
    const title=document.createElement('span');title.textContent=post.title;
    const arrow=document.createElement('span');arrow.textContent='›';arrow.className='row-arrow';arrow.setAttribute('aria-hidden','true');
    link.append(title,arrow);link.setAttribute('aria-label',post.title);link.dataset.postId=post.id;li.append(link);list.append(li);
  }
  $('page-info').textContent=page+' / '+pages;
  $('prev').disabled=page<=1;$('next').disabled=page>=pages;
  $('page-numbers').replaceChildren();
  const start=Math.max(1,Math.min(page-2,pages-4));
  for(let number=start;number<=Math.min(pages,start+4);number++){
    const link=button(String(number),async()=>{page=number;closeDetail();await loadPosts();});
    link.setAttribute('aria-label',number+'페이지');if(number===page)link.setAttribute('aria-current','page');
    $('page-numbers').append(link);
  }
}
async function enterBoard(){closeDetail();show('board');await loadPosts();}
async function openPost(id){closeDetail();selected=id;const version=selectionVersion;const [post,comments]=await Promise.all([api('/posts/'+id),api('/posts/'+id+'/comments')]);if(version!==selectionVersion||selected!==id)return;$('editor').hidden=true;$('detail').hidden=false;for(const link of $('posts').querySelectorAll('.post-link'))link.setAttribute('aria-current',String(link.dataset.postId===id));$('post-title').textContent=post.title;$('post-content').textContent=post.content;const actions=$('post-actions');actions.replaceChildren();if(post.is_owner){actions.append(button('수정',()=>startPostEdit(id)),button('삭제',()=>ask('게시글 삭제 확인',[['password','비밀번호','password']],async data=>{await api('/posts/'+id+'/delete','POST',data);closeDetail();await loadPosts();message('삭제했습니다.');})));}actions.append(button('신고',()=>reportTarget('POST',id)),button('닫기',()=>closeDetail()));const list=$('comments');list.replaceChildren();$('comment-count').textContent=String(comments.length);if(!comments.length)emptyState(list,'아직 댓글이 없어요.','첫 댓글로 이야기를 이어가세요.');for(const comment of comments){const li=document.createElement('li');const content=document.createElement('p');content.className='multiline';content.classList.add('comment-text');content.textContent=comment.content;const author=document.createElement('strong');author.className='comment-author';author.textContent=comment.nickname;const controls=document.createElement('div');controls.className='comment-actions';li.append(author,content,controls);if(comment.is_owner){controls.append(button('수정',async()=>{const version=selectionVersion;const original=await api('/comments/'+comment.id+'/edit-access');if(version!==selectionVersion||selected!==id)return;ask('댓글 수정',[['content','댓글 내용','textarea',original.content]],async data=>{await api('/comments/'+comment.id,'PATCH',data);await openPost(id);message('댓글을 수정했습니다.');});}),button('삭제',()=>ask('댓글을 삭제하시겠습니까?',[],async()=>{await api('/comments/'+comment.id,'DELETE');await openPost(id);message('댓글을 삭제했습니다.');})));}controls.append(button('신고',()=>reportTarget('COMMENT',comment.id)));list.append(li);}focusSection('detail');}
function ask(title,fields,action){$('inline-title').textContent=title;$('inline-fields').replaceChildren();for(const [name,label,type,value=''] of fields){const wrap=document.createElement('label');wrap.textContent=label;const input=document.createElement(type==='textarea'?'textarea':'input');if(type!=='textarea')input.type=type;input.name=name;input.value=value;input.required=true;input.maxLength=type==='password'?128:name==='reason'?1000:2000;wrap.append(input);$('inline-fields').append(wrap);}inlineAction=action;$('inline').hidden=false;focusSection('inline');const input=$('inline-fields').querySelector('input,textarea');if(input)input.focus({preventScroll:true});}
function reportTarget(type,id){ask('불쾌한 표현 신고',[['reason','신고 사유 또는 문제 표현','textarea']],async data=>{await api('/reports','POST',{...data,target_type:type,target_id:id});message('신고가 접수되었습니다.');});}
function startWrite(){closeDetail();editId=null;$('editor').hidden=false;$('editor-title').textContent='글쓰기';$('edit-password-label').hidden=true;$('post-form').elements.password.required=false;focusSection('editor');}
function startPostEdit(id){const version=selectionVersion;ask('본인 확인 후 글 수정',[['password','비밀번호','password']],async data=>{const original=await api('/posts/'+id+'/edit-access','POST',data);if(version!==selectionVersion||selected!==id)return;editId=id;$('detail').hidden=true;$('editor').hidden=false;$('editor-title').textContent='글 수정';$('post-form').elements.title.value=original.title;$('post-form').elements.content.value=original.content;$('edit-password-label').hidden=false;$('post-form').elements.password.required=true;$('post-form').elements.password.value='';focusSection('editor');});}
async function rulesPanel(){const version=++adminVersion;reportVersion++;$('rules-tab').setAttribute('aria-selected','true');$('reports-tab').setAttribute('aria-selected','false');$('rules-panel').hidden=false;$('reports-panel').hidden=true;const rules=await api('/admin/filter-rules');if(version!==adminVersion||user?.role!=='ADMIN')return;$('rules').replaceChildren();if(!rules.length)emptyState($('rules'),'등록된 규칙이 없습니다.');for(const rule of rules){const li=document.createElement('li');const text=document.createElement('span');text.textContent=rule.rule_type+' / '+rule.match_mode+' / '+rule.pattern+' → '+rule.replacement+' ';li.append(text,button('삭제',async()=>{await api('/admin/filter-rules/'+rule.id,'DELETE');await rulesPanel();message('규칙을 삭제했습니다.');}));$('rules').append(li);}}
const statusName={RECEIVED:'접수',IN_REVIEW:'검토',RESOLVED:'처리 완료'};
async function reportsPanel(){const version=++adminVersion;reportVersion++;$('rules-tab').setAttribute('aria-selected','false');$('reports-tab').setAttribute('aria-selected','true');$('rules-panel').hidden=true;$('reports-panel').hidden=false;$('report-detail').hidden=true;const reports=await api('/admin/reports?status='+$('report-filter').value);if(version!==adminVersion||user?.role!=='ADMIN')return;$('reports').replaceChildren();if(!reports.length)emptyState($('reports'),'접수된 신고가 없습니다.');for(const report of reports){const li=document.createElement('li');li.append(button(statusName[report.status]+' · '+report.target_type+' · '+report.reason,()=>openReport(report.id)));$('reports').append(li);}}
async function openReport(id){const version=++reportVersion;const report=await api('/admin/reports/'+id);if(version!==reportVersion||user?.role!=='ADMIN'||$('reports-panel').hidden)return;reportId=id;$('report-detail').hidden=false;$('report-target').textContent=(report.target_deleted?'삭제된 대상':'대상 '+(report.post_id||report.comment_id))+'\n'+report.target_content;$('report-reason').textContent='신고 사유: '+report.reason;$('report-handler').textContent=report.handled_at?'처리 관리자: '+report.handled_by+' · '+new Date(report.handled_at).toLocaleString():'아직 처리하지 않았습니다.';$('report-form').elements.status.value=report.status;$('report-form').elements.admin_note.value=report.admin_note||'';}
bind('login-mode',()=>mode('login'));bind('signup-mode',()=>mode('signup'));bind('forgot-mode',()=>mode('forgot'));
form('auth-form',async(data,el)=>{if(authMode==='forgot'){message('목업입니다. 이메일은 발송되지 않았습니다.');return;}if(authMode==='signup'){await api('/auth/signup','POST',data);el.reset();mode('login');message('가입했습니다. 로그인하세요.');return;}const result=await api('/auth/login','POST',{email:data.email,password:data.password});el.reset();await refreshCSRF();user=await api('/auth/me');navigation();$('greeting').textContent=result.nickname+'님, 환영합니다.';show('welcome');});
bind('enter-board',enterBoard);bind('board-link',enterBoard);bind('logout',async()=>{await api('/auth/logout','POST',{});user=null;closeDetail();navigation();mode('login');await refreshCSRF();message('로그아웃했습니다.');});
form('search-form',async()=>{page=1;closeDetail();await loadPosts();});bind('search-reset',async()=>{$('search-form').reset();page=1;closeDetail();await loadPosts();});bind('prev',async()=>{page--;closeDetail();await loadPosts();});bind('next',async()=>{page++;closeDetail();await loadPosts();});bind('write',startWrite);bind('cancel-edit',async()=>{const id=editId;closeDetail();if(id)await openPost(id);});bind('cancel-inline',()=>{$('inline').hidden=true;inlineAction=null;$('inline-fields').replaceChildren();});
form('post-form',async(data,el)=>{if(editId){await api('/posts/'+editId,'PATCH',data);}else{delete data.password;await api('/posts','POST',data);}el.reset();closeDetail();await loadPosts();message('저장했습니다.');});
form('comment-form',async(data,el)=>{const id=selected;if(!id)return;await api('/posts/'+id+'/comments','POST',data);el.reset();await openPost(id);message('댓글을 등록했습니다.');});
form('inline-form',async data=>{const action=inlineAction;if(!action)return;await action(data);if(inlineAction===action){$('inline').hidden=true;inlineAction=null;$('inline-fields').replaceChildren();}});
bind('admin-link',async()=>{closeDetail();show('admin');await rulesPanel();});bind('rules-tab',rulesPanel);bind('reports-tab',reportsPanel);$('report-filter').addEventListener('change',()=>run(reportsPanel));
form('rule-form',async(data,el)=>{data.case_sensitive=el.elements.case_sensitive.checked;data.priority=Number(data.priority);await api('/admin/filter-rules','POST',data);el.reset();await rulesPanel();message('규칙을 추가했습니다.');});
form('report-form',async data=>{const id=reportId;await api('/admin/reports/'+id,'PATCH',data);await reportsPanel();await openReport(id);message('처리 내용을 저장했습니다.');});
$('rule-form').elements.rule_type.addEventListener('change',()=>{const f=$('rule-form').elements;f.match_mode.value=f.rule_type.value==='REGEX'?'REGEX':'PARTIAL';});
run(async()=>{await refreshCSRF();try{user=await api('/auth/me');}catch{user=null;}navigation();if(user)await enterBoard();else mode('login');});
