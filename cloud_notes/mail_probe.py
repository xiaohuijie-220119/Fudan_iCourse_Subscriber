"""Cloud-only attachment test using existing Secrets; no course login or transcription."""
import os
import tempfile
from pathlib import Path
from datetime import datetime,timezone
from cloud_notes.store import Store
from cloud_notes.word import create_word,send_attachment
from cloud_notes.diagnostics import describe

def execute():
    root=Path(__file__).resolve().parents[1]
    store=Store(root);store.restore()
    state={'phase':'附件邮件连接测试','mode':'test-mail','updated':datetime.now(timezone.utc).isoformat(),
           'run_id':os.environ.get('GITHUB_RUN_ID',''),'failed':0}
    try:
        settings={k:os.environ.get(k,'') for k in ('SMTP_EMAIL','SMTP_PASSWORD','RECEIVER_EMAIL')}
        if not all(settings.values()):raise ValueError('missing_mail_configuration')
        with tempfile.TemporaryDirectory() as directory:
            row={'sub_id':'connection-test','course_title':'iCourse 邮件连接测试','sub_title':'Word 附件测试',
                 'summary':'### 连接测试\n收到这封邮件和 Word 附件，说明云端发送通道正常。此文件不包含课程内容或凭据。'}
            path=create_word(row,Path(directory))
            if not send_attachment(path,row,settings):raise RuntimeError('mail_not_accepted')
        state['phase']='附件测试邮件已发送'
        store.save(None,state)
        print('测试附件邮件已发送。')
    except Exception as error:
        item=describe('附件邮件发送',error)
        state.update(phase='附件邮件测试失败',failed=1,failure_phase=item['stage'],error_type=item['error_type'],errors=[item])
        store.save(None,state)
        print('附件邮件测试失败：'+item['error_type']+'；'+item['reason']+'；状态码 '+str(item.get('response_code','无')))
        raise SystemExit(1)

if __name__=='__main__':execute()
