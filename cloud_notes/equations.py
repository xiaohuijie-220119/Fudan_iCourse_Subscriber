"""Editable native Word equations, with XML-safe conversion and structural fallback."""
import re
from lxml import etree
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

def element(name,*children):
    out=OxmlElement('m:'+name)
    for child in children:out.append(child)
    return out

def run(text):
    node=element('t');node.text=text or ''
    node.set(qn('xml:space'),'preserve')
    return element('r',node)

def structural(node):
    tag=etree.QName(node).localname;children=list(node)
    def child(i):return structural(children[i]) if i<len(children) else run('')
    if tag in ('mi','mn','mo','mtext','ms'):return run(''.join(node.itertext()))
    if tag=='mfrac':return element('f',element('num',child(0)),element('den',child(1)))
    if tag in ('msup','msub','msubsup'):
        name={'msup':'sSup','msub':'sSub','msubsup':'sSubSup'}[tag]
        out=element(name,element('e',child(0)))
        for index,label in enumerate((['sup'] if tag=='msup' else ['sub'] if tag=='msub' else ['sub','sup']),1):out.append(element(label,child(index)))
        return out
    if tag in ('msqrt','mroot'):
        props=element('radPr')
        if tag=='msqrt':
            hide=element('degHide');hide.set(qn('m:val'),'1');props.append(hide)
            content=element('e',*(structural(c) for c in children));degree=element('deg')
        else:content=element('e',child(0));degree=element('deg',child(1))
        return element('rad',props,degree,content)
    if tag in ('mover','munder','munderover'):
        out=child(0)
        if tag in ('munder','munderover'):out=element('limLow',element('e',out),element('lim',child(1)))
        if tag in ('mover','munderover'):out=element('limUpp',element('e',out),element('lim',child(2 if tag=='munderover' else 1)))
        return out
    if tag=='mtable':return element('m',*(structural(c) for c in children))
    if tag=='mtr':return element('mr',*(structural(c) for c in children))
    if tag=='mtd':return element('e',*(structural(c) for c in children))
    if tag=='mspace':return run(' ')
    if tag=='mfenced':
        return element('box',element('e',run(node.get('open','(')),*(structural(c) for c in children),run(node.get('close',')'))))
    return element('box',element('e',*(structural(c) for c in children))) if children else run(node.text or '')

def convert_equation(latex):
    from latex2mathml.converter import convert
    from latex2mathml.exceptions import MissingEndError
    from mathml2omml import convert as omml
    try:mathml=convert(latex)
    except MissingEndError:
        repaired=close_missing_environments(latex)
        if repaired==latex:raise
        mathml=convert(repaired)
    mathml=re.sub(r'&(?!#\d+;|#x[0-9A-Fa-f]+;|amp;|lt;|gt;|quot;|apos;)','&amp;',mathml)
    parser=etree.XMLParser(resolve_entities=False,no_network=True)
    source=etree.fromstring(mathml.encode(),parser)
    try:
        xml=omml(mathml)
        # mathml2omml 0.0.2 incorrectly closes groupChrPr as groupChr.
        xml=re.sub(r'(<m:groupChrPr>(?:(?!</m:groupChrPr>).)*?)</m:groupChr>',r'\1</m:groupChrPr>',xml,flags=re.S)
        xml=xml.replace('<m:oMath>','<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">',1)
        return etree.fromstring(xml.encode(),parser)
    except Exception:
        return element('oMath',structural(source))

def close_missing_environments(latex):
    """Close unambiguous unclosed environments; never change existing mathematics."""
    stack=[]
    for match in re.finditer(r'\\(begin|end)\{([A-Za-z*]+)\}',latex):
        action,name=match.groups()
        if action=='begin':stack.append(name)
        elif not stack or stack[-1]!=name:return latex
        else:stack.pop()
    if len(stack)>12:return latex
    return latex+''.join(r'\end{'+name+'}' for name in reversed(stack))
