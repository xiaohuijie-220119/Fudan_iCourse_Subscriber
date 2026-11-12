"""Fixed failure categories only. Never expose exception text, recipients or signed URLs."""
import smtplib
import ssl

class CourseAuthenticationError(RuntimeError):
    def __init__(self, code, *, missing_ticket=False):
        value = str(code) if type(code) in (int, str) else ''
        self.business_code = value if value.isascii() and value.isdecimal() and len(value) <= 10 else None
        self.missing_ticket = missing_ticket
        super().__init__('course_authentication_failed')

class StageError(RuntimeError):
    def __init__(self,stage,cause):
        self.stage=stage;self.cause=cause
        super().__init__('course_stage_failed')

def describe(stage,error):
    if isinstance(error,StageError):stage,error=error.stage,error.cause
    seen=set()
    while getattr(error,'__cause__',None) is not None and id(error) not in seen and len(seen)<8:
        seen.add(id(error));error=error.__cause__
    reason='该步骤未完成'
    if isinstance(error,smtplib.SMTPAuthenticationError):reason='邮箱登录被拒绝，请核对发件邮箱和 SMTP 授权码'
    elif isinstance(error,smtplib.SMTPRecipientsRefused):reason='收件地址被邮件服务器拒绝'
    elif isinstance(error,smtplib.SMTPSenderRefused):reason='发件地址被邮件服务器拒绝'
    elif isinstance(error,smtplib.SMTPDataError):reason='邮件内容或附件被服务器拒绝'
    elif isinstance(error,smtplib.SMTPServerDisconnected):reason='SMTP 连接被邮件服务器断开'
    elif isinstance(error,(TimeoutError,)):reason='连接或读取响应超时'
    elif isinstance(error,ssl.SSLError):reason='HTTPS 或 SMTP 加密连接失败'
    result={'stage':stage,'error_type':type(error).__name__,'reason':reason}
    if isinstance(error,CourseAuthenticationError):
        result['reason'] = ('学校返回成功业务码，但未提供登录票据' if error.missing_ticket else '学校课程认证未通过')
        if error.business_code:
            result['reason'] += '（学校业务码：'+error.business_code+'）'
        return result
    code=getattr(error,'smtp_code',getattr(error,'status_code',None))
    if isinstance(code,int) and 100<=code<=599:
        result['response_code']=code
        if not isinstance(error,smtplib.SMTPException):
            reasons={401:'服务拒绝 API 身份认证，请核对对应密钥',402:'服务报告余额或额度不足',
                     403:'服务拒绝此请求的访问权限',429:'服务限流或配额受限',
                     500:'服务内部错误',502:'服务网关异常',503:'服务暂时不可用',504:'服务网关超时'}
            result['reason']=reasons.get(code,result['reason'])
    return result
