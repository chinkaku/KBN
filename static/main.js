window.addEventListener("error",function(ev){
  var d=document.createElement("div");
  d.style.cssText="position:fixed;left:8px;bottom:8px;z-index:99999;background:#7a1f1f;color:#ffd9d9;font:11px monospace;padding:8px 12px;border-radius:6px;max-width:70vw;white-space:pre-wrap";
  d.textContent="JS错误: "+(ev.message||"未知");
  document.body.appendChild(d);
});
var ws=null,st=null,sel=null,MY_IDX=-1;
var IMG={"1m":"1m.png","2m":"2m.png","3m":"3m.png","4m":"4m.png","5m":"5m.png","6m":"6m.png","7m":"7m.png","8m":"8m.png","9m":"9m.png","1p":"1p.png","2p":"2p.png","3p":"3p.png","4p":"4p.png","5p":"5p.png","6p":"6p.png","7p":"7p.png","8p":"8p.png","9p":"9p.png","1s":"1s.png","2s":"2s.png","3s":"3s.png","4s":"4s.png","5s":"5s.png","6s":"6s.png","7s":"7s.png","8s":"8s.png","9s":"9s.png","E":"1z.png","S":"2z.png","W":"3z.png","N":"4z.png","C":"5z.png","F":"6z.png","P":"7z.png"};
var _QS=new URLSearchParams(location.search);
var ROOM_ID=_QS.get("room")||"";
var WS_USER=localStorage.getItem("mj_user")||"";
var DEBUG_HAND=_QS.get("hand")||"";
var ADV_LEVEL=_QS.get("adventure")||"";
var ADV_STORY=null;
var ADV_ROUNDS=1;
var ADV_GOAL=null;
var TOKEN=localStorage.getItem("mj_token")||"";
function q(url){return url+(url.indexOf("?")>=0?"&":"?")+"token="+encodeURIComponent(TOKEN)}
var WS_RETRY=0;
var TIMER_DEADLINE=0,TIMER_INTERVAL=null,PREV_DISCARD=null,LAST_POP_BY=-1,PREV_DISCARD_COUNTS=[0,0,0,0];

function conn(){var p=location.protocol=="https:"?"wss:":"ws:";var url=p+"//"+location.host+"/ws";if(ROOM_ID)url+="/"+ROOM_ID;var q=[];if(WS_USER)q.push("user="+encodeURIComponent(WS_USER));if(_QS.get("debug")==="1")q.push("debug=1");if(DEBUG_HAND)q.push("hand="+encodeURIComponent(DEBUG_HAND));if(ADV_LEVEL)q.push("adventure="+encodeURIComponent(ADV_LEVEL));if(q.length)url+="?"+q.join("&");ws=new WebSocket(url);ws.onmessage=function(e){onMsg(JSON.parse(e.data));WS_RETRY=0};ws.onclose=function(){WS_RETRY++;if(WS_RETRY<=5)setTimeout(conn,2000)}}
function act(type,prm){prm=prm||{};if(ws&&ws.readyState===WebSocket.OPEN)ws.send(JSON.stringify({action:type,params:prm}))}
function onMsg(msg){if(msg.type==="msg"){alert(msg.msg);return}
  if(msg.type==="adventure_ready"){
    ADV_STORY=msg.story||{before:[],after:[]};
    ADV_ROUNDS=msg.rounds||1;
    ADV_GOAL=msg.goal||null;
    if(msg.seen){
      // 战前剧情已看过: 提供跳过(直接跳到战斗前一句=获胜条件)或重看
      showSkipPrompt(function(){
        var lines=ADV_STORY.before||[];
        playStory(lines.slice(-1),function(){act("adventure_start");hideDialog()});
      });
    }else{
      playStory(ADV_STORY.before,function(){act("adventure_start");hideDialog()});
    }
    return
  }
  if(msg.type!=="state")return;st=msg.data;if(st.my_idx!=null)MY_IDX=st.my_idx;if(st.room)updateNames(st.room);if(st.game_over&&!st._shown){st._shown=1;clearTimer();showResult(st);return}render(st);startTimer(st)}
