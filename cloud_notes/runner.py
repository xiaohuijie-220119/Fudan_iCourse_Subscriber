"""Run only in GitHub Actions. Original pipeline, one checkpoint per lecture."""
import contextlib
import io
import json
import os
from pathlib import Path
import time
from datetime import datetime, timezone
from cloud_notes.store import Store

ROOT = Path(__file__).resolve().parents[1]

class Quiet(io.TextIOBase):
    # Upstream diagnostics may contain signed media URLs. Never write them to Actions logs.
    def write(self, value): return len(value)
    def flush(self): pass

def execute():
    started = time.monotonic()
    store = Store(ROOT)
    state = {'phase':'恢复进度', 'total':0, 'completed':0, 'failed':0,
             'updated':datetime.now(timezone.utc).isoformat()}
    db = None
    def checkpoint(phase, **values):
        state.update(values, phase=phase, updated=datetime.now(timezone.utc).isoformat(),
                     run_id=os.environ.get('GITHUB_RUN_ID',''))
        store.save(db,state)
    # Failure to decrypt must stop, rather than overwrite old work with empty state.
    store.restore()
    with contextlib.redirect_stdout(Quiet()), contextlib.redirect_stderr(Quiet()):
        import main as upstream
        from src.runtime import config
        from src.data.database import Database
        from src.api.icourse import ICourseClient
        from src.pipeline.lecture_runner import LectureRunner
        from src.runtime.reporter import Reporter
        from src.runtime.scheduler import Scheduler
        from src.ai.summarizer import Summarizer
        from src.ai.transcriber import Transcriber
        from cloud_notes.auth import observed_vpn
        from cloud_notes.word import create_word, send_attachment
        if not config.COURSE_IDS: raise ValueError('course_ids_missing')
        reporter = Reporter(); db = Database()
        def login():
            last = None
            for attempt in range(3):
                vpn = None
                try:
                    checkpoint('统一身份认证', attempt=attempt+1)
                    vpn = observed_vpn(state)
                    vpn.login()
                    checkpoint('验证课程接口')
                    vpn.authenticate_icourse()
                    client = ICourseClient(vpn)
                    if not client.check_alive(): raise RuntimeError('icourse_api_verification_failed')
                    return client
                except Exception as error:
                    last = error
                    if vpn: vpn.session.close()
                    # Never repeat rejected credentials or MFA challenges automatically.
                    import requests
                    if isinstance(error,requests.exceptions.SSLError) or not isinstance(error,(requests.Timeout, requests.ConnectionError)):
                        raise
                    time.sleep(5*(attempt+1))
            raise last
        try:
            client = login()
            checkpoint('读取课程')
            lectures = upstream._enumerate_lectures(client,db,reporter)
            # Upstream catches enumeration errors; don't report an empty failed enumeration as success.
            for course in config.COURSE_IDS:
                client.get_course_detail(course)
            state['total'] = len(lectures)
            scheduler = Scheduler(reporter=reporter)
            try:
                transcriber, summarizer = Transcriber(), Summarizer()
                runner = LectureRunner(client,db,scheduler,transcriber,summarizer,reporter)
                def deliver(row):
                    import tempfile
                    from src.api.icourse import fetch_ppt_image
                    from PIL import Image
                    with tempfile.TemporaryDirectory() as images_dir:
                        pictures=[]
                        pages=db.conn.execute('SELECT page_num,pptimgurl FROM ppt_pages WHERE sub_id=? AND pptimgurl IS NOT NULL ORDER BY created_sec',(row['sub_id'],)).fetchall()
                        # Evenly spaced examples rather than the first six title slides.
                        positions=sorted({round(i*(len(pages)-1)/5) for i in range(6)}) if pages else []
                        for index in positions:
                            page=dict(pages[index]);raw=fetch_ppt_image(client,page,max_attempts=1,timeout=15)
                            if not raw or len(raw)>15*1024*1024:continue
                            try:
                                image=Image.open(io.BytesIO(raw));image.verify()
                                path=Path(images_dir)/(str(index)+'.jpg')
                                image=Image.open(io.BytesIO(raw))
                                if image.width*image.height>30000000:continue
                                image.thumbnail((1800,1400))
                                image.convert('RGB').save(path,quality=88)
                                pictures.append(('课堂课件第 '+str(page['page_num'])+' 页',path))
                            except Exception:continue
                        doc = create_word(row,ROOT,pictures=pictures)
                    checkpoint('Word 已保存')
                    if not row.get('emailed_at'):
                        settings = {k:os.environ.get(k,'') for k in ('SMTP_EMAIL','SMTP_PASSWORD','RECEIVER_EMAIL')}
                        if not all(settings.values()): raise ValueError('mail_configuration_missing')
                        if not send_attachment(doc,row,settings): raise RuntimeError('mail_not_accepted')
                        db.mark_emailed(row['sub_id'])
                        checkpoint('附件邮件已发送')
                # Retry document/mail failures even when transcription is already complete.
                for row in db.get_unsent_lectures():
                    try: deliver(row)
                    except Exception: state['failed'] += 1; checkpoint('有文档或邮件待重试')
                for course_id, title, lecture in lectures:
                    # Leave enough time for final checkpoint before the Actions hard limit.
                    if time.monotonic()-started > 4.5*3600:
                        checkpoint('本批结束，下次继续'); return
                    sid = str(lecture['sub_id'])
                    checkpoint('转写与整理',current=lecture.get('sub_title',sid),course=title)
                    try:
                        if not client.check_alive():
                            refreshed=login(); client.vpn=refreshed.vpn; client._userinfo=None
                        summary = runner.run(course_id,title,lecture)
                        if not summary: raise RuntimeError('lecture_incomplete')
                        row = dict(db.get_lecture(sid)); row['course_title'] = title
                        deliver(row)
                        state['completed'] += 1
                    except Exception as error:
                        state['failed'] += 1
                        state['error_type'] = type(error).__name__
                    finally:
                        scheduler.image_cache.discard(sid)
                        scheduler.audio_downloader.release(sid)
                        checkpoint('课次已保存')
            finally: scheduler.shutdown()
            checkpoint('部分课次待重试' if state['failed'] else '本次检查完成')
            if state['failed']: raise RuntimeError('lectures_need_retry')
        except Exception as error:
            checkpoint('任务未完成', failure_phase=state['phase']+' / '+state.get('auth_step',''), error_type=type(error).__name__)
            raise
        finally:
            if db: db.conn.close()

if __name__ == '__main__':
    try:
        execute()
        print('云端检查结束；详细进度请在本机工作台查看。')
    except Exception as error:
        print('云端任务未完成，错误类别：'+type(error).__name__+'。请在工作台查看失败阶段。')
        raise SystemExit(1)
