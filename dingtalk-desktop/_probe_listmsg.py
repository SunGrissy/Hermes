"""探针：dump listMessage 返回的完整原始对象"""
import sys, os, json, time

sys.path.insert(0, os.path.dirname(__file__))
from daemon import FridaDaemon, BEACON_PORT
from lib.utils import js_escape

def probe(cid, count=2):
    d = FridaDaemon()
    if not d.attach():
        print("无法附加到钉钉"); return

    bid = d._find_jsapi_browser()
    if not bid:
        print("未找到 JSAPI browser"); return

    d._beacon.clear()
    cid_safe = js_escape(cid)

    # 拉消息但不做任何裁剪，直接 JSON.stringify 整个返回值
    probe_js = (
        f"(function(){{"
        "function post(l,d){{navigator.sendBeacon('http://127.0.0.1:" + str(BEACON_PORT) + "/b?l='+l,JSON.stringify(d));}}"
        "function promisify(fn,ctx){"
        "return function(){"
        "var a=Array.prototype.slice.call(arguments);"
        "return new Promise(function(ok,fail){"
        "a.push(function(r){ok(r);});"
        "fn.apply(ctx,a);"
        "});"
        "};"
        "}"
        "if(typeof dingtalk==='undefined'||!dingtalk.message||!dingtalk.message.listMessage){"
        "post('probe_err',{error:'no_api'});return;"
        "}"
        "var lm=promisify(dingtalk.message.listMessage,dingtalk.message);"
        f"lm('{cid_safe}',String(Number.MAX_SAFE_INTEGER),"
        f"{count},false,{{isFirstPull:true}})"
        ".then(function(msgs){"
        "if(!msgs||!msgs.length){post('probe_ok',{count:0});return;}"
        # 只取第一条，完整序列化
        "var first=msgs[0];"
        "var keys=Object.keys(first);"
        "post('probe_keys',{keys:keys});"
        # baseMessage 的完整 keys
        "if(first.baseMessage){"
        "post('probe_bm_keys',{keys:Object.keys(first.baseMessage)});"
        "}"
        # 尝试序列化整个对象（可能太大，截断）
        "try{"
        "var full=JSON.stringify(first,null,0);"
        # beacon 有 64KB 限制，分片
        "var chunk=4000;"
        "var parts=Math.ceil(full.length/chunk);"
        "post('probe_meta',{total_len:full.length,parts:parts});"
        "for(var i=0;i<parts&&i<16;i++){"
        "post('probe_p'+i,{d:full.substr(i*chunk,chunk)});"
        "}"
        "}catch(e){post('probe_err',{error:'stringify: '+String(e)});}"
        "}).catch(function(e){post('probe_err',{error:String(e)});});"
        "})()"
    )

    d._cef_script.exports_sync.exec_js(bid, probe_js)

    # 等待结果
    for _ in range(15):
        time.sleep(1)
        reports = d._beacon.get_reports()
        if 'probe_keys' in reports or 'probe_ok' in reports or 'probe_err' in reports:
            break

    reports = d._beacon.get_reports()
    
    if 'probe_err' in reports:
        print(f"错误: {reports['probe_err']}")
        return

    if 'probe_ok' in reports:
        print(f"空结果: {reports['probe_ok']}")
        return

    print(f"\n=== 顶层 keys ===")
    print(json.dumps(reports.get('probe_keys', {}), ensure_ascii=False, indent=2))

    print(f"\n=== baseMessage keys ===")
    print(json.dumps(reports.get('probe_bm_keys', {}), ensure_ascii=False, indent=2))

    meta = reports.get('probe_meta', {})
    print(f"\n=== 完整对象大小: {meta.get('total_len', '?')} bytes, {meta.get('parts', '?')} parts ===")

    # 拼接分片
    full = ''
    for i in range(16):
        part = reports.get(f'probe_p{i}')
        if part and isinstance(part, dict):
            full += part.get('d', '')

    if full:
        # 保存到文件
        out_path = os.path.join(os.path.dirname(__file__), '_probe_listmsg_result.json')
        try:
            obj = json.loads(full)
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(obj, f, ensure_ascii=False, indent=2)
            print(f"\n完整对象已保存: {out_path}")
        except json.JSONDecodeError:
            with open(out_path, 'w', encoding='utf-8') as f:
                f.write(full)
            print(f"\n原始文本已保存（JSON 不完整）: {out_path}")

    d.detach()

if __name__ == '__main__':
    cid = sys.argv[1] if len(sys.argv) > 1 else ''
    if not cid:
        # 从 contacts.json 取第一个群聊
        contacts_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'dingtalk', 'contacts.json')
        try:
            with open(contacts_path, encoding='utf-8') as f:
                contacts = json.load(f)
            for c in contacts:
                if c.get('type') == 'group':
                    cid = c['cid']
                    print(f"使用群聊 CID: {cid} ({c.get('name', '未知')})")
                    break
        except Exception:
            pass
    if not cid:
        print("用法: python _probe_listmsg.py <CID>")
        sys.exit(1)
    
    cnt = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    probe(cid, cnt)