function render(s){bar(s);for(var i=0;i<4;i++)pla(i,s);disc(s);melds(s);if(s.game_over)over(s)}
function E(id){return document.getElementById(id)}
function bar(s){var sc=s.scores||{};var rt=s.remaining_tiles;var wc=E("wall-count-area");if(wc)wc.textContent=rt;var ri=E("round-info");if(ri)ri.textContent=ADV_LEVEL?(s.round_num+"/"+ADV_ROUNDS+"局"):s.round_num;E("score-info").textContent=(sc["东"]||0)+" "+(sc["南"]||0)+" "+(sc["西"]||0)+" "+(sc["北"]||0)}

// ===== 牌河: 联机模式隐藏中央弃牌, 改为牌河标红 =====
function disc(s){
  // 清除上一轮标红
  if(PREV_DISCARD) PREV_DISCARD.classList.remove("tile-highlight");
  if(ROOM_ID){
    var la=E("last-discard-area"); if(la)la.style.display="none";
    // 在牌河中找最后一张弃牌标红 (视角旋转: 按我的座位映射到物理牌河)
    if(s.last_discard&&s.last_discard_by!=null){
      var my=(MY_IDX<0?0:MY_IDX);
      var rEl=E("river-"+["bottom","right","top","left"][(s.last_discard_by-my+4)%4]);
      if(rEl){
        var tiles=rEl.children;
        if(tiles.length>0){
          PREV_DISCARD=tiles[tiles.length-1];
          PREV_DISCARD.classList.add("tile-highlight");
        }
      }
    }
  }else{
    var el=E("last-discard-tile");if(!el)return;
    if(s.last_discard){el.className="tile tile-img";var fn=IMG[s.last_discard];if(fn)el.style.backgroundImage="url(/static/tiles/"+fn+")"}
    else{el.className="tile tile-hidden"}
  }
}

var FLY_ID=0,SORTING=false;

// 摸牌排序动画: 关闭空档 + 插入排序位
function sortDrawnBeforeDiscard(handEl,discardEl,drawnSh,callback){
  if(SORTING){callback();return}
  SORTING=true;
  var tiles=[].slice.call(handEl.querySelectorAll(".tile"));
  var gap=handEl.querySelector(".hand-gap");
  var first={};tiles.forEach(function(t,i){first[i]=t.getBoundingClientRect().left});

  // 重排 DOM: 去掉空档 + drawn 插到排序位(弃牌留给 flyReal 处理)
  if(gap)gap.remove();
  var sorted=[];
  tiles.forEach(function(t){if(t.dataset.sh!==drawnSh)sorted.push(t)});
  // rest 就是 drawn 牌
  var drawnTile=null;
  tiles.forEach(function(t){if(t.dataset.sh===drawnSh)drawnTile=t});
  // 按 tile_type+rank 排序 (复用服务端顺序: 万m->筒p->条s->字z)
  var order={m:0,p:1,s:2,z:3};
  function rank(sh){var t=sh[0],s=sh[sh.length-1];return order[s]*10+parseInt(t)||99}
  sorted.sort(function(a,b){return rank(a.dataset.sh)-rank(b.dataset.sh)});
  var ins=0;for(;ins<sorted.length;ins++){if(rank(drawnSh)<rank(sorted[ins].dataset.sh))break}
  while(handEl.firstChild)handEl.removeChild(handEl.firstChild);
  for(var i=0;i<sorted.length;i++){if(i===ins&&drawnTile)handEl.appendChild(drawnTile);handEl.appendChild(sorted[i])}
  if(ins>=sorted.length&&drawnTile)handEl.appendChild(drawnTile);
  SORTING=false;callback();
}

function flyDiscard(el,sh){
  if(FLY_ID||!st||st.current_player_idx!==MY_IDX||st.phase!=="DISCARD"){act("discard",{tile:sh});return}
  // 摸切(打出刚摸的牌)或非摸切: 都隐藏空档, 避免删错牌后空档残留
  var gap=E("hand-bottom")?E("hand-bottom").querySelector(".hand-gap"):null;
  if(gap&&st.drawn_tile)gap.style.visibility="hidden";
  flyReal(el,sh);
}

