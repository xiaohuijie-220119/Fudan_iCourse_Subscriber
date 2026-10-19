"""Finish cached notes without contacting school or loading speech models."""
import os
from pathlib import Path
from datetime import datetime,timezone
from cloud_notes.store import Store
from cloud_notes.word import create_word,send_attachment
from cloud_notes.diagnostics import StageError,describe
from src.data.database import Database

def execute(root=None,store=None,send=send_attachment):
    root=Path(root) if root is not None else Path(__file__).resolve().parents[1]
    store=store or Store(root);store.restore()
    if not (root/'data/icourse.db').exists():raise ValueError('云端尚无可补生成的笔记')
    db=Database(str(root/'data/icourse.db'))
    state={'phase':'补生成已有笔记','mode':'recover-notes','total':0,'completed':0,'failed':0,'errors':[]}
    def save():
        state.update(updated=datetime.now(timezone.utc).isoformat(),run_id=os.environ.get('GITHUB_RUN_ID',''))
        store.save(db,state)
    try:
        rows=db.get_unsent_lectures();state['total']=len(rows);save()
        for row in rows:
            stage='Word 生成与公式转换'
            state.update(current=row.get('sub_title',''),course=row.get('course_title',''))
            try:
                path=create_word(row,root)
                state['phase']='Word 已保存';save()
                stage='附件邮件发送'
                settings={k:os.environ.get(k,'') for k in ('SMTP_EMAIL','SMTP_PASSWORD','RECEIVER_EMAIL')}
                if not all(settings.values()):raise ValueError('missing_mail_configuration')
                if not send(path,row,settings):raise RuntimeError('mail_not_accepted')
                db.mark_emailed(row['sub_id']);state['completed']+=1
            except Exception as error:
                item=describe(stage,error)
                item.update(course=row.get('course_title',''),lecture=row.get('sub_title',''))
                state['errors'].append(item);state['failed']+=1
                state.update(failure_phase=item['stage'],error_type=item['error_type'])
            finally:save()
        state['phase']='补生成完成' if not state['failed'] else '部分笔记仍待处理';save()
        return state
    finally:db.conn.close()

if __name__=='__main__':
    try:
        result=execute()
        print('已有笔记补生成结束；完成 '+str(result['completed'])+'，失败 '+str(result['failed']))
        raise SystemExit(1 if result['failed'] else 0)
    except Exception as error:
        print('已有笔记补生成未完成：'+type(error).__name__)
        raise SystemExit(1)
