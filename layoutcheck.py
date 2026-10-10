"""Layout auditor: walks every section and view at phone and desktop widths and flags anything that isn't lined up.
Checks: horizontal overflow; panels that stick out of the content column; side-by-side columns whose tops or bottoms
don't match; uneven gaps between stacked panels; elements wider than the screen."""
import asyncio,sys,json
from playwright.async_api import async_playwright
VIEWS=[('today','brief'),('news','list'),('mna','deals'),('mna','map'),('mna','players'),('clock','list'),('clock','calendar'),('fuel',None),('docs','library'),('docs','alerts'),('docs','earnings'),('docs','decoder')]
JS=r"""()=>{const F=[];const R=e=>e.getBoundingClientRect();const sec=document.querySelector('[data-section]:not([hidden])');if(!sec)return F;
 const view=[...sec.querySelectorAll('.view')].find(v=>v.offsetParent!==null)||sec;
 const wrap=R(sec);const vw=innerWidth;
 if(document.documentElement.scrollWidth>vw+1)F.push('page scrolls sideways: '+document.documentElement.scrollWidth+'px');
 const vis=e=>e.offsetParent!==null&&R(e).width>0;
 const blocks=[...view.querySelectorAll('.panel,.cfly,.cards>.card,.deal2,.fcard')].filter(vis);
 const top=[...view.children,...(view===sec?[]:[...sec.children])];
 for(const b of blocks){const r=R(b);if(r.left<wrap.left-1.5||r.right>wrap.right+1.5)F.push(`${b.className.split(' ')[0]} sticks out of the column (${Math.round(r.left)}–${Math.round(r.right)} vs ${Math.round(wrap.left)}–${Math.round(wrap.right)})`)}
 // side-by-side columns: same top and bottom
 for(const g of view.querySelectorAll('.stack.two')){if(!vis(g))continue;const cs=[...g.children].filter(vis);if(cs.length<2)continue;const a=R(cs[0]),b=R(cs[1]);
   if(Math.abs(a.top-b.top)<4&&a.right<=b.left+2){if(Math.abs(a.bottom-b.bottom)>2)F.push(`columns end at different heights (${Math.round(a.bottom)} vs ${Math.round(b.bottom)})`)}}
 // even gaps between stacked full-width blocks in the view
 const stackKids=[...view.querySelectorAll(':scope > *, :scope > .stack > *, :scope > .stack > .col > *')].filter(e=>vis(e)&&R(e).height>8&&R(e).width>wrap.width*.9);
 const gaps=[];for(let i=1;i<stackKids.length;i++){const g=Math.round(R(stackKids[i]).top-R(stackKids[i-1]).bottom);if(g>=0&&g<200)gaps.push(g)}
 const odd=[...new Set(gaps)].filter(g=>g!==0&&g!==16&&g!==12&&g!==24);if(odd.length)F.push('uneven vertical gaps: '+JSON.stringify(gaps));
 for(const e of view.querySelectorAll('*')){if(!vis(e))continue;const r=R(e);const clipped=(()=>{let a=e.parentElement;while(a&&a!==document.body){const o=getComputedStyle(a);if(o.overflowX!=='visible'||o.overflow!=='visible')return true;a=a.parentElement}return false})();if(r.right>vw+1&&!clipped&&getComputedStyle(e).position!=='fixed'){F.push('element past the right edge: '+(e.className||e.tagName));break}}
 return F}"""
async def main(path):
  out={}
  async with async_playwright() as p:
    b=await p.chromium.launch()
    for w,h in ((1280,1000),(390,900)):
      pg=await b.new_page(viewport={'width':w,'height':h});await pg.goto('file://'+path);await pg.wait_for_timeout(1500)
      await pg.evaluate("document.querySelector('#coop')&&(document.querySelector('#coop').style.display='none')")
      for t,v in VIEWS:
        await pg.evaluate(f"goTo('{t}'{','+repr(v) if v else ''})");await pg.wait_for_timeout(500)
        f=await pg.evaluate(JS)
        if f:out[f'{w} {t}/{v}']=f
    await b.close()
  for k,v in out.items():print(k);[print('   -',x) for x in v]
  print('layout findings:',sum(len(v) for v in out.values()))
asyncio.run(main(sys.argv[1]))