function flyReal(el,sh){
  if(FLY_ID||!el)return;
  FLY_ID=1;
  var r=el.getBoundingClientRect();
  var rv=E("river-bottom");if(!rv){act("discard",{tile:sh});FLY_ID=0;return}
  var rr=rv.getBoundingClientRect();
  var c=el.cloneNode(true);
  c.style.position="fixed";c.style.left=r.left+"px";c.style.top=r.top+"px";
  c.style.width=r.width+"px";c.style.height=r.height+"px";
  c.style.margin="0";c.style.zIndex="1000";c.style.pointerEvents="none";
  if(!c.style.backgroundImage||c.style.backgroundImage==="none")c.style.backgroundImage=getComputedStyle(el).backgroundImage;
  document.body.appendChild(c);el.remove();
  var dx=rr.right-28-4-r.left,dy=rr.top+rr.height/2-38/2-r.top;
  var jx=Math.round(4*(.85+Math.random()*.3)),jy=Math.round(8*(.85+Math.random()*.3));
  c.animate([{transform:"translate(0,0) scale(1)",opacity:1},{transform:"translate(0,0) scale(.58)",opacity:.85}],
    {duration:113,easing:"linear",fill:"forwards"}).onfinish=function(){
    c.animate([
      {transform:"translate(0,0) scale(.58)",opacity:.85,offset:0},
      {transform:"translate("+(dx+jx)+"px,"+(dy+jy)+"px) scale(.58)",opacity:.8,offset:.65},
      {transform:"translate("+dx+"px,"+dy+"px) scale(.58)",opacity:.5,offset:1}
    ],{duration:113,easing:"linear",fill:"forwards"}).onfinish=function(){c.remove();FLY_ID=0;act("discard",{tile:sh})};
  };
}
function tile(sh,clk){var d=document.createElement("div");d.className="tile tile-img";d.dataset.sh=sh;var fn=IMG[sh];if(fn)d.style.backgroundImage="url(/static/tiles/"+fn+")";if(clk)d.addEventListener("click",function(){flyDiscard(d,sh)});return d}
function back(){var d=document.createElement("div");d.className="tile tile-img tile-back";d.style.backgroundImage="url(/static/tiles/back.png)";return d}

// ===== 副露区渲染 (横置鸣牌、加杠叠放、暗杠扣牌) =====
function renderMeldGroup(m){
  var g=document.createElement("span");g.className="meld-group";
  var claimed=m.claimed_tile,from=m.claimed_from,added=m.added_tile;
  function rt(sh){var w=document.createElement("span");w.className="tile-rot-wrap";w.appendChild(tile(sh,false));return w}
  function nt(sh){return tile(sh,false)}
  // 暗杠: 第1、4张扣着, 不横置
  if(m.type==="DARK_KONG"){
    for(var i=0;i<4;i++){g.appendChild(i===0||i===3?back():nt(m.tiles[i]))}
    return g;
  }
  // 无鸣牌信息(旧数据)则全部正放
  if(!claimed&&!added){m.tiles.forEach(function(sh){g.appendChild(tile(sh,false))});return g}
  // 吃: 横置牌固定最左
  if(m.type==="CHOW"){
    g.appendChild(rt(claimed));
    m.tiles.forEach(function(sh){if(sh!==claimed)g.appendChild(nt(sh))});
    return g;
  }
  // 加杠: 原碰3张 + 新牌叠在原横置牌上方
  if(added){
    var pi=from===1?0:from===2?1:2; // 碰的横置位置(上家0/对家1/下家2)
    for(var j=0;j<3;j++){
      if(j===pi){
        var st=document.createElement("span");st.className="tile-stack";
        st.appendChild(rt(added));
        st.appendChild(rt(m.tiles[j]));
        g.appendChild(st);
      }else g.appendChild(nt(m.tiles[j]));
    }
    return g;
  }
  // 碰/明杠
  var ri=from===1?0:from===2?1:from===3?(m.tiles.length-1):-1;
  for(var k=0;k<m.tiles.length;k++){
    g.appendChild(k===ri?rt(m.tiles[k]):nt(m.tiles[k]));
  }
  return g;
}

// ===== 七段数码管计时器 =====
var SEGS={
'0':[1,1,1,0,1,1,1],'1':[0,0,1,0,0,1,0],'2':[1,0,1,1,1,0,1],'3':[1,0,1,1,0,1,1],
'4':[0,1,1,1,0,1,0],'5':[1,1,0,1,0,1,1],'6':[1,1,0,1,1,1,1],'7':[1,0,1,0,0,1,0],
'8':[1,1,1,1,1,1,1],'9':[1,1,1,1,0,1,1]
};
// 七段管(单数字紧凑几何): a(top) b(ur) c(lr) d(bot) e(ll) f(ul) g(mid)
// 每个数字约46x88, 两位并排 (dx=0, 50), viewBox "0 0 100 92"
var SP=[ // [x,y,x2,y2] per segment
[10,5,40,5],[43,9,43,40],[43,48,43,79],[10,84,40,84],
[6,48,6,79],[6,9,6,40],[10,43,40,43]
];

