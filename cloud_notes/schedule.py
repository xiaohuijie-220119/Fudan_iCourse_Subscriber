import re

def cron_for(time):
    if not isinstance(time,str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',time):
        raise ValueError('时间应为北京时间 HH:MM')
    hour, minute = map(int,time.split(':'))
    return f'{minute} {(hour-8)%24} * * *'

def update_workflow(text, time):
    text = text.replace('\r\n','\n')
    cron = cron_for(time)
    if '  schedule:' not in text and '  workflow_dispatch:' in text:
        return text.replace('on:\n','on:\n  schedule:\n    - cron: "'+cron+'"\n',1)
    updated, count = re.subn(r'(?m)^(\s*- cron: )"[^"\n]+"',lambda m:m[1]+'"'+cron+'"',text)
    if count != 1: raise ValueError('定时工作流格式不符，未修改')
    return updated
