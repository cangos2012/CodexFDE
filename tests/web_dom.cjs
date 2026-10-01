/* Small DOM fixture for behavior tests; no browser state or live data. */
function dom() {
  const nodes = new Map(), listeners = new Map();
  function element(tag) {
    const el = {tag, value:'', textContent:'', hidden:false, disabled:false, dataset:{}, children:[],
      classList:{toggle(){},add(){},remove(){}}, setAttribute(){}, removeAttribute(){},
      append(...children){this.children.push(...children);}, appendChild(child){this.append(child);},
      replaceChildren(...children){this.children=children;},
      contains(target){return this===target || this.children.some(c=>c.contains?.(target));},
      showModal(){this.hidden=false;},close(){this.hidden=true;},dispatchEvent(){},
      querySelectorAll(selector){
        const found=[];
        const match=(node,s)=>{
          const m=/^([a-z]*)?(?:\[([^=\]]+)(?:="([^"]*)")?\])?$/.exec(s);
          if(!m)return false;
          if(m[1] && node.tag!==m[1])return false;
          if(m[2]){const key=m[2].replace(/^data-/, '').replace(/-([a-z])/g,(_,c)=>c.toUpperCase());
            return m[3]===undefined ? node.dataset[key]!==undefined : node.dataset[key]===m[3];}
          return true;
        };
        const visit=node=>{for(const child of node.children){if(selector.split(',').some(s=>match(child,s.trim())))found.push(child);visit(child);}};
        visit(this);return found;
      },querySelector(s){return this.querySelectorAll(s)[0] || null;}
    };return el;
  }
  const document={createElement:element,getElementById(id){if(!nodes.has(id))nodes.set(id,element('div'));return nodes.get(id);},
    addEventListener(type,fn){listeners.set(type,fn);},querySelectorAll(){return [];},querySelector(){return null;}};
  return {document, nodes, element, listeners, node:id=>document.getElementById(id)};
}
function storage() {
  const data=new Map();return {get length(){return data.size;},key:i=>[...data.keys()][i],getItem:k=>data.get(k) ?? null,
    setItem:(k,v)=>data.set(k,v),removeItem:k=>data.delete(k),data};
}
module.exports={dom,storage};