var LED_HTML="";

function draw7Seg(num,cls,dx){
  var pat=SEGS[num]||SEGS['0'];
  var c=cls||"seg-on";
  var o=dx||0;
  for(var i=0;i<7;i++){
    var s=SP[i], on=pat[i];
    if(i===0||i===3||i===6){
      LED_HTML+='<polygon points="'+(o+s[0])+','+s[1]+' '+(o+s[0]+7)+','+(s[1]-5)+' '+(o+s[2]-7)+','+(s[3]-5)+' '+(o+s[2])+','+s[3]+'" class="'+(on?c:"seg-off")+'"/>';
    }else{
      LED_HTML+='<polygon points="'+(o+s[0])+','+s[1]+' '+(o+s[0]+5)+','+(s[1]+6)+' '+(o+s[2]+5)+','+(s[3]-6)+' '+(o+s[2])+','+s[3]+'" class="'+(on?c:"seg-off")+'"/>';
    }
  }
}

function updateLED(tm){
  var el=E("led-timer"),svg=E("led-svg"); if(!el||!svg)return;
  if(!tm||!tm.remaining||tm.remaining<=0){el.style.display="none";return}
  var sec=Math.ceil(tm.remaining);
  var t0=Math.floor(sec/10)%10, t1=sec%10;
  if(tm.chow_window){
    el.style.display="block";
    svg.setAttribute("viewBox","0 0 100 92");
    LED_HTML=""; draw7Seg(t0,"seg-on gold",0); draw7Seg(t1,"seg-on gold",50);
  }else if(tm.visible){
    el.style.display="block";
    var cls=sec<=3?"seg-on urgent":"seg-on";
    svg.setAttribute("viewBox","0 0 100 92");
    LED_HTML=""; draw7Seg(t0,cls,0); draw7Seg(t1,cls,50);
  }else{
    el.style.display="block";
    svg.innerHTML='<text x="50" y="57" class="led-wait-text">等待</text>';
    return;
  }
  svg.innerHTML='<defs><filter id="glow"><feGaussianBlur stdDeviation="0.8" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>'+LED_HTML;
}

function startTimer(s){
  clearTimer();
  var tm=s.timer; if(!tm||!tm.remaining)return;
  TIMER_DEADLINE=Date.now()+tm.remaining*1000;
  updateLED(tm);
  TIMER_INTERVAL=setInterval(function(){
    var left=(TIMER_DEADLINE-Date.now())/1000;
    if(left<=0){clearTimer();var el=E("led-timer");if(el)el.style.display="none";return}
    var fake={remaining:left,visible:tm.visible,chow_window:tm.chow_window};
    updateLED(fake);
  },200);
}
function clearTimer(){if(TIMER_INTERVAL){clearInterval(TIMER_INTERVAL);TIMER_INTERVAL=null}TIMER_DEADLINE=0}

function updateNames(room){if(room&&room.players){for(var r in room.players){var p=room.players[r];if(p&&p.name)NAMES[parseInt(r)]=p.name}}}
var ROLES=["东","南","西","北"];var NAMES=["你","伯特1","伯特2","伯特3"];

