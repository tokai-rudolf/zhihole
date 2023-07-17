import json
import sqlite3
import threading
import time
from datetime import datetime

import requests
from flask import Flask, make_response, redirect

con = sqlite3.connect('accounts.db')

class LoginTask():
    def __init__(self, cookies, token, expire_at):
        self.cookies = cookies
        self.token = token
        self.expire_at = expire_at
        self.success = False


login_tasks:dict[str, LoginTask] = {}


def current_milli_time():
    return round(time.time() * 1000)


def refresh_tasks(con):
    global login_tasks
    for token, task in login_tasks.items():
        if task.success:
            if task.expire_at < current_milli_time():
                login_tasks -= token
            else:
                continue

        url = f"https://www.zhihu.com/api/v3/account/api/login/qrcode/{task.token}/scan_info"
        res = requests.get(url, cookies=task.cookies)
        task.cookies = res.cookies
        if 'status' not in res.json() or res.json()['status'] != 0:
            uid = res.json()['uid']
            print(f'Login success, uid: {uid}')
            requests.post('https://www.zhihu.com/api/account/prod/token/refresh', '', cookies=task.cookies)
            task.cookies = res.cookies
            # save cookies
            with open(f'cookies/{uid}.txt', 'w') as f:
                f.write(str(task.cookies.get_dict()))
            con.execute('INSERT INTO accounts VALUES (?, ?, ?)', (uid, json.dumps(task.cookies.get_dict()), current_milli_time()))
            print(json.dumps(task.cookies.get_dict()))
            con.commit()
            task.expire_at = current_milli_time() + 100*1000
            task.success = True
        elif task.expire_at < current_milli_time():
            login_tasks.remove(task)


def get_random_account():
    uid = con.execute('SELECT uid FROM accounts ORDER BY last_used LIMIT 1').fetchone()[0]
    cookies = con.execute('SELECT cookies FROM accounts WHERE uid=?', (uid,)).fetchone()[0]
    con.execute('UPDATE accounts SET last_used=? WHERE uid=?', (current_milli_time(), uid))
    return uid, json.loads(cookies)


def generate_payload(ans: str):
    return {
        "commercial_report_info": {
            "is_report": False
        },
        "commercial_zhitask_bind_info": None,
        "content": ans,
        "disclaimer_status": "open",
        "disclaimer_type": "fictional_creation",
        "is_report": False,
        "push_activity": False,
        "table_of_contents_enabled": False,
        "thank_inviter": "",
        "thank_inviter_status": "close",
        "reward_setting": {
            "can_reward": False,
            "tagline": ""
        }
    }


def answer(question: int, ans: str, cookies: dict):
    requests.post(f'https://www.zhihu.com/api/v4/answers/{question}', json=generate_payload(ans), cookies=cookies)


def upload_image(image: bytearray, cookies: dict):
    return requests.post('https://api.zhihu.com/images', json={
        "image_hash": "",
        "source": "answer",
    }, cookies=cookies).json()


def local_login_qr():
    cookies, token, expire_at = get_qr_token()
    print(f'QR Token: {token}')
    # print expire time, in a human read format, expire_at is unix timestamp
    print(f'Expire at: {datetime.fromtimestamp(expire_at)}')
    print('Please scan the QR code in 2 minutes')
    qr_url = f"https://www.zhihu.com/api/v3/account/api/login/qrcode/{token}/image"
    print(qr_url)

    while True:
        url = f"https://www.zhihu.com/api/v3/account/api/login/qrcode/{token}/scan_info"
        res = requests.get(url, cookies=cookies)
        cookies = res.cookies
        json: dict = res.json()
        if 'status' in json and json['status'] == 0:
            pass
        else:
            uid = json['uid']
            print(f'Login success, uid: {uid}')
            requests.post('https://www.zhihu.com/api/account/prod/token/refresh', '', cookies=cookies)
            cookies = res.cookies
            # save cookies
            with open(f'cookies/{uid}.txt', 'w') as f:
                f.write(str(cookies.get_dict()))
            return cookies


def get_qr_token():
    cookies = {}
    res = requests.get('https://www.zhihu.com/signin', cookies=cookies)
    cookies = res.cookies
    print(cookies)
    res = requests.post('https://www.zhihu.com/udid')
    cookies = res.cookies
    print(cookies)
    print(res.text)
    res = requests.post('https://www.zhihu.com/api/v3/account/api/login/qrcode', cookies=cookies, headers={
        "X-Requested-With": "fetch",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    })
    cookies = res.cookies
    print(cookies)
    print(res.request.headers)
    print(res.json())
    token = res.json()['token']
    expire_at = res.json()['expires_at']
    return cookies, token, expire_at


app = Flask(__name__)


