# dareda 一键安装(Windows PowerShell)。Linux / macOS 用 install.sh。
#
# 把能自动的都自动掉:建虚拟环境、装 Python 包、克隆并编译麻将引擎、下模型权重。
# 可重复运行 —— 每步先查"是不是已经做好了",做好就跳过,所以中途出错修完再跑一遍
# 就行,不会重新编译或重下权重。
#
# 脚本兜不住、需要你先装好的:
#   - Python 3.11+   (https://www.python.org)
#   - Rust 工具链    (编译引擎要用 cargo;没有会提示你去 https://rustup.rs 装)
# 抓牌谱是浏览器里的人工操作,装完看 README。
#
# 跑法:在项目目录里打开 PowerShell,执行   .\install.ps1
# 若报"无法加载脚本,禁止运行",先执行:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

# 用 Continue 而非 Stop:cargo build / git clone / curl 都会往 stderr 写进度,
# 在 PowerShell 5.1 + Stop 下这些正常输出会被当成 NativeCommandError 直接中断脚本。
# 所以改为手动检查每个原生命令的退出码(NeedExit)。
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

function Say  ($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function OK   ($m) { Write-Host "  + $m" -ForegroundColor Green }
function Skip ($m) { Write-Host "  . $m(已就绪,跳过)" -ForegroundColor DarkGray }
function Die  ($m) { Write-Host "  x $m" -ForegroundColor Red; exit 1 }
function NeedExit ($m) { if ($LASTEXITCODE -ne 0) { Die $m } }

# python 导入探测:成功返回 $true。stderr/stdout 全吞掉,失败时不刷 traceback。
function Test-Import ($mod) {
  & $venvPy -c "import $mod" 2>$null 1>$null
  return ($LASTEXITCODE -eq 0)
}

$WeightsUrl = "https://huggingface.co/VoidShine/mortal-298k/resolve/main/mortal_298k.pth"

# ---- Windows 特有:路径太长会让 torch 装到一半失败,先拦一道 ----
if ($PSScriptRoot.Length -gt 90) {
  Write-Host "  ! 当前项目路径较长($($PSScriptRoot.Length) 字符):$PSScriptRoot" -ForegroundColor Yellow
  Write-Host "    Windows 有 260 字符上限,torch 的包目录很深,路径一长装 torch 会报" -ForegroundColor Yellow
  Write-Host "    'WinError 206 文件名太长'。强烈建议把项目挪到短路径(如 C:\dev\dareda)再装。" -ForegroundColor Yellow
  $ans = Read-Host "    仍要继续吗?(y/N)"
  if ($ans -ne "y") { Die "已中止。请把项目移到短路径后重跑。" }
}

# ---- 前置检查 ----
Say "检查前置工具"
$py = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $py) { Die "找不到 Python。请装 Python 3.11+ 并勾选 Add to PATH。" }
$verOK = & python -c "import sys; print(1 if sys.version_info>=(3,11) else 0)"
if ($verOK.Trim() -ne "1") { Die "Python 版本太低,需要 3.11+" }
OK ("Python: " + (& python --version))
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
  Die "找不到 cargo(编译引擎要用)。去 https://rustup.rs 装好 Rust 再重跑本脚本。"
}
OK ("cargo: " + (& cargo --version))

# ---- 1. 虚拟环境 ----
Say "虚拟环境 .venv"
$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (Test-Path $venvPy) { Skip ".venv" }
else { & python -m venv .venv; NeedExit "创建 .venv 失败。"; OK "已建 .venv" }

# ---- 2. 装本项目 ----
Say "安装 dareda 及依赖"
if (Test-Import "dareda") { Skip "dareda" }
else {
  & $venvPy -m pip install -q --upgrade pip; NeedExit "升级 pip 失败。"
  & $venvPy -m pip install -q -e .;           NeedExit "dareda 安装失败。"
  OK "已装 dareda"
}

# ---- 3. PyTorch(CPU 版;推理够用,CUDA 只是更快,想要的自己重装)----
Say "PyTorch(CPU)+ numpy"
if (Test-Import "torch") { Skip "torch / numpy" }
else {
  & $venvPy -m pip install -q numpy torch --index-url https://download.pytorch.org/whl/cpu
  NeedExit "torch 装失败。多半是路径过长,把项目挪到短目录重来;详见 README「遇到问题」。"
  OK "已装 torch(CPU)"
}

# ---- 4. 引擎:克隆 + 打补丁 ----
Say "麻将引擎 libriichi(上游 Mortal + 本项目补丁)"
if (Test-Path "vendor\Mortal\.git") { Skip "已克隆 Mortal" }
else {
  & git clone --depth 1 https://github.com/Equim-chan/Mortal.git vendor/Mortal
  NeedExit "克隆 Mortal 失败。"
  OK "已克隆 Mortal"
}
if (Test-Path "vendor\Mortal\libriichi\src\arena\replay.rs") { Skip "补丁已打" }
else {
  Copy-Item patches\replay.rs vendor\Mortal\libriichi\src\arena\replay.rs
  & git -C vendor/Mortal apply ../../patches/arena-mod.patch
  NeedExit "补丁应用失败(可能上游改了 arena/mod.rs)。手动加那四行,见 README「遇到问题」。"
  OK "已打补丁"
}

# ---- 5. 编译 + 摆放产物 ----
Say "编译引擎(首次约 1–2 分钟)"
if (Test-Path "libriichi.pyd") { Skip "libriichi.pyd 已存在" }
else {
  Push-Location vendor\Mortal\libriichi
  & cargo build --release
  $rc = $LASTEXITCODE
  Pop-Location
  if ($rc -ne 0) { Die "编译失败。" }
  Copy-Item vendor\Mortal\target\release\riichi.dll libriichi.pyd
  OK "已编译并放好 libriichi.pyd"
}

# ---- 6. 模型权重(约 130 MB;本项目不分发,从第三方下)----
Say "模型权重"
$w = "models\mortal_298k.pth"
if ((Test-Path $w) -and ((Get-Item $w).Length -gt 100MB)) { Skip "权重已下载" }
else {
  if (-not (Test-Path models)) { New-Item -ItemType Directory models | Out-Null }
  Write-Host "    下载中(130 MB)..."
  & curl.exe -fL --progress-bar -o $w $WeightsUrl
  NeedExit "权重下载失败。手动下 $WeightsUrl 放到 $w。"
  OK "已下载权重"
}

# ---- 自检 ----
Say "自检"
$env:PYTHONPATH = "src;vendor/Mortal/mortal;."
& $venvPy -c "import libriichi; assert libriichi.__profile__=='release'"
NeedExit "libriichi 导入失败。"
OK "引擎可导入"

Write-Host ""
Write-Host "========================================================================" -ForegroundColor Green
Write-Host " 装好了。以后每次用之前,先激活环境并设好 PYTHONPATH:"
Write-Host ""
Write-Host "   .venv\Scripts\activate"
Write-Host '   $env:PYTHONPATH = "src;vendor/Mortal/mortal;."'
Write-Host ""
Write-Host " 然后:"
Write-Host "   1) 按 README「取牌谱」用浏览器导出一份牌谱(需装 Tampermonkey)"
Write-Host "   2) dareda decode-capture --capture majsoul-ws-*.json --out record.json"
Write-Host "   3) dareda verify   --record record.json      # 必须全过"
Write-Host "   4) dareda self-luck --record record.json --hero <你的座次 0-3> --trials 30"
Write-Host "========================================================================" -ForegroundColor Green