function showResult(s){
  clearTimer();
  var old=E("result-overlay"); if(old)old.remove();
  var ov=document.createElement("div");ov.id="result-overlay";
  ov.style.cssText="position:fixed;top:0;left:0;width:100vw;height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;background:rgba(5,10,16,.95);z-index:9999;gap:12px";
  var ti=document.createElement("div");ti.textContent=s.winner_idx!=null?(ROLES[s.winner_idx]+" 和牌"):"流局";ti.style.cssText="font-size:28px;font-weight:900;color:#e0e0e0;letter-spacing:2px";ov.appendChild(ti);
  var rows=document.createElement("div");rows.style.cssText="display:flex;flex-direction:column;gap:8px;width:92vw;max-width:900px";
  for(var i=0;i<4;i++){var p=s.players[i]||{},r=ROLES[i],n=NAMES[i],isWin=(s.winner_idx===i);var handSh=s.human_hand||[],scNum="",scLab="";if(isWin){scNum=(s.total_fan?2*s.total_fan:p.score||0)+"";scLab=(s.win_type||"")+" "+("总"+(s.total_fan||0)+"番");}else{var rs=s.ryuukyoku_scores;if(rs&&rs[r]){scNum=(rs[r].score||0)+"";scLab=(rs[r].fan||0)+"番"+(rs[r].method?("·"+rs[r].method):"")+(rs[r].waiting?("(听"+rs[r].waiting+"张)"):"");}else{scNum=(p.score||0)+"";scLab="-";}}
  var row=document.createElement("div");row.style.cssText="display:flex;flex-direction:column;padding:10px 16px;gap:4px;background:rgba(30,42,60,.7);border:1px solid rgba(0,229,255,.15);border-radius:10px";if(isWin){row.style.borderColor="#00e5ff";row.style.boxShadow="0 0 20px rgba(0,229,255,.1)";row.style.background="rgba(0,229,255,.08)";}
  var topR=document.createElement("div");topR.style.cssText="display:flex;align-items:center;gap:10px";var left=document.createElement("div");left.style.cssText="width:60px;text-align:center;flex-shrink:0";left.innerHTML="<div style=font-size:20px;font-weight:900;color:#00e5ff>"+r+"</div><div style=font-size:10px;color:#78909c>"+n+"</div>";topR.appendChild(left);
  var mid=document.createElement("div");mid.style.cssText="flex:1;display:flex;flex-wrap:wrap;gap:2px;align-items:center;min-height:38px";
  if(p.melds&&p.melds.length){p.melds.forEach(function(m){var mg=document.createElement("span");mg.style.cssText="display:inline-flex;gap:1px;margin-right:4px;border:1px solid rgba(0,229,255,.15);border-radius:3px;padding:1px;background:rgba(0,229,255,.04)";m.tiles.forEach(function(sh,j){var t=document.createElement("span");t.style.cssText="display:inline-flex;flex-shrink:0;width:26px;height:36px;background-size:cover;background-position:center;border-radius:2px";if(m.type=="DARK_KONG"&&j<m.hidden){t.style.backgroundImage="url(/static/tiles/back.png)";t.style.border="1px solid rgba(0,229,255,.1)";}else{t.style.backgroundImage="url(/static/tiles/"+IMG[sh]+")";t.style.border="1px solid rgba(0,229,255,.2)";}mg.appendChild(t);});mid.appendChild(mg)})}
  var rev=(s.revealed_hands&&s.revealed_hands[i])||null;
  if(rev){rev.forEach(function(sh){var t=document.createElement("span");t.style.cssText="display:inline-flex;flex-shrink:0;width:32px;height:44px;background-size:cover;background-position:center;background-image:url(/static/tiles/"+IMG[sh]+");border:1px solid rgba(0,229,255,.2);border-radius:3px";mid.appendChild(t)});}else if(isWin||i===MY_IDX){if(handSh)handSh.forEach(function(sh){var t=document.createElement("span");t.style.cssText="display:inline-flex;flex-shrink:0;width:32px;height:44px;background-size:cover;background-position:center;background-image:url(/static/tiles/"+IMG[sh]+");border:1px solid rgba(0,229,255,.2);border-radius:3px";mid.appendChild(t)});}else{for(var k=0;k<(p.hand_count||0);k++){var t=document.createElement("span");t.style.cssText="display:inline-flex;flex-shrink:0;width:32px;height:44px;background-size:cover;background-position:center;background-image:url(/static/tiles/back.png);border:1px solid rgba(0,229,255,.1);border-radius:3px";mid.appendChild(t);}}
  topR.appendChild(mid);var right=document.createElement("div");right.style.cssText="width:80px;text-align:right;flex-shrink:0";right.innerHTML="<div style=font-size:22px;font-weight:900;color:#ffb300>"+scNum+"</div>";topR.appendChild(right);row.appendChild(topR);
  if(scLab&&scLab!="-"){var botR=document.createElement("div");botR.style.cssText="display:flex;align-items:center;gap:8px;padding-left:70px;padding-right:86px";var fd=[];if(isWin){fd=s.fan_details||[];}else{var rd=s.ryuukyoku_details;if(rd&&rd[r])fd=rd[r];}if(fd.length){var names=fd.map(function(d){return d.name}).join(" ");botR.innerHTML="<span style=color:#78909c;font-size:11px>"+names+"</span><span style=color:#ffb300;font-weight:700;font-size:12px;margin-left:auto>"+scLab+"</span>";}else{botR.innerHTML="<span style=color:#78909c;font-size:11px>"+scLab+"</span>";}row.appendChild(botR);}
  rows.appendChild(row)}ov.appendChild(rows);var btn=document.createElement("button");if(ADV_LEVEL){btn.textContent="继续 →";btn.onclick=function(){adventureEnd(s)}}else{btn.textContent="下一局";btn.onclick=nx}btn.style.cssText="padding:10px 30px;font-size:14px;font-weight:600;border:1px solid rgba(0,229,255,.3);border-radius:20px;background:rgba(0,229,255,.08);color:#00e5ff;cursor:pointer;margin-top:6px";ov.appendChild(btn);document.body.appendChild(ov);
}

