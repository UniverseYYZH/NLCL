# NLMCL 打包与 GitHub 发布傻瓜教程

> 这份文档写给不熟悉 Git、GitHub、PyInstaller 的人。
> 你只需要按顺序做，不需要理解每条命令。
>
> **我（AI）可以直接在当前电脑上执行本地打包，但无法登录你的 GitHub 账号，也不能替你点 GitHub 网页。**
> 因此本地 exe 我已经帮你打好；GitHub 上传需要你按本教程操作。

---

## 一、最终会得到什么

打包成功后：

```text
D:\Users\zyh\Desktop\NLMCL\
├─ dist\
│  └─ NLMCL.exe          ← 最终单文件程序，发给别人只需要这个
├─ build\               ← 打包临时目录，可删除
├─ 一键打包.bat          ← 双击即可重新打包
├─ build.bat            ← 真正执行打包的脚本
├─ assets\
│  ├─ app.ico           ← exe 图标
│  ├─ app.png           ← 图标源图
│  └─ steve.png         ← 默认史蒂夫皮肤，已打进 exe
└─ ...
```

`NLMCL.exe` 是 **Windows 单文件 exe**：

- 双击运行，不弹黑色控制台；
- 已嵌入 `assets` 资源；
- 图标为 `assets/app.ico`；
- 游戏版本、Forge/Fabric、Java 运行时仍然是**运行后联网下载**；
- 不包含 `.minecraft` 游戏文件，也不包含 Java。

本次已经实际完成一次打包并启动验证：

- 文件：`dist\NLMCL.exe`
- 大小约 90 MB
- 已用离线账号验证默认史蒂夫头像从 exe 内资源读取成功
- `dist\SHA256.txt` 保存了校验值，可以一起上传到 Release

---

## 二、打包前准备

### 1. 安装 Python 3.11 或更高版本（64 位）

1. 打开 <https://www.python.org/downloads/windows/>
2. 下载 **Windows installer (64-bit)**
3. 双击安装
4. 安装第一页必须勾选：

```text
[√] Add python.exe to PATH
```

5. 点 `Install Now`
6. 安装完成后，按 `Win + R`，输入 `cmd`，回车，输入：

```bat
python --version
```

看到类似 `Python 3.13.x` 就成功。

### 2. 项目放到英文路径（推荐）

当前路径：

```text
D:\Users\zyh\Desktop\NLMCL
```

可以使用，但**不要**放到 `C:\Program Files` 这类需要管理员权限的目录。

### 3. 确认项目里有这些文件

```text
main.py
requirements.txt
requirements-build.txt
一键打包.bat
build.bat
assets\app.ico
assets\steve.png
```

缺一个都可能打包失败。

---

## 三、一键打包（最简单）

### 第 1 步：打开项目文件夹

在文件资源管理器打开：

```text
D:\Users\zyh\Desktop\NLMCL
```

### 第 2 步：双击

```text
一键打包.bat
```

### 第 3 步：等

会弹出一个黑色窗口，依次显示：

```text
[1/6] ...
[2/6] ...
[3/6] ...
[4/6] ...
[5/6] ...
[6/6] Packaging with PyInstaller...
```

**不要关窗口。** 第一次打包通常需要 2～10 分钟，取决于网络和电脑。

### 第 4 步：看到 BUILD SUCCESS

窗口出现：

```text
BUILD SUCCESS
EXE: D:\Users\zyh\Desktop\NLMCL\dist\NLMCL.exe
```

说明成功。

### 第 5 步：测试 exe

打开：

```text
D:\Users\zyh\Desktop\NLMCL\dist
```

双击 `NLMCL.exe`。

第一次启动会比平时慢几秒，这是单文件 exe 的正常现象。

---

## 四、脚本到底做了什么

`一键打包.bat` 只是调用 `build.bat`。`build.bat` 会：

1. 检查 `.venv`
2. 如果没有 `.venv`，自动创建
3. 安装 `requirements.txt`
4. 安装 `requirements-build.txt`（PyInstaller + flet-cli）
5. 删除旧的 `build`、`dist`
6. 执行：

