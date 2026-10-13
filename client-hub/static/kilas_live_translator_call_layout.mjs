// Viewport-only call layout: no Fullscreen API, microphone or network work.
export class TranslatorCallLayout {
  constructor({document,root,endButton}){Object.assign(this,{document,root,endButton});this.active=false;this.background=[];}
  setActive(active){
    const body=this.document.body;
    if(active===this.active||!body?.appendChild||!this.root?.parentNode)return;
    if(active){
      this.parent=this.root.parentNode;this.next=this.root.nextSibling;this.focus=this.document.activeElement;
      // Moving the scoped surface avoids fixed-position containment by app shells.
      body.appendChild(this.root);
      this.background=[...body.children].filter(node=>node!==this.root&&!['SCRIPT','STYLE','LINK'].includes(node.tagName)).map(node=>{
        const attributes=['inert','aria-hidden','data-kilas-translator-call-background'].map(name=>[name,node.getAttribute(name)]);
        node.setAttribute('inert','');node.setAttribute('aria-hidden','true');node.setAttribute('data-kilas-translator-call-background','');
        return {node,attributes};
      });
      body.classList.add('kilas-translator-call-active');this.active=true;
      this.endButton?.focus?.({preventScroll:true});
    }else{
      body.classList.remove('kilas-translator-call-active');
      this.parent.insertBefore(this.root,this.next?.parentNode===this.parent?this.next:null);
      for(const {node,attributes} of this.background)for(const [name,value] of attributes){if(value===null)node.removeAttribute(name);else node.setAttribute(name,value);}
      this.background=[];this.active=false;this.focus?.focus?.({preventScroll:true});
    }
  }
}
