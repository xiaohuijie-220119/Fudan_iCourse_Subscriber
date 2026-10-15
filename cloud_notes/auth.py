"""Authentication diagnostics contain only fixed labels, status numbers and exception types."""
from urllib.parse import urlsplit
import requests
from src.api.webvpn import WebVPNSession

LABELS={'authenticate':'认证入口','queryAuthMethods':'认证方式','getJsPublicKey':'密码加密公钥',
        'authExecute':'提交身份认证','authnEngine':'获取认证票据','casapi':'课程登录跳转',
        'infosimple':'课程接口验证'}

class ObservedSession(requests.Session):
    def __init__(self,state):
        super().__init__();self.state=state;self.max_redirects=12
    def send(self,request,**kwargs):
        path=urlsplit(request.url).path.rstrip('/').split('/')[-1]
        self.state['auth_step']=LABELS.get(path,'建立学校会话')
        self.state.pop('http_status',None)
        try:
            response=super().send(request,**kwargs)
            self.state['http_status']=response.status_code
            return response
        except Exception as error:
            self.state['error_type']=type(error).__name__
            raise

def observed_vpn(state):
    vpn=WebVPNSession()
    headers=dict(vpn.session.headers);vpn.session.close()
    vpn.session=ObservedSession(state);vpn.session.headers.update(headers)
    # An unauthenticated probe distinguishes network reachability from login success.
    state['auth_step']='学校入口连通性'
    response=vpn.session.get('https://webvpn.fudan.edu.cn/',allow_redirects=False,timeout=(10,15))
    if response.status_code not in (200,301,302,303,307,308):
        raise RuntimeError('school_portal_unavailable')
    return vpn