```bat
.venv\Scripts\flet.exe pack main.py ^
  --name NLMCL ^
  --icon assets\app.ico ^
  --add-data "assets;assets" ^
  --hidden-import PIL ^
  --hidden-import requests ^
  --hidden-import urllib3 ^
  --hidden-import segno ^
  --hidden-import minecraft_launcher_lib ^
  -y
```

`flet pack` 底层就是 PyInstaller，并且会额外把 Flet 的 Windows 桌面运行器一起打包，避免出现“exe 打开白屏”。

它默认使用：

```text
--onefile
--noconsole
```

因此最终只有一个 exe，且没有黑框控制台。

### 为什么不是直接手写 `pyinstaller main.py`？

Flet 桌面程序除了 Python 代码，还依赖 Flet 自己的桌面运行器。
`flet pack` 会自动处理这些依赖；直接 `pyinstaller main.py` 很容易出现：

- 打开后白屏
- 闪退
- 找不到 `flet.exe`
- 找不到 `assets\steve.png`

所以本项目使用 `flet pack`（仍然是 PyInstaller）。

---

## 五、资源在哪里

### 已嵌入 exe 的

```text
assets\steve.png
assets\app.ico
```

打包参数：

```text
--add-data "assets;assets"
```

程序运行时从 PyInstaller 的解包目录读取，不会因为移动 exe 而丢失。

### 不嵌入 exe 的

- Minecraft 游戏本体
- Java 运行时
- 下载的 Forge/Fabric 安装器
- 用户上传的皮肤
- `accounts.json`
- `app_settings.json`
- `ui_theme.json`

这些都在运行后生成或下载，默认位置：

```text
%APPDATA%\NLMCL
```

### 游戏目录

默认：

```text
%APPDATA%\.minecraft
```

可以在设置页修改下载目录，程序会记住。

---

## 六、修改 exe 图标

图标文件：

```text
assets\app.ico
```

替换它即可。要求：

- `.ico` 格式
- 建议包含 16、24、32、48、64、128、256 尺寸
- 文件名保持 `app.ico`

然后重新双击 `一键打包.bat`。

如果资源管理器还显示旧图标：

1. 关闭所有 NLMCL 窗口
2. `Win + R` 输入 `ie4uinit.exe -show`
3. 或重启资源管理器
4. 或把 exe 复制到另一个目录看

---

## 七、把代码上传到 GitHub

> 推荐用 **GitHub Desktop**，不用记命令。
> 如果你愿意用命令，后面也给了完整的 Git 命令版。

### 方案 A：GitHub Desktop（推荐新手）

#### 1. 注册 GitHub

打开 <https://github.com>，点 `Sign up`，按提示注册并验证邮箱。

#### 2. 安装 GitHub Desktop

打开 <https://desktop.github.com/>，下载安装。

安装后打开，点：

```text
Sign in to GitHub.com
```

浏览器会弹出登录，按提示授权。

#### 3. 在 GitHub 网页新建仓库

1. 打开 <https://github.com/new>
2. `Repository name` 填：

```text
NLMCL
```

3. 选择 `Public`（公开）或 `Private`（私有）
4. **不要勾选** `Add a README file`
5. 点 `Create repository`
6. 页面会显示仓库地址，例如：

```text
https://github.com/你的用户名/NLMCL.git
```

先不要关页面。

#### 4. 在 GitHub Desktop 添加本地项目

1. 打开 GitHub Desktop
2. 左上角 `File` → `Add local repository...`
3. `Local path` 选择：

```text
D:\Users\zyh\Desktop\NLMCL
```

4. 点 `Add repository`
5. 如果提示 “This directory does not appear to be a Git repository”，点：

```text
create a repository
```

6. 点 `Create repository`

#### 5. 第一次提交

左下角：

1. `Summary` 填：

```text
feat: NLMCL launcher v1.0
```

2. 点 `Commit to main`

#### 6. 发布到 GitHub

点顶部：

```text
Publish repository
```

