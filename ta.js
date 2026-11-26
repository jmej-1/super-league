<script>
(function(){
  if(!window.TA) return;
  var R=TA.R.map(String), wk=TA.wk, NS=40000, st={t:['',''],give:{}}, cache={};
  function esc(x){return String(x==null?'':x).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
  function pc(v){ var x=v*100; return (x>=99.95?'>99.9':x<0.05&&x>0?'<0.1':(Math.round(x*10)/10).toString())+'%'; }
  function dl(v){ var x=Math.round(v*1000)/10; if(Math.abs(x)<0.1) return '<span class="muted">0</span>'; return '<span class="'+(x>0?'pos':'neg')+'">'+(x>0?'+':'')+x+'</span>'; }
  function ncdf(z){ var t=1/(1+0.2316419*Math.abs(z)), d=0.3989423*Math.exp(-z*z/2), p=d*t*(0.3193815+t*(-0.3565638+t*(1.781478+t*(-1.821256+t*1.330274)))); return z>0?1-p:p; }
  function best(pl){ var pool=pl.slice(), tot=0, ch=[];
    TA.slots.forEach(function(ok){ var bi=-1, bv=-1e9; for(var k=0;k<pool.length;k++){ if(ok.indexOf(pool[k][1])>=0&&pool[k][2]>bv){bv=pool[k][2];bi=k;} } if(bi>=0){ tot+=bv; ch.push(pool[bi].concat([ok.length>1?'FLEX':ok[0]])); pool.splice(bi,1); } });
    return [tot,ch]; }
  function teamWeek(ids,wi){ var w=wk[wi], pl=ids.map(function(i){var P=TA.P[i]; return [i,P[1],P[3][wi]];});
    var cur=best(pl)[0], added=[], cands=(TA.cand[w]||[]);
    for(var n=0;n<TA.pmax;n++){ var bst=null;
      cands.forEach(function(c){ if(added.indexOf(c)>=0||ids.indexOf(c)>=0) return; var x=pl.concat(added.concat([c]).map(function(i){var P=TA.P[i]; return [i,P[1],P[3][wi]];})), v=best(x)[0];
        if(v-cur>=TA.gain&&(!bst||v>bst[0])) bst=[v,c]; });
      if(!bst) break; added.push(bst[1]); cur=bst[0]; }
    var b=best(pl.concat(added.map(function(i){var P=TA.P[i]; return [i,P[1],P[3][wi]];}))), v=0;
    b[1].forEach(function(x){ var e=TA.cv[x[1]]*x[2]; v+=e*e; });
    var bp={}; b[1].forEach(function(x){ bp[x[3]]=(bp[x[3]]||0)+x[2]; });
    return [b[0], Math.sqrt(v)*TA.corr, bp]; }
  function rng(seed){ return function(){ seed|=0; seed=seed+0x6D2B79F5|0; var t=Math.imul(seed^seed>>>15,1|seed); t=t+Math.imul(t^t>>>7,61|t)^t; return ((t^t>>>14)>>>0)/4294967296; }; }
  function sim(ros){
    var nR=R.length, ix={}; R.forEach(function(r,k){ix[r]=k;});
    var MU=[], SD=[], BP=R.map(function(){return {};}); wk.forEach(function(w,wi){ MU.push([]); SD.push([]); R.forEach(function(r,k){ var x=teamWeek(ros[r],wi); MU[wi].push(x[0]); SD[wi].push(x[1]); for(var q in x[2]) BP[k][q]=(BP[k][q]||0)+x[2][q]/wk.length; }); });
    var full=[]; wk.forEach(function(w,wi){ if(!(TA.byes[w]||[]).length) full.push(wi); }); if(!full.length) full=wk.map(function(_,k){return k;});
    var pm=R.map(function(_,k){ var a=0,b=0; full.forEach(function(wi){a+=MU[wi][k]; b+=SD[wi][k];}); return [a/full.length,b/full.length]; });
    var rnd=rng(20261117), spare=null; function nrm(){ if(spare!==null){var s=spare; spare=null; return s;} var u=rnd()||1e-12, v=rnd(), m=Math.sqrt(-2*Math.log(u)); spare=m*Math.sin(2*Math.PI*v); return m*Math.cos(2*Math.PI*v); }
    var po=new Float64Array(nR), by=new Float64Array(nR), ti=new Float64Array(nR), W=new Float64Array(nR), PF=new Float64Array(nR), sc=new Float64Array(nR), o=[];
    for(var n=0;n<NS;n++){
      for(var k=0;k<nR;k++){ W[k]=TA.W[R[k]]; PF[k]=TA.PF[R[k]]; }
      for(var wi=0;wi<wk.length;wi++){ for(k=0;k<nR;k++){ sc[k]=MU[wi][k]+nrm()*SD[wi][k]; PF[k]+=sc[k]; }
        TA.fut[wk[wi]].forEach(function(g){ var i=ix[g[0]], j=ix[g[1]]; if(sc[i]>sc[j]) W[i]++; else W[j]++; }); }
      o=R.map(function(_,k){return k;}).sort(function(x,y){ return (W[y]*1e5+PF[y])-(W[x]*1e5+PF[x]); });
      for(k=0;k<TA.po;k++) po[o[k]]++; for(k=0;k<TA.by;k++) by[o[k]]++;
      var g=function(t){return pm[t][0]+nrm()*pm[t][1];}, pl=function(a,b){return g(a)>g(b)?a:b;};
      var q1=pl(o[3],o[4]), q2=pl(o[2],o[5]), f1=pl(o[0],q1), f2=pl(o[1],q2); ti[pl(f1,f2)]++; }
    var out={}; R.forEach(function(r,k){ out[r]={po:po[k]/NS, by:by[k]/NS, ti:ti[k]/NS, ppw:MU.reduce(function(a,x){return a+x[k];},0)/wk.length, bp:BP[k]}; });
    // league ranks: each lineup spot, and the power ranking (same formula as Standings: 50% projection, 30% season PPG, 20% last 3)
    POSL.forEach(function(q){ var o=R.slice().sort(function(x,y){return (out[y].bp[q]||0)-(out[x].bp[q]||0);}); o.forEach(function(r,n){ out[r]['rk'+q]=n+1; }); });
    var m=function(f){ var s=0; R.forEach(function(r){s+=f(r);}); return s/R.length; }, mr=m(function(r){return out[r].ppw;}), mp=m(function(r){return TA.pw[r][0];}), ml=m(function(r){return TA.pw[r][1];});
    R.forEach(function(r){ out[r].pw=0.5*(out[r].ppw-mr)+0.3*(TA.pw[r][0]-mp)+0.2*(TA.pw[r][1]-ml); });
    R.slice().sort(function(x,y){return out[y].pw-out[x].pw;}).forEach(function(r,n){ out[r].prk=n+1; });
    return out; }
  function war(i){ var P=TA.P[i]; return P&&P[6]?P[5]:null; }   // WAR over every game he played, started or not
  function ros_(i){ return TA.P[i][3].reduce(function(a,b){return a+b;},0); }
  var SHORT={Questionable:'Q',Doubtful:'D',Out:'O',IR:'IR',PUP:'PUP',Sus:'SUS',NA:'NA'};
  var MAXT=10, POSL=['QB','RB','WR','TE','FLEX','K','DEF'];
  function ord(n){ var s=['th','st','nd','rd'], v=n%100; return n+(s[(v-20)%10]||s[v]||s[0]); }
  function others(r){ return st.t.filter(function(x){return x&&x!==r;}); }
  function list(k){ var r=st.t[k]; if(!r) return '<p class="muted">Pick a team.</p>';
    var g=st.give[r]||{}, ot=others(r);
    var ids=TA.ros[r].slice().sort(function(x,y){ var o='QB RB WR TE K DEF'.split(' '); return o.indexOf(TA.P[x][1])-o.indexOf(TA.P[y][1])||(war(y)===null?-99:war(y))-(war(x)===null?-99:war(x))||ros_(y)-ros_(x); });   // position, then Full WAR
    var cl=st.t.length>=3&&!(st.open||{})[r], ng=Object.keys(g).filter(function(i){return g[i];}).length;
    return '<div class="tal'+(cl?' tcl':'')+'"><div class="talh"><span>Tap to add to the deal</span><span>Proj. rest of season, then Full WAR</span></div>'+ids.map(function(i){ var P=TA.P[i], on=!!g[i], wv=war(i), ir=(TA.ir[r]||[]).indexOf(i)>=0;
      var dest=on&&ot.length>1?'<label class="tadest">To <select data-dest="'+r+'|'+i+'">'+ot.map(function(o){return '<option value="'+o+'"'+(o===g[i]?' selected':'')+'>'+esc(TA.N[o][1])+'</option>';}).join('')+'</select></label>':'';
      return '<div class="tarow'+(on?' on':'')+'"><button type="button" class="tapl'+(on?' on':'')+'" data-r="'+r+'" data-i="'+i+'" aria-pressed="'+(on?'true':'false')+'"><span class="tpos">'+P[1]+'</span><span class="tnm"><b>'+esc(P[0])+'</b>'+(P[4]&&!(ir&&P[4]==='IR')?'<span class="stg inj">'+esc(SHORT[P[4]]||P[4])+'</span>':'')+(ir?'<span class="irb">IR</span>':'')+'<small>'+esc(P[2])+'</small></span><span class="tv"><b>'+(ros_(i)*TA.f).toFixed(1)+'</b><small>'+(wv===null?'no games':(wv>=0?'+':'')+wv.toFixed(2)+' Full WAR<br>'+P[7].toFixed(1)+' PPG')+'</small></span></button>'+dest+'</div>'; }).join('')+'</div>'+(st.t.length>=3?'<button type="button" class="tamore" data-r="'+r+'">'+(cl?'See full roster ('+ids.length+')':'Show less')+'</button>'+(cl&&ng?'<p class="tasel2">'+ng+' in the deal: '+Object.keys(g).filter(function(i){return g[i];}).map(function(i){return esc(TA.P[i][0]);}).join(', ')+'</p>':''):''); }
  function opts(k){ var sel=st.t[k]; return '<option value="">Pick a team</option>'+R.filter(function(r){return r===sel||st.t.indexOf(r)<0;}).map(function(r){return '<option value="'+r+'"'+(r===sel?' selected':'')+'>'+esc(TA.N[r][1])+' ('+esc(TA.N[r][0])+')</option>';}).join(''); }
  function moves(){ var m=[]; st.t.forEach(function(r){ if(!r) return; var g=st.give[r]||{}; Object.keys(g).forEach(function(i){ var d=g[i]; if(d&&st.t.indexOf(d)>=0&&d!==r) m.push([i,r,d]); }); }); return m; }
  function rosAfter(m){ var ros={}; R.forEach(function(r){ros[r]=TA.ros[r].slice();}); m.forEach(function(x){ ros[x[1]]=ros[x[1]].filter(function(i){return i!==x[0];}); ros[x[2]].push(x[0]); }); return ros; }
  function results(){
    var who=st.t.filter(Boolean);
    if(who.length<2) return '<p class="muted tahint">Pick at least two teams, then tap players to put them in the deal.</p>';
    var m=moves(); if(!m.length) return '<p class="muted tahint">Tap players on any side to put them in the deal.</p>';
    var gets={}, sends={}; who.forEach(function(r){gets[r]=[]; sends[r]=0;}); m.forEach(function(x){ gets[x[2]].push(x[0]); sends[x[1]]++; });
    if(!cache.base) cache.base=sim(TA.ros);
    var key=m.map(function(x){return x.join('>');}).sort().join(','); if(!cache[key]) cache[key]=sim(rosAfter(m));
    var B=cache.base, A=cache[key], nm=function(i){return esc(TA.P[i][0]);};
    var h='<div class="tadeal">'+who.map(function(r){ return '<p><b>'+esc(TA.N[r][1])+'</b> gets '+(gets[r].length?gets[r].map(nm).join(', '):'nothing')+'</p>'; }).join('')+'</div>';
    var sc=who.map(function(r){return [r,A[r].ti-B[r].ti];}).sort(function(x,y){return y[1]-x[1];});
    h+='<p class="tawin">Biggest winner: <b>'+esc(TA.N[sc[0][0]][1])+'</b>, title odds '+dl(sc[0][1])+'. Biggest loser: <b>'+esc(TA.N[sc[sc.length-1][0]][1])+'</b>, '+dl(sc[sc.length-1][1])+'.</p>';
    h+='<div class="tagrid">'+who.map(function(r){ var b=B[r], a=A[r], n=TA.ros[r].length-sends[r]+gets[r].length;
      var tile=function(k,lab){ return '<div class="tat2"><span>'+lab+'</span><b>'+pc(a[k])+'</b><small>from '+pc(b[k])+' '+dl(a[k]-b[k])+'</small></div>'; };
      var mv=function(n0,n1){ return n1<n0?'<span class="pos">▲'+(n0-n1)+'</span>':n1>n0?'<span class="neg">▼'+(n1-n0)+'</span>':'<span class="muted">same</span>'; };
      var gi=gets[r], go=m.filter(function(x){return x[1]===r;}).map(function(x){return x[0];});
      var sum=function(ids){ var w=0, p=0; ids.forEach(function(i){ var v=war(i); if(v!==null) w+=v; p+=ros_(i)*TA.f; }); return [w,p]; }, si=sum(gi), so=sum(go);
      var pos=POSL.filter(function(q){ return (b.bp[q]||0)>0||(a.bp[q]||0)>0; }).map(function(q){ var d=((a.bp[q]||0)-(b.bp[q]||0))*TA.f;
        return '<tr'+(Math.abs(d)>=0.5?' class="chg"':'')+'><td><b>'+q+'</b></td><td class="r">'+((b.bp[q]||0)*TA.f).toFixed(1)+'</td><td class="r"><b>'+((a.bp[q]||0)*TA.f).toFixed(1)+'</b></td><td class="r">'+(Math.abs(d)<0.05?'<span class="muted">0</span>':'<span class="'+(d>0?'pos':'neg')+'">'+(d>0?'+':'')+d.toFixed(1)+'</span>')+'</td><td class="r">'+ord(b['rk'+q])+' → <b>'+ord(a['rk'+q])+'</b></td></tr>'; }).join('');
      var dp=(a.ppw-b.ppw)*TA.f;
      return '<section class="panel tacard"><h3>'+TA.LG[r]+esc(TA.N[r][1])+'<small>'+esc(TA.N[r][0])+'</small></h3>'
        +'<div class="tat3">'+tile('po','Playoffs')+tile('by','Bye')+tile('ti','Title')+'</div>'
        +'<div class="tapw"><div><span>Power ranking</span><b>'+ord(b.prk)+' → '+ord(a.prk)+'</b> '+mv(b.prk,a.prk)+'</div><div><span>Points a week, rest of season</span><b>'+(b.ppw*TA.f).toFixed(1)+' → '+(a.ppw*TA.f).toFixed(1)+'</b> '+(Math.abs(dp)<0.05?'<span class="muted">same</span>':'<span class="'+(dp>0?'pos':'neg')+'">'+(dp>0?'+':'')+dp.toFixed(1)+'</span>')+'</div></div>'
        +'<h4>Starting lineup by spot</h4><table class="pt tapos"><thead><tr><th>Spot</th><th class="r">Now</th><th class="r">After</th><th class="r">Change</th><th class="r">League rank</th></tr></thead><tbody>'+pos+'</tbody></table>'
        +'<div class="taio"><div><span>Gets</span><b>'+(si[0]>=0?'+':'')+si[0].toFixed(2)+' Full WAR</b><small>'+si[1].toFixed(1)+' proj. pts left</small></div><div><span>Gives</span><b>'+(so[0]>=0?'+':'')+so[0].toFixed(2)+' Full WAR</b><small>'+so[1].toFixed(1)+' proj. pts left</small></div></div>'
        +(n>TA.ros[r].length?'<p class="note">Roster goes from '+TA.ros[r].length+' to '+n+'. Any drop isn\'t counted.</p>':'')+'</section>'; }).join('')+'</div>';
    var rest=R.filter(function(r){return who.indexOf(r)<0;}).sort(function(p,q){ return Math.abs(A[q].ti-B[q].ti)+Math.abs(A[q].po-B[q].po)-Math.abs(A[p].ti-B[p].ti)-Math.abs(A[p].po-B[p].po); });
    if(rest.length) h+='<section><h2>Everyone else</h2><p class="note">The trade moves the rest of the league too. Biggest changes first.</p><div class="scroll"><table class="pt taoth"><thead><tr><th>Team</th><th class="r">Playoffs</th><th class="r">Change</th><th class="r">Title</th><th class="r">Change</th><th class="r">Power</th></tr></thead><tbody>'
      +rest.map(function(r){ return '<tr><td><span class="tat">'+TA.LG[r]+esc(TA.N[r][1])+'</span></td><td class="r">'+pc(A[r].po)+'</td><td class="r">'+dl(A[r].po-B[r].po)+'</td><td class="r">'+pc(A[r].ti)+'</td><td class="r">'+dl(A[r].ti-B[r].ti)+'</td><td class="r">'+ord(B[r].prk)+' → '+ord(A[r].prk)+'</td></tr>'; }).join('')+'</tbody></table></div></section>';
    h+='<p class="note">'+NS.toLocaleString()+' simulated seasons, same model as the site\'s odds, re-run with the new rosters. Full WAR is WAR over every game a player played, started or not, so a player stuck on a bench still gets credit. Everywhere else on the site, WAR counts starts only. Lineup spots are average projected points a week in each team\'s best lineup. The "Now" column comes from the same run, so it can differ a little from Standings (1M seasons). Injured players count as 0 until Sleeper projects them again. Trade deadline: Week '+TA.dl+'.</p>';
    return h; }
  function draw(){ var el=document.getElementById('ta'); if(!el) return;
    el.innerHTML='<label class="tan"><span>Teams in the trade</span><select class="tanum">'+[2,3,4,5,6,7,8,9,10].map(function(n){ return '<option value="'+n+'"'+(st.t.length===n?' selected':'')+'>'+n+'</option>'; }).join('')+'</select></label><div class="tapick" style="grid-template-columns:repeat('+Math.min(st.t.length,2)+',minmax(0,1fr))">'+st.t.map(function(r,k){ return '<section class="taside"><div class="tahd"><label class="tasel"><span>Team '+(k+1)+' sends</span><select data-k="'+k+'">'+opts(k)+'</select></label>'+'</div>'+list(k)+'</section>'; }).join('')+'</div>'
      +'<div class="tares">'+results()+'</div>'; }
  function rerun(){ var y=window.scrollY, res=document.querySelector('#ta .tares'); if(res) res.innerHTML='<p class="muted tahint">Running the season…</p>'; setTimeout(function(){ draw(); window.scrollTo(0,y); },20); }
  function fixDest(){ st.t.forEach(function(r){ var g=st.give[r]; if(!r||!g) return; var ot=others(r); Object.keys(g).forEach(function(i){ if(!g[i]) return; if(ot.indexOf(g[i])<0) g[i]=ot[0]||''; if(!g[i]) delete g[i]; }); }); }
  document.addEventListener('change',function(e){ var s=e.target;
    if(s.matches&&s.matches('#ta select[data-k]')){ var k=+s.getAttribute('data-k'), old=st.t[k]; if(old) delete st.give[old]; st.t[k]=s.value; fixDest(); rerun(); }
    else if(s.matches&&s.matches('#ta select[data-dest]')){ var p=s.getAttribute('data-dest').split('|'); st.give[p[0]][p[1]]=s.value; rerun(); } });
  document.addEventListener('click',function(e){ var c=e.target.closest; if(!c) return;
    var mo=e.target.closest('#ta .tamore'); if(mo){ var r0=mo.getAttribute('data-r'); st.open=st.open||{}; st.open[r0]=!st.open[r0]; var y=window.scrollY; draw(); if(!st.open[r0]) { var el=document.querySelector('#ta .tamore[data-r="'+r0+'"]'); if(el) el.scrollIntoView({block:'center'}); } else window.scrollTo(0,y); return; }
    var b=e.target.closest('#ta .tapl'); if(b){ var r=b.getAttribute('data-r'), i=b.getAttribute('data-i'), g=st.give[r]=st.give[r]||{}; if(g[i]) delete g[i]; else g[i]=others(r)[0]||''; if(g[i]==='') delete g[i]; rerun(); return; }
    });
  document.addEventListener('change',function(e){ if(!(e.target.matches&&e.target.matches('#ta .tanum'))) return; { var n=+e.target.value; while(st.t.length<n) st.t.push(''); while(st.t.length>n){ var r=st.t.pop(); if(r) delete st.give[r]; } fixDest(); rerun(); } });
  window.addEventListener('hashchange',function(){ if(/^#\/analyzer/.test(location.hash)&&!document.querySelector('#ta .taside')) draw(); });
  if(/^#\/analyzer/.test(location.hash)) draw(); else setTimeout(draw,0);
})();
</script>
<script>
(function(){
  var st={f:'all',r:'',lost:false,q:'',n:6};        // the list stops after n moves; "Show more" adds 20
  var norm=function(x){ return String(x||'').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/[^a-z0-9 ]/g,''); };
  function apply(){ var list=document.querySelector('.txlist'); if(!list) return; var shown=0, lastH=null, any=false;
    [].forEach.call(list.children,function(el){
      if(el.tagName==='H3'){ if(lastH) lastH.hidden=!any; lastH=el; any=false; return; }
      var ok=(st.f==='all'||el.getAttribute('data-k')===st.f)&&(!st.r||(','+el.getAttribute('data-r')+',').indexOf(','+st.r+',')>=0)&&(st.lost||el.getAttribute('data-lost')!=='1')&&(!st.q||st.q.split(' ').every(function(w){ if(!el._t) el._t=norm(el.textContent); return el._t.indexOf(w)>=0; }));
      if(ok){ shown++; if(shown>st.n) ok=false; } el.hidden=!ok; if(ok) any=true; });
    if(lastH) lastH.hidden=!any; var nn=document.querySelector('.txnone'); if(nn) nn.hidden=shown>0;
    var mb=document.querySelector('.txmore'); if(!mb){ mb=document.createElement('div'); mb.className='txmore'; list.parentNode.insertBefore(mb,list.nextSibling); }
    mb.innerHTML=shown>st.n?'<span>Showing '+st.n+' of '+shown+'</span><button type="button" class="txmb">Show 10 more</button><button type="button" class="txma">Show all</button>':(shown>6?'<span>All '+shown+' shown</span><button type="button" class="txmc">Show fewer</button>':''); }
  document.addEventListener('click',function(e){ var x=e.target.closest&&e.target.closest('.txmb,.txma,.txmc'); if(!x) return;
    if(x.classList.contains('txmb')) st.n+=10; else if(x.classList.contains('txma')) st.n=1e9; else { st.n=6; var l=document.querySelector('.txbar'); if(l) l.scrollIntoView({block:'start'}); } apply(); });
  document.addEventListener('click',function(e){ var b=e.target.closest&&e.target.closest('.txf button'); if(!b) return; st.f=b.getAttribute('data-f'); st.n=6;
    [].forEach.call(b.parentNode.querySelectorAll('button'),function(x){x.setAttribute('aria-pressed',x===b?'true':'false');}); apply(); });
  document.addEventListener('input',function(e){ if(e.target.matches&&e.target.matches('.txq')){ st.q=norm(e.target.value).trim().replace(/\s+/g,' '); st.n=6; var lc=document.querySelector('.txlost'); st.lost=!!st.q||!!(lc&&lc.checked); apply(); } });      // search also looks through lost claims
  document.addEventListener('change',function(e){ if(e.target.matches&&e.target.matches('.txteam')){ st.r=e.target.value; st.n=6; apply(); } else if(e.target.matches&&e.target.matches('.txlost')){ st.lost=e.target.checked; apply(); } });
  apply();
})();
</script>
<script>
document.addEventListener('click',function(e){ var b=e.target.closest&&e.target.closest('.gft button'); if(!b) return; var pn=b.closest('.wpc'), g=b.getAttribute('data-g');
  [].forEach.call(b.parentNode.querySelectorAll('button'),function(x){x.setAttribute('aria-pressed',x===b?'true':'false');});
  [].forEach.call(pn.querySelectorAll('.gfv'),function(v){v.hidden=v.getAttribute('data-g')!==g;}); [].forEach.call(pn.querySelectorAll('.wpd.on'),function(x){x.classList.remove('on');}); [].forEach.call(pn.querySelectorAll('.wpg'),function(l){l.setAttribute('opacity','0');}); var c=pn.querySelector('.wpcard'); if(c) c.innerHTML=c.getAttribute('data-def'); });
</script>
<script>
document.addEventListener('click',function(e){ var b=e.target.closest&&e.target.closest('.sdt button');
  if(b){ var sec=b.closest('.seedsec'), v=b.getAttribute('data-v'); [].forEach.call(b.parentNode.querySelectorAll('button'),function(x){x.setAttribute('aria-pressed',x===b?'true':'false');});
    [].forEach.call(sec.querySelectorAll('.sdv'),function(x){x.hidden=x.getAttribute('data-v')!==v;}); return; }
  var g=e.target.closest&&e.target.closest('.sdr'); if(g){ var sec2=g.closest('.seedsec'); g.classList.toggle('on'); sec2.classList.toggle('iso',!!sec2.querySelector('.sdr.on')); } });
</script>
