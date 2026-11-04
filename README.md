<img src="assets/hero.svg" width="100%" alt="希冀作业雷达">

<p>
  <img src="https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Playwright-Chromium-2EAD33?logo=playwright&logoColor=white" alt="Playwright">
  <img src="https://img.shields.io/badge/%E5%B9%B3%E5%8F%B0-CourseGrading%208.2.3-2563EB" alt="CourseGrading">
  <img src="https://img.shields.io/badge/License-MIT-B45309" alt="MIT">
</p>

**每天中午 11:55，把「哪门课还剩什么作业、交了几题、还有多久截止」整理成一封邮件，发到你邮箱。**

作业散在每门课里，平台只会告诉你「有这个作业」，不会告诉你「你还差三题没交」。这个脚本会点进每一个作业，逐题数一遍。

---

## 效果

<img src="assets/mail.svg" width="100%" alt="邮件效果">

没做完的排在最上面，带倒计时；做完的收在下面，只列名字。扫一眼就知道今天必须先做哪个。

---

## 它怎么做的

<img src="assets/flow.svg" width="100%" alt="三个动作">

### 为什么不用普通请求直接登录

希冀的登录口有图形验证码，密码还过了一层 AES 加密，硬撞几次就会锁号。所以这里绕开它，走学校自己的 CAS 统一认证——用一个看不见的浏览器，像人一样把学号和密码填进去、点登录，拿到 `JSESSIONID` 之后，后面所有抓取都换回普通请求，快且稳。

这一步不是耍花招，只是因为平台的风控本来就是防「用脚本撞密码」的。你登的是自己的账号，看的是自己的作业，一天跑一次。

---

## 安装

```bash
git clone https://github.com/xm2284/cstlab-assignment-radar.git
cd cstlab-assignment-radar

pip install -r requirements.txt
playwright install chromium
```

国内打不开 GitHub 用镜像：`https://gitee.com/xm2284/cstlab-assignment-radar.git`

> 第一次必须跑 `playwright install chromium`，否则会报找不到浏览器。这一步要下载约 150MB，慢的话挂个镜像。

---

## 配置

```bash
cp config.example.json config.json
```

```json
{
  "stid": "你的学号",
  "pwd": "你的校园密码",
  "email": {
    "smtp_server": "smtp.qq.com",
    "smtp_port": 465,
    "sender": "你的QQ号@qq.com",
    "auth_code": "QQ邮箱SMTP授权码",
    "receiver": "你的QQ号@qq.com"
  }
}
```

`config.json` 已在 `.gitignore` 里，不会被提交。**别把它传到任何公开仓库。**

QQ 邮箱授权码：邮箱设置 → 账号 → 开启 POP3/SMTP → 按提示验证 → 拿到 16 位授权码。

---

## 跑起来

```bash
python xiji_assignment_radar.py
```

正常会看到三段输出：

```
[1/3] 启动无头浏览器，走校园统一认证…
  ✓ 统一认证通过
[2/3] 逐门扫描在期作业…
  · 操作系统：3 项
  · 算法设计与分析：2 项
[3/3] 生成并投递邮件…
  ✓ 已发送：待做 3 项，已完成 5 项
```

**挂定时任务**

Windows（每天 11:55）：

```powershell
schtasks /create /tn "作业雷达" /tr "pythonw.exe D:\radar\xiji_assignment_radar.py" /sc daily /st 11:55
```

Linux / macOS：

```bash
0 11 * * * /usr/bin/python3 /home/you/cstlab-assignment-radar/xiji_assignment_radar.py >> /tmp/xiji.log 2>&1
```

---

## 遇到问题

**① 第一次跑就报证书错误**

校园站的证书链经常不完整。脚本里已经带了 `--ignore-certificate-errors`，如果你改成自己的启动参数，记得把这个也带上。这是这个项目第一次跑失败的真正原因。

**② `登录异常，没拿到 JSESSIONID`**

三种可能：密码改了；账号被风控临时限制（等一会儿再试）；学校换了登录页结构，输入框的 `placeholder` 变了，改 `page.locator(...)` 那两行即可。

**③ 扫出来 0 项**

平台改版，`div.main-zy` / `p.main-title` 这类选择器失效了。把作业列表页的 HTML 存一份，跟 AI 说「这是列表页，要作业名、截止时间、倒计时、链接」，让它改 `parse_course_assigns` 就行。

**④ 状态判断不准**

详情页的提交状态文案各地不同。`check_assignment_detail_status` 里认的是「已提交 / 通过 / 已评阅」，如果你们平台用的是别的词（比如「已批改」），加到列表里。

**⑤ 会不会锁号**

一天一次，走的是正常登录流程，和人手动登一次没区别。但别把定时任务设成每隔几分钟跑一次。

---

## 它适合谁

- 一学期七八门课，作业散在平台上，靠脑子记截止时间的人
- 想知道「这门课我还差几题」但不想一道道点开的人
- 想拿这个当个例子，看看「用大白话让 AI 写工具」能到什么程度的人

---

## 使用边界

- 登录的是**你自己的账号**，读取的是**你自己的作业数据**；
- 每天运行一次，不并发、不爬取他人信息、不做任何写操作（不提交、不改答案）；
- 仅用于个人学习与自我管理，请遵守学校平台的使用条款；
- 密码保存在本地 `config.json`，请自行妥善保管。

---

## License

[MIT](LICENSE) © 2026 何明（xm2284）