- `Name` 保持 `NLMCL`
- 不要勾选 `Keep this code private`（如果要公开）
- 点 `Publish repository`

上传完成后，网页仓库就能看到代码。

#### 7. 后续修改再上传

每次改完代码：

1. 打开 GitHub Desktop
2. 左下角 `Summary` 写一句说明
3. 点 `Commit to main`
4. 点右上角 `Push origin`

---

### 方案 B：命令行 Git

如果你已经安装 Git，按下面做。

#### 1. 检查 Git

打开 PowerShell，输入：

```powershell
git --version
```

能看到版本号才继续。

如果提示“无法将 git 项识别为...”，先安装：

<https://git-scm.com/download/win>

安装时一路 `Next`，最后 `Install`。

装完**关闭并重新打开** PowerShell。

#### 2. 进入项目目录

```powershell
cd "D:\Users\zyh\Desktop\NLMCL"
```

#### 3. 第一次使用 Git，设置名字和邮箱

```powershell
git config --global user.name "你的GitHub用户名"
git config --global user.email "你的GitHub邮箱"
```

例如：

```powershell
git config --global user.name "zhangsan"
git config --global user.email "zhangsan@example.com"
```

#### 4. 初始化仓库

如果项目还不是 Git 仓库：

```powershell
git init
git branch -M main
```

#### 5. 查看将要上传的文件

```powershell
git status
```

确认没有把 `.venv`、`dist`、`build` 加进去。
本项目 `.gitignore` 已经排除这些目录。

#### 6. 添加并提交

```powershell
git add .
git commit -m "feat: NLMCL launcher v1.0"
```

#### 7. 连接 GitHub 仓库

把下面地址换成你自己的：

```powershell
git remote add origin https://github.com/你的用户名/NLMCL.git
```

如果提示 `remote origin already exists`，改用：

```powershell
git remote set-url origin https://github.com/你的用户名/NLMCL.git
```

#### 8. 推送

```powershell
git push -u origin main
```

第一次推送会弹出浏览器登录 GitHub。
登录并授权后，等待上传完成。

#### 9. 以后更新

```powershell
git add .
git commit -m "update: 修复一些问题"
git push
```

---

## 八、在 GitHub 网页发布 Release 并上传 exe

代码上传成功后再做这一步。

### 1. 打开仓库

浏览器打开：

```text
https://github.com/你的用户名/NLMCL
```

### 2. 进入 Releases

在仓库首页右侧，找到：

```text
Releases
```

点它；如果没有，直接打开：

```text
https://github.com/你的用户名/NLMCL/releases
```

### 3. 新建 Release

点：

```text
Draft a new release
```

### 4. 填写

`Choose a tag`：

```text
v1.0.0
```

然后点：

```text
Create new tag: v1.0.0 on publish
```

`Release title`：

```text
NLMCL v1.0.0
```

`Describe this release` 可以复制：

```markdown
## NLMCL v1.0.0

轻量化 Minecraft Java 启动器。

### 功能
- 本地版本扫描
- 原版 / Fabric / Forge 下载
- Java 运行时管理
- 多实例启动与实时日志
- 局域网联机与房间扫描
- 实例快照
- 日志标签
- 皮肤管理
- 三套主题
- 全局等比缩放布局

### 使用方法
1. 下载 `NLMCL.exe`
2. 放到任意文件夹
3. 双击运行
4. 首次启动会检查并在线下载所需 Java / 游戏文件
```

### 5. 上传 exe

在页面下方找到：

```text
Attach binaries by dropping them here or selecting them.
```

点击：

```text
selecting them
```

选择：

```text
D:\Users\zyh\Desktop\NLMCL\dist\NLMCL.exe
```

等待上传完成。

可选：同时上传：

```text
D:\Users\zyh\Desktop\NLMCL\dist\SHA256.txt
```

它是 exe 的 SHA256 校验值，用户下载后可以核对文件是否完整。

### 6. 发布

点绿色按钮：

```text
Publish release
```

### 7. 验证

发布成功后打开：

