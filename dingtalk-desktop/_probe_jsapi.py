"""探测 JSAPI dingtalk 对象的可用方法，特别是 conversation 相关"""
import sys, os, time, json
sys.path.insert(0, os.path.dirname(__file__))
from daemon import FridaDaemon, BEACON_PORT

d = FridaDaemon()
if not d.attach():
    print("无法 attach"); sys.exit(1)

bid = d._find_jsapi_browser()
if not bid:
    print("未找到 JSAPI browser"); sys.exit(1)

print(f"browser ID: {bid}")

d._beacon.clear()
probe_js = (
    "(function(){"
    "var P=" + str(BEACON_PORT) + ";"
    "function post(l,d){var b=JSON.stringify(d);"
    "fetch('http://127.0.0.1:'+P+'/b?l='+encodeURIComponent(l),"
    "{method:'POST',body:b,mode:'no-cors'}).catch(function(){});}"
    ""
    "if(typeof dingtalk==='undefined'){post('probe',{error:'no dingtalk'});return;}"
    ""
    "var result={};"
    "var topKeys=Object.keys(dingtalk);"
    "result.topKeys=topKeys;"
    ""
    "for(var i=0;i<topKeys.length;i++){"
    "var k=topKeys[i];"
    "try{"
    "var v=dingtalk[k];"
    "if(v&&typeof v==='object'){"
    "result[k]=Object.keys(v);"
    "}"
    "}catch(e){}"
    "}"
    ""
    "post('probe',result);"
    "})()"
)

d._cef_script.exports_sync.exec_js(bid, probe_js)

for _ in range(10):
    time.sleep(0.5)
    reports = d._beacon.get_reports()
    if 'probe' in reports:
        print(json.dumps(reports['probe'], indent=2, ensure_ascii=False))
        break
else:
    print("超时，未收到 probe 响应")

d._cleanup()
