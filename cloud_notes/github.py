"""GitHub API client. Never expose server replies, request URLs or tokens in errors."""
import base64
import hashlib
import http.client
import socket
import ssl
import time
import json
import re
import urllib.request
import urllib.error

class GitHubConnectionError(RuntimeError):
    """Safe, fixed transport diagnostic; never include URLs or exception text."""
    pass

class APIError(RuntimeError):
    def __init__(self, status, operation='GitHub 操作', reason='', permissions=''):
        self.status = status
        self.operation=operation
        self.reason=reason;self.permissions=permissions
        details=('；'+reason) if reason else ''
        if permissions:details+='；接口要求：'+permissions
        super().__init__(f'{operation}失败（HTTP {status}）'+details)

def safe_failure(error,path,method):
    """Translate only known error categories; never return raw body/URLs/headers."""
    labels=[('/actions/secrets','读取或上传云端配置'),('/actions/variables','保存模型设置'),
            ('/git/blobs','上传代码文件'),('/git/trees','读取或构建代码目录'),
            ('/git/commits','创建代码提交'),('/git/refs','更新云端分支'),
            ('/git/ref/','读取云端分支'),('/actions/workflows','读取或控制工作流'),
            ('/actions/runs','检查运行中的任务')]
    operation=next((label for prefix,label in labels if path.startswith(prefix)),'连接 GitHub 仓库')
    workflow=re.fullmatch(r'/actions/workflows/(check\.yml|single_run\.yml|cloud-notes\.yml|\d+)(?:/(enable|disable|dispatches|runs))?(?:\?[^\n]*)?',path)
    if workflow:
        action={'enable':'启用工作流','disable':'停用工作流','dispatches':'启动课程检查','runs':'读取任务记录',None:'读取工作流状态'}[workflow[2]]
        operation=action+' '+workflow[1]
    headers=error.headers or {}
    permission=headers.get('X-Accepted-GitHub-Permissions','')
    if not re.fullmatch(r'[a-z_]+=(?:read|write)(?:[ ,;]+[a-z_]+=(?:read|write))*',permission):permission=''
    try:message=str(json.loads(error.read(16000)).get('message','')).lower()
    except Exception:message=''
    reason=''
    if 'cannot trigger' in message and 'disabled workflow' in message:
        reason='这个工作流目前已停用，需要先启用 iCourse Cloud Notes，才能启动课程检查'
    elif 'workflow_dispatch' in message and any(word in message for word in ('does not have','not found','not configured')):
        reason='GitHub 尚未识别该分支的手动启动入口，请核对默认分支中的工作流文件'
    elif 'ref' in message and any(word in message for word in ('not found','no ref','invalid ref')):
        reason='请求的分支不存在，请重新验证仓库默认分支'
    elif headers.get('X-RateLimit-Remaining')=='0':reason='GitHub API 配额已用完，请稍后再试，不必修改 Token 权限'
    elif 'rate limit' in message or headers.get('Retry-After'):reason='GitHub 暂时限制请求频率，请稍后再试'
    elif 'workflow' in message and any(word in message for word in ('refusing','permission','scope')):
        reason='Token 缺少 Workflows 写权限；请在 GitHub 编辑这个 Token 的仓库权限'
    elif 'resource not accessible' in message or 'permission' in message:
        reason='Token 对本仓库的权限不足，请核对仓库选择和下方接口要求'
    elif 'admin' in message:reason='GitHub 要求仓库管理员权限'
    elif any(word in message for word in ('disabled','blocked','restricted','suspended')):
        reason='GitHub 报告此仓库、账户或工作流处于受限状态，请检查仓库 Actions 页面'
    elif 'not supported' in message or 'unsupported' in message:
        reason='GitHub 报告此操作不受当前授权方式或工作流状态支持'
    elif error.code==403:reason='GitHub 拒绝访问，需进一步核对仓库权限或平台限制'
    return APIError(error.code,operation,reason,permission)