```text
https://github.com/你的用户名/NLMCL/releases
```

应该能看到：

```text
NLMCL v1.0.0
NLMCL.exe
```

点一下 `NLMCL.exe`，确认可以下载。

---

## 九、常见错误与解决办法

### 1. 双击 bat 一闪而过

原因：脚本报错后窗口关闭。

解决：

1. 点开始菜单，搜索 `cmd`
2. 打开命令提示符
3. 输入：

```bat
cd /d "D:\Users\zyh\Desktop\NLMCL"
build.bat
```

这样错误会留在窗口里。

### 2. 提示 `Python launcher "py" not found`

没装 Python，或安装时没勾选 PATH。

解决：

1. 重新安装 Python
2. 勾选 `Add python.exe to PATH`
3. 关掉所有命令行，重新双击 bat

### 3. 提示 `flet` 不是内部或外部命令

`flet-cli` 没装好。

解决：

```bat
.venv\Scripts\python.exe -m pip install -r requirements-build.txt
```

然后重新打包。

### 4. `pip install` 网络超时

国内网络访问 PyPI 慢。

在命令行执行一次镜像安装：

```bat
.venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
.venv\Scripts\python.exe -m pip install -r requirements-build.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

然后重新打包。

### 5. 打包成功，但打开白屏

按顺序检查：

1. 等待 10 秒，单文件第一次启动较慢。
2. 确认 `assets\steve.png` 存在。
3. 确认 `build.bat` 中有：

```bat
--add-data "assets;assets"
```

4. 确认没有把 exe 和 assets 分开移动（资源已嵌入，不需要 assets 文件夹）。
5. 用源码运行，确认程序本身正常：

```powershell
.\.venv\Scripts\python.exe main.py
```

6. 如果源码正常、exe 白屏，重新打包；仍失败时做调试版：

```bat
.venv\Scripts\flet.exe pack main.py --name NLMCL-debug --icon assets\app.ico --add-data "assets;assets" --debug-console 1 -y
```

运行 `dist\NLMCL-debug.exe`，把黑色窗口里的报错发出来。

### 6. 提示 “Could not create temporary directory!”

单文件 exe 启动时会先解压到 `%TEMP%`。这个目录不可写时就会报错。

按顺序处理：

1. 确认下面目录存在：

```text
C:\Users\你的用户名\AppData\Local\Temp
```

2. 打开该目录，删除旧的 `_MEI*` 文件夹
3. 确认 C 盘剩余空间充足
4. 把 exe 放到桌面或普通文件夹运行，不要放在只读目录
5. 把 exe 所在目录加入杀毒排除项
6. 如果仍然不行，用源码运行，或改为目录版打包：

```bat
.venv\Scripts\flet.exe pack main.py --name NLMCL --icon assets\app.ico --add-data "assets;assets" -D -y
```

### 7. 提示找不到 `assets/steve.png`

原因：打包时没有带 assets。

解决：

```bat
--add-data "assets;assets"
```

注意 Windows 下是**分号** `;`，不是冒号。

### 8. 杀毒软件报毒 / Windows Defender 删除 exe

PyInstaller 单文件 exe 被误报很常见，不代表有病毒。

解决：

1. Windows 安全中心 → 病毒和威胁防护 → 管理设置 → 排除项
2. 添加排除项：

```text
D:\Users\zyh\Desktop\NLMCL\dist
```

3. 重新打包
4. 把 exe 上传到 <https://www.virustotal.com> 查看，若只有少数引擎误报，通常是 PyInstaller 特征
5. 正式发布建议购买代码签名证书；个人项目可以先在 README 说明“未签名，可能误报”

**不要**为了绕过杀毒去关闭整个实时保护，只加项目目录排除即可。

### 9. Windows SmartScreen 提示“已保护你的电脑”

原因：exe 没有代码签名。

解决：

1. 点 `更多信息`
2. 点 `仍要运行`
3. 这是正常现象，不是程序错误

### 10. `ModuleNotFoundError: No module named ...`

缺依赖。

解决：

```bat
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