@app.route('/')
def hello_world():
    return """<html><head><meta charset='utf-8'><title>知乎树洞 - 匿名化社区</title></head>
    <body><h1>知乎树洞 - 匿名化社区</h1>
    <p><a href="/share">共享您的账号用于树洞服务</a>或者<a href="/post">使用其他人的账号发布匿名回答</a></p>
    <p>树洞服务可以帮助您使用账号池内的账号隐藏真实身份和真实ip，虽然不能发布匿名回答，但是可以保证你的个人信息安全，没有人可以得知你的身份。暂不支持评论回复等功能。</p>
    <p>树洞服务是一个开源项目，你可以在<a href="">Github</a>上查看源代码，欢迎提交PR。</p>
    </body></html>"""


@app.get('/qr/<token>.png')
def qr(token):
    qr_url = f"https://www.zhihu.com/api/v3/account/api/login/qrcode/{token}/image"
    bytesarray = requests.get(qr_url).content
    res = make_response(bytesarray)
    res.content_type = 'image/png'
    return res


@app.get('/share')
def share():
    [cookies, token, expire_at] = get_qr_token()
    login_tasks[token] = LoginTask(cookies, token, expire_at)
    return redirect(f'/share/{token}')


@app.get('/share/<token>')
def share_with_token(token):
    if token not in login_tasks:
        return "Invalid token"
    if login_tasks[token].success:
        return "您已经成功登录，可以关闭此页面"
    return """
    <html><head><meta charset="utf-8"><title>知乎登录</title></head>
    <body><img src="/qr/""" + token + ".png" + """">
    <p>请扫描二维码登录</p>
    <p style="color:red">注意：您的账号在登录后可能会发布其他用户的、不受到控制的信息。继续扫码登录即表示您同意此风险。</p>
    
    <script>
    setTimeout(function() { window.location.reload(); }, 10000);
    </script>
    </body></html>
    """


@app.get('/post')
def post():
    return """<html><head><meta charset='utf-8'><title>知乎树洞 - 匿名化社区</title></head>
    <body><h1>知乎树洞 - 匿名化社区</h1>
    <p>树洞服务可以帮助您使用账号池内的账号隐藏真实身份和真实ip，虽然不能发布匿名回答，但是可以保证你的个人信息安全，没有人可以得知你的身份。暂不支持评论回复等功能。</p>
    <p>请输入问题id并点击继续，我们会自动使用账号池内的账号发布回答。</p>
    <p>由于我们不保存您的身份信息，回答一经发布，我们将无法删除。请谨慎使用。</p>
    <p>为了避免滥用和封号，我们的服务同一ip半小时只能发布一个回答，所有账号每小时只能发布100个回答。</p>
    <form method="none" name="form">
    <input type="text" name="qid" placeholder="问题id">
    </form>
    <button onclick="window.location.href='/post/'+document.form.qid.value">继续</button>
    </body></html>"""


def update_account(uid, cookies):
    con.execute('update accounts set cookies=? where uid=?', [json.dumps(cookies.get_dict()), uid])
    con.commit()


@app.get('/post/<qid>')
def post_with_qid(qid):
    [uid, cookies] = get_random_account()
    res = requests.get(f'https://www.zhihu.com/question/{qid}', cookies=cookies)
    update_account(uid, res.cookies)
    html = res.text
    print(html)
    str = "<meta itemProp=\"name\" content=\""
    index = html.index(str) + len(str)
    title = html[index:html.index("\"", index)]
    return """
    <html><head><meta charset="utf-8"><title>匿名回答问题 - 知乎树洞</title></head>
    <body><h1>匿名回答问题 - 知乎树洞</h1>
    <p>您正在回答的问题是：""" + title + """</p>
    <button onclick="uploadImage()">上传图片</button>
    <form method="post" action="/post/""" + qid + """">
    <input type="hidden" name="qid" value='""" + qid + """'>
    <textarea id="content" style="width: 100%; height: 300px"></textarea>
    <input type="submit" value="提交">
    </form>
    <p id="status"></p>
    <script>
    function uploadImage() {
        var formData = new FormData();
        formData.append("file", document.getElementById("file").files[0]);
        var xhr = new XMLHttpRequest();
        xhr.open("POST", "/upload");
        xhr.send(formData);
        xhr.onreadystatechange = function() {
            if (xhr.readyState == 4 && xhr.status == 200) {
                document.getElementById("content").value += "\\n![](" + xhr.responseText + ")";
            }
        }
    }
    </script>
    </body></html>"""


@app.get('/status')
def status():
    return {
        'available': sqlite3.connect('accounts.db').execute('select count(*) from accounts').fetchone()[0],
        'requests': 0,
        'login_tasks': len(login_tasks),
    }


if __name__ == '__main__':
    def do_refresh():
        fresher_con = sqlite3.connect("accounts.db")
        while True:
            refresh_tasks(fresher_con)
            print(login_tasks)
            time.sleep(10)

    threading.Thread(target=do_refresh).start()
    con.execute('CREATE TABLE IF NOT EXISTS accounts (uid TEXT, cookies TEXT, last_used INTEGER)')
    app.run(port=8080)