class GitHub:
    def __init__(self, repo, token):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
            raise ValueError('仓库格式应为 用户名/仓库名')
        self.repo, self.token = repo, token

    def call(self, path, body=None, method=None):
        raw = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request('https://api.github.com/repos/' + self.repo + path,
            data=raw, method=method or ('GET' if raw is None else 'POST'), headers={
            'Authorization': 'Bearer ' + self.token, 'Accept': 'application/vnd.github+json',
            'User-Agent': 'iCourse-Cloud-Workbench', 'X-GitHub-Api-Version': '2022-11-28',
            'Content-Type': 'application/json'})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=30) as response:
                    data = response.read()
                    return json.loads(data) if data else {}
            except urllib.error.HTTPError as error:
                raise safe_failure(error,path,req.method) from None
            except (OSError,http.client.RemoteDisconnected) as error:
                reason=getattr(error,'reason',error)
                transient=isinstance(reason,(ssl.SSLEOFError,TimeoutError,socket.gaierror,
                                             ConnectionError,http.client.RemoteDisconnected))
                if req.method=='GET' and transient and attempt<2:
                    time.sleep(attempt+1)
                    continue
                category=type(reason).__name__
                if isinstance(reason,socket.gaierror):label='DNS 域名解析失败'
                elif isinstance(reason,ssl.SSLCertVerificationError):label='HTTPS 证书校验失败'
                elif isinstance(reason,ssl.SSLEOFError):label='TLS 连接被中途断开'
                elif isinstance(reason,ssl.SSLError):label='TLS 连接失败'
                elif isinstance(reason,(TimeoutError,socket.timeout)):label='网络连接超时'
                else:label='网络连接失败'
                raise GitHubConnectionError('连接 GitHub：'+label+'（'+category+'）') from None
            except ValueError:
                raise GitHubConnectionError('GitHub 返回了无法解析的响应，请检查代理或网络连接') from None

    def head(self, branch):
        try:
            return self.call('/git/ref/heads/' + branch)['object']['sha']
        except APIError as error:
            if error.status == 404: return None
            raise

    def files(self, branch):
        sha = self.head(branch)
        if not sha: return {}
        tree = self.call('/git/trees/' + sha + '?recursive=1')
        if tree.get('truncated'): raise RuntimeError('云端文件清单超出限制')
        return {x['path']: x['sha'] for x in tree['tree'] if x['type'] == 'blob'}

    def blob(self, sha):
        return base64.b64decode(self.call('/git/blobs/' + sha)['content'])

    def commit(self, branch, files, message, expected=None):
        head = self.head(branch)
        if expected is not None and head != expected:
            raise RuntimeError('云端已发生更改，请刷新后重试')
        entries = []
        existing={}
        if head:
            listing=self.call('/git/trees/'+head+'?recursive=1')
            if listing.get('truncated'):raise ValueError('仓库目录过大，停止部署以保护现有内容')
            existing={item['path']:item['sha'] for item in listing['tree'] if item['type']=='blob'}
        for name, raw in files.items():
            digest=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
            if existing.get(name)==digest:continue
            entry={'path':name,'mode':'100644','type':'blob'}
            if name.endswith(('.py','.yml','.yaml','.txt','.md','.json')):
                entry['content']=raw.decode('utf-8')
            else:
                entry['sha']=self.call('/git/blobs', {'content':base64.b64encode(raw).decode(),'encoding':'base64'})['sha']
            entries.append(entry)
        if not entries:return head
        body = {'tree':entries}
        if head: body['base_tree'] = self.call('/git/commits/' + head)['tree']['sha']
        tree = self.call('/git/trees', body)['sha']
        commit = self.call('/git/commits', {'message':message, 'tree':tree, 'parents':[head] if head else []})['sha']
        if head:
            self.call('/git/refs/heads/' + branch, {'sha':commit, 'force':False}, 'PATCH')
        else:
            self.call('/git/refs', {'ref':'refs/heads/' + branch, 'sha':commit})
        return commit