然后把缺失模块名加到 `build.bat` 的 `--hidden-import` 后面重新打包。

### 11. `flet pack` 报 PyInstaller 错误

先清理后重试：

```bat
rmdir /s /q build
rmdir /s /q dist
del /q NLMCL.spec
```

然后重新双击 `一键打包.bat`。

### 12. exe 太大

Flet 桌面运行器本身较大，单文件 100MB 左右是正常的。

如果希望启动更快，可以把 `build.bat` 里的打包方式改为目录版：

```bat
"%FLET%" pack main.py ... -D
```

但这样发布时需要把整个 `dist\NLMCL` 文件夹压缩成 zip，不是单文件。

本项目默认坚持单文件 exe。

### 13. `git` 不是内部或外部命令

没安装 Git。

解决：

1. 安装 <https://git-scm.com/download/win>
2. 安装后关闭所有终端
3. 重新打开 PowerShell
4. 输入 `git --version` 验证

### 14. GitHub 推送提示 `remote origin already exists`

说明已经配置过远程地址。

执行：

```powershell
git remote set-url origin https://github.com/你的用户名/NLMCL.git
git push -u origin main
```

### 15. GitHub 推送提示 `rejected ... non-fast-forward`

远程仓库已有新提交。

先拉取：

```powershell
git pull origin main --allow-unrelated-histories
```

如果出现冲突，按提示修改文件后：

```powershell
git add .
git commit -m "merge"
git push origin main
```

### 16. GitHub 登录失败 / 403

- 确认浏览器已登录正确 GitHub 账号
- 确认仓库地址是你的用户名
- 确认对该仓库有写权限
- 如果开了双重验证，使用浏览器授权，不要随便填账号密码
- 也可以使用 Personal Access Token 作为密码

### 17. `git push` 卡住或 SSL 错误

先检查网络/代理，然后重试：

```powershell
git push -u origin main
```

公司网络/代理可能拦截 GitHub；换网络或配置代理。

### 18. 不小心把 dist/build 提交了

本项目 `.gitignore` 已排除：

```text
build/
dist/
*.spec
*.exe
```

如果已经提交，执行：

```powershell
git rm -r --cached build dist
git commit -m "chore: remove build output"
git push
```

### 19. Release 上传 exe 很慢

exe 通常几十到一百多 MB，浏览器上传需要时间。

- 不要关闭页面
- 等进度条完成
- 网络差时换个时间
- GitHub Release 单个附件上限 2GB，正常不会超

### 20. 用户下载 exe 后打不开

检查：

- 是否 Windows 10/11 64 位
- 是否被杀毒隔离
- 是否下载完整（文件大小和 Release 页面显示一致）
- 是否解压工具把 exe 损坏

### 21. 下载游戏/Java 失败

这不是打包问题。

- 游戏和 Java 是运行后在线下载
- 检查网络
- 在设置页修改下载目录
- 查看启动器日志和 Java 预检提示

---

## 十、发布前检查清单

- [ ] 双击 `一键打包.bat` 成功
- [ ] `dist\NLMCL.exe` 存在
- [ ] 双击 exe 能打开
- [ ] 版本列表能扫描
- [ ] 账号头像正常
- [ ] 主题切换正常
- [ ] 设置页能打开
- [ ] 杀毒软件没有删除 exe
- [ ] README 已更新
- [ ] 代码已 push 到 GitHub main
- [ ] Release 已上传 `NLMCL.exe`
- [ ] 下载链接可以打开

---

## 十一、我无法替你做的部分

我可以：

- 修改代码
- 创建打包脚本
- 在本机执行 PyInstaller
- 生成 `dist\NLMCL.exe`
- 写 README 和教程

我不能：

- 登录你的 GitHub 账号
- 替你点 GitHub 网页按钮
- 替你输入 GitHub 密码/验证码
- 替你决定仓库公开还是私有

所以最后只有两步需要你亲手做：

1. 按第七节把代码推到 GitHub
2. 按第八节在网页上传 `NLMCL.exe`
