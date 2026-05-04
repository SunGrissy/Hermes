import json, pathlib, datetime, re
base=pathlib.Path('D:/MyAgents/tmp/april_reports')

def load(name):
    return json.loads((base/f'{name}.json').read_text(encoding='utf-8'))['result']['report_list']

def dt(ms):
    # timestamp seems ms; convert local roughly
    return datetime.datetime.fromtimestamp(ms/1000, datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')

for name in ['weekly_april','daily_last_week']:
    reports=load(name)
    print('\n====',name,len(reports),'====')
    for i,r in enumerate(reports,1):
        print('\n---REPORT',i,r.get('report_name'),r.get('report_template_name'),dt(r.get('createTime',0)),r.get('report_id'))
        for c in r.get('content',[]):
            val=c.get('value','') or ''
            print('FIELD:',c.get('key'),'LEN',len(val))
            print(val[:2500].replace('\r',''))
            if len(val)>2500: print('...TRUNC...')