// ===== 冒险模式: 剧情对话框 =====
var DIALOG_LINES=null,DIALOG_IDX=0,DIALOG_TYPING=false,DIALOG_TICK=null,DIALOG_DONE=null;

function showDialog(){var ov=E("dialog-overlay");if(!ov){ov=document.createElement("div");ov.id="dialog-overlay";document.body.appendChild(ov)}ov.style.display="block"}
function hideDialog(){var ov=E("dialog-overlay");if(ov)ov.style.display="none"}
function playStory(lines,onDone){
  DIALOG_LINES=lines||[];DIALOG_IDX=0;DIALOG_DONE=onDone||null;
  showDialog();showDialogLine();
}
function showDialogLine(){
  var line=DIALOG_LINES[DIALOG_IDX];
  if(!line){hideDialog();var fn=DIALOG_DONE;DIALOG_DONE=null;if(fn)fn();return}
  E("dialog-name").textContent=line.speaker||"旁白";
  typeText(line.text);
}
function typeText(text){
  DIALOG_TYPING=true;
  var el=E("dialog-text");el.textContent="";
  var i=0;
  clearInterval(DIALOG_TICK);DIALOG_TICK=null;
  DIALOG_TICK=setInterval(function(){
    i++;el.textContent=text.slice(0,i);
    if(i>=text.length){clearInterval(DIALOG_TICK);DIALOG_TICK=null;DIALOG_TYPING=false}
  },40);
}
function dialogAdvance(){
  if(DIALOG_TYPING){ // 第一次: 立即显示全部
    clearInterval(DIALOG_TICK);DIALOG_TICK=null;
    var line=DIALOG_LINES[DIALOG_IDX];
    if(line)E("dialog-text").textContent=line.text;
    DIALOG_TYPING=false;return;
  }
  DIALOG_IDX++;showDialogLine(); // 第二次: 下一句
}
// 战前剧情已看过: 弹出"跳过 / 重看"选项
function showSkipPrompt(onSkip){
  var old=E("skip-prompt");if(old)old.remove();
  var ov=document.createElement("div");ov.id="skip-prompt";
  ov.style.cssText="position:fixed;top:0;left:0;width:100vw;height:100vh;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:18px;background:rgba(5,10,16,.72);z-index:9997;cursor:default";
  var t=document.createElement("div");t.textContent="该关战前剧情已看过，要跳过吗？";t.style.cssText="color:#e0e0e0;font-size:18px;font-weight:600;letter-spacing:1px";
  var st=document.createElement("div");st.textContent="跳过将直接播放获胜条件一句后开战";st.style.cssText="color:#78909c;font-size:12px";
  var btns=document.createElement("div");btns.style.cssText="display:flex;gap:14px;margin-top:6px";
  function mk(txt,fn){var b=document.createElement("button");b.textContent=txt;b.style.cssText="padding:9px 26px;font-size:14px;font-weight:600;border:1px solid rgba(0,229,255,.35);border-radius:20px;background:rgba(0,229,255,.08);color:#00e5ff;cursor:pointer";b.onclick=function(){ov.remove();fn()};return b}
  btns.appendChild(mk("跳过",onSkip));
  btns.appendChild(mk("重看",function(){ov.remove();playStory(ADV_STORY.before,function(){act("adventure_start");hideDialog()})}));
  ov.appendChild(t);ov.appendChild(st);ov.appendChild(btns);
  document.body.appendChild(ov);
}
function adventureEnd(s){
  var ov=E("result-overlay");if(ov)ov.remove();
  var goalMet=!!s.adv_goal_met;
  var after=(ADV_STORY&&ADV_STORY.after)||[];
  if(goalMet){
    // 达成关卡目标(和出五门齐): 播战后剧情 → 标记完成
    if(after.length){
      playStory(after,function(){markAdventureComplete(ADV_LEVEL).then(function(){location.href="/adventure"})});
    }else{
      markAdventureComplete(ADV_LEVEL).then(function(){location.href="/adventure"});
    }
  }else{
    // 未达成目标: 还有局数则继续, 打满局数则失败
    var rd=s.round_num||1;
    var total=ADV_ROUNDS||1;
    if(rd<total){
      var won=(s.winner_idx===MY_IDX);
      var txt;
      if(ADV_GOAL&&ADV_GOAL.type==="score"){
        var cur=(s.scores&&s.scores["东"])||0;
        var target=ADV_GOAL.target||0;
        txt="第"+rd+"局结束（当前累计"+cur+"分，还差"+Math.max(0,target-cur)+"分），还有"+(total-rd)+"局机会，再来一局！";
      }else{
        txt=won?("第"+rd+"局结束（目标尚未达成），还有"+(total-rd)+"局机会，再来一局！"):("第"+rd+"局结束，还有"+(total-rd)+"局机会，再来一局！");
      }
      playStory([{speaker:"旁白",text:txt,choices:null}],function(){nx()});
    }else{
      playStory([{speaker:"旁白",text:"你输了，再接再厉吧！",choices:null}],function(){location.href="/adventure"});
    }
  }
}
async function markAdventureComplete(level){
  try{
    var p=await (await fetch(q("/api/adventure/progress"))).json();
    if(!p.progress)return;
    var pr=p.progress;
    var done=pr.completed_levels||[];if(done.indexOf(level)<0)done.push(level);
    pr.completed_levels=done;
    // 推进到下一关(按章节顺序) + 过关奖励番种解锁
    var cfg=await (await fetch(q("/api/adventure/config"))).json();
    var ids=[];var reward=[];
    (cfg.chapters||[]).forEach(function(ch){(ch.levels||[]).forEach(function(lv){ids.push(lv.id);if(lv.id===level&&lv.reward_yaku)reward=lv.reward_yaku})});
    var cur=ids.indexOf(level);
    if(cur>=0&&cur<ids.length-1)pr.current_level=ids[cur+1];
    if(reward.length){
      var u=pr.unlocked_yaku||[];
      reward.forEach(function(y){if(u.indexOf(y)<0)u.push(y)});
      pr.unlocked_yaku=u;
    }
    // 番种替换(如1-2: 番牌刻升级为字刻 -> 退役番牌刻)
    var cfg2=cfg.chapters||[];
    var repl={};
    cfg2.forEach(function(ch){(ch.levels||[]).forEach(function(lv){if(lv.id===level&&lv.replace_yaku)repl=lv.replace_yaku})});
    if(Object.keys(repl).length){
      var u=pr.unlocked_yaku||[];
      var changed=false;
      Object.keys(repl).forEach(function(old){
        var idx=u.indexOf(old);
        if(idx>=0){u.splice(idx,1);changed=true}
        var neu=repl[old];
        if(u.indexOf(neu)<0)u.push(neu);
      });
      if(changed)pr.unlocked_yaku=u;
    }
    await fetch(q("/api/adventure/progress"),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({progress:pr})});
  }catch(e){}
}
document.addEventListener("click",function(e){
  var ov=E("dialog-overlay");
  if(ov&&ov.style.display!=="none"&&ov.contains(e.target))dialogAdvance();
});
document.addEventListener("keydown",function(e){
  if(e.key==="Enter"){
    var ov=E("dialog-overlay");
    if(ov&&ov.style.display!=="none"){e.preventDefault();dialogAdvance()}
  }
});
function nx(){act("next_round");var x=E("result-overlay");if(x)x.remove()}
function nx2(){nx()}
function pla(idx,s){
  var p=s.players[idx];
  // 联机/单机视角旋转: 自己的座位(MY_IDX)永远显示在下方
  var ids=["bottom","right","top","left"];
  var id=ids[(idx-(MY_IDX<0?0:MY_IDX)+4)%4];
  var wd=E("wind-"+id); if(wd)wd.textContent=ROLES[idx]||"";
  var nm=E("name-"+id); if(nm){
    nm.textContent=NAMES[idx]||ROLES[idx]||id;
    if(ADV_LEVEL&&idx===MY_IDX){
      var sc=s.scores&&s.scores[ROLES[idx]];
      if(sc!==undefined)nm.textContent+="  ("+sc+"分)";
    }
  }
  var hEl=E("hand-"+id); if(hEl){
    hEl.innerHTML="";
    if(idx===MY_IDX&&s.human_hand){
      var dr=s.drawn_tile;
      if(dr){var skip=false;s.human_hand.forEach(function(sh){if(sh===dr&&!skip){skip=true;return}hEl.appendChild(tile(sh,true))});var g=document.createElement("span");g.className="hand-gap";hEl.appendChild(g);hEl.appendChild(tile(dr,true))}
      else{s.human_hand.forEach(function(sh){hEl.appendChild(tile(sh,true))})}
    }else{var c=document.createElement("span");c.className="opp-hand-count";c.textContent=p.hand_count;hEl.appendChild(c)}
  }
  var mEl=E("melds-"+id);if(mEl){mEl.innerHTML="";p.melds.forEach(function(m){mEl.appendChild(renderMeldGroup(m))})}
  var rEl=E("river-"+id);if(rEl){var prev=PREV_DISCARD_COUNTS[idx]||0,cur=p.discards.length;if(cur<prev){rEl.innerHTML="";prev=0}for(var di=prev;di<cur;di++){var t=tile(p.discards[di],false);if(di===cur-1&&s.last_discard_by===idx&&s.last_discard_by!==LAST_POP_BY)t.classList.add("tile-pop");rEl.appendChild(t)}PREV_DISCARD_COUNTS[idx]=cur;if(id==="bottom")LAST_POP_BY=s.last_discard_by!=null?s.last_discard_by:-1}
}
function melds(s){var mb=E("meld-btns"),cs=E("chow-sub"),as=s.actions||[];if(!mb||!cs)return;mb.style.display="none";mb.innerHTML="";cs.style.display="none";cs.innerHTML="";if(!as.length)return;as.forEach(function(a){switch(a.type){case"tsumo":mb.appendChild(mkb("tsumo","自摸",function(){act("tsumo")}));break;case"skip":mb.appendChild(mkb("skip","跳过",function(){act("skip")}));break;case"pass":mb.appendChild(mkb("pass","过",function(){act("pass")}));break;case"pung":mb.appendChild(mkb("pung","碰",function(){act("pung")}));break;case"kong":mb.appendChild(mkb("kong","杠",function(){act("kong")}));break;case"ron":mb.appendChild(mkb("ron","和",function(){act("ron")}));break;case"dark_kong":mb.appendChild(mkb("dark","暗杠 "+a.tile,function(){act("dark_kong",{tile:a.tile})}));break;case"add_kong":mb.appendChild(mkb("dark","加杠 "+a.tile,function(){act("add_kong",{tile:a.tile,meld_idx:a.meld_idx})}));break;case"chow":var chBtn=mkb("pung","吃",function(){var c=document.getElementById("chow-sub");c.style.display=(c.style.display=="none"?"flex":"none")});mb.appendChild(chBtn);if(a.options){a.options.forEach(function(opt,i){var d=document.createElement("div");d.className="chow-opt";opt.forEach(function(sh){d.appendChild(tile(sh,false))});d.addEventListener("click",function(){act("chow",{choice:i})});cs.appendChild(d)})}break}});if(mb.children.length)mb.style.display="flex"}
function mkb(cls,txt,onclk){var d=document.createElement("div");d.className="meld-act "+cls;d.textContent=txt;d.addEventListener("click",onclk);return d}
window.addEventListener("DOMContentLoaded",function(){conn();E("hand-bottom").addEventListener("wheel",function(e){if(e.deltaY){e.preventDefault();this.scrollLeft+=e.deltaY}},{passive:false})})
