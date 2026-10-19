"""Beijing calendar cutoff and credential-free per-lecture status."""
from datetime import datetime,timedelta,timezone,date
import re

BEIJING=timezone(timedelta(hours=8))

def lecture_date(row):
    for value in (row.get('date',''),row.get('sub_title','')):
        match=re.search(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})',str(value or ''))
        if match:
            try:return date(*map(int,match.groups()))
            except ValueError:pass
    return None

def eligible(row,now=None):
    now=now or datetime.now(BEIJING)
    if now.tzinfo is None:raise ValueError('Timezone required')
    day=lecture_date(row)
    return day is not None and day < now.astimezone(BEIJING).date()

def snapshot(db,now=None,documents=()):
    rows=db.conn.execute('SELECT l.*,c.title AS course_title FROM lectures l LEFT JOIN courses c ON c.course_id=l.course_id ORDER BY l.date DESC,l.sub_title DESC').fetchall()
    out=[]
    labels={'no_video':'等待回放审核或开放','transcribe':'音频转写','summarize':'AI 笔记生成'}
    for raw in rows:
        row=dict(raw);transcribed=bool(row.get('transcript'));summary=bool(row.get('summary'))
        stage=row.get('error_stage')
        status='已发送' if row.get('emailed_at') else '已整理' if summary else '已转录' if transcribed else '待处理'
        reason=''
        if stage=='no_video':status='等待回放';reason=labels[stage]
        elif stage:status='失败';reason=labels.get(stage,'课程处理')
        if not summary and not eligible(row,now):
            status='等待回放';reason='当天或未来课次，明天起再检查' if lecture_date(row) else '课次日期无法识别，暂不自动转写'
        out.append({'id':str(row['sub_id']),'course':row.get('course_title') or row['course_id'],
                    'lecture':row.get('sub_title') or str(row['sub_id']),'date':row.get('date',''),
                    'status':status,'transcribed':transcribed,'summarized':summary,
                    'word_saved':any(d['path'].endswith('_'+str(row['sub_id'])+'.docx') for d in documents),
                    'emailed':bool(row.get('emailed_at')),'reason':reason})
    return out
