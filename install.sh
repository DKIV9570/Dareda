#!/usr/bin/env bash
# dareda 一键安装(Linux / macOS)。Windows 用 install.ps1。
#
# 把能自动的都自动掉:建虚拟环境、装 Python 包、克隆并编译麻将引擎、下模型权重。
# 可重复运行 —— 每步先查"是不是已经做好了",做好就跳过,所以中途出错修完再跑一遍
# 就行,不会重新编译或重下权重。
#
# 脚本兜不住、需要你先装好的:
#   - Python 3.11+
#   - Rust 工具链(编译引擎要用 cargo;没有会提示你去 https://rustup.rs 装)
# 抓牌谱是浏览器里的人工操作,装完看 README。

set -euo pipefail
cd "$(dirname "$0")"

say()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m  ✓\033[0m %s\n' "$*"; }
skip() { printf '\033[2m  · %s(已就绪,跳过)\033[0m\n' "$*"; }
die()  { printf '\033[1;31m  ✗ %s\033[0m\n' "$*" >&2; exit 1; }

WEIGHTS_URL="https://huggingface.co/VoidShine/mortal-298k/resolve/main/mortal_298k.pth"

# ---- 平台:决定编译产物和 Python 扩展的文件名 ----
case "$(uname -s)" in
  Linux*)  BUILT="libriichi.so";     EXT="libriichi.so" ;;
  Darwin*) BUILT="libriichi.dylib";  EXT="libriichi.so" ;;
  *) die "认不出的系统 $(uname -s);Windows 请用 install.ps1" ;;
esac

# ---- 前置检查 ----
say "检查前置工具"
PY="$(command -v python3 || command -v python || true)"
[ -n "$PY" ] || die "找不到 Python。请装 Python 3.11+"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info>=(3,11) else 1)' \
  || die "Python 版本太低,需要 3.11+(当前 $("$PY" --version 2>&1))"
ok "Python: $("$PY" --version 2>&1)"
command -v cargo >/dev/null 2>&1 \
  || die "找不到 cargo(编译引擎要用)。去 https://rustup.rs 装好 Rust 再重跑本脚本。"
ok "cargo: $(cargo --version)"

# ---- 1. 虚拟环境 ----
say "虚拟环境 .venv"
if [ -x ".venv/bin/python" ]; then skip ".venv"; else "$PY" -m venv .venv; ok "已建 .venv"; fi
VENV_PY=".venv/bin/python"

# ---- 2. 装本项目 ----
say "安装 dareda 及依赖"
if "$VENV_PY" -c 'import dareda' 2>/dev/null; then skip "dareda"; else
  "$VENV_PY" -m pip install -q --upgrade pip
  "$VENV_PY" -m pip install -q -e .
  ok "已装 dareda"
fi

# ---- 3. PyTorch(CPU 版;推理够用,CUDA 只是更快,想要的自己重装)----
say "PyTorch(CPU)+ numpy"
if "$VENV_PY" -c 'import torch, numpy' 2>/dev/null; then skip "torch / numpy"; else
  "$VENV_PY" -m pip install -q numpy torch --index-url https://download.pytorch.org/whl/cpu \
    || die "torch 装失败。若报路径过长,请把项目挪到更短的目录;否则见 README「遇到问题」。"
  ok "已装 torch(CPU)"
fi

# ---- 4. 引擎:克隆 + 打补丁 ----
say "麻将引擎 libriichi(上游 Mortal + 本项目补丁)"
if [ -d vendor/Mortal/.git ]; then skip "已克隆 Mortal"; else
  git clone --depth 1 https://github.com/Equim-chan/Mortal.git vendor/Mortal
  ok "已克隆 Mortal"
fi
if [ -f vendor/Mortal/libriichi/src/arena/replay.rs ]; then skip "补丁已打"; else
  cp patches/replay.rs vendor/Mortal/libriichi/src/arena/replay.rs
  git -C vendor/Mortal apply ../../patches/arena-mod.patch \
    || die "补丁应用失败(可能上游改了 arena/mod.rs)。手动加那四行,见 README「遇到问题」。"
  ok "已打补丁"
fi

# ---- 5. 编译 + 摆放产物 ----
say "编译引擎(首次约 1–2 分钟)"
if [ -f "$EXT" ]; then skip "$EXT 已存在"; else
  ( cd vendor/Mortal/libriichi && cargo build --release )
  cp "vendor/Mortal/target/release/$BUILT" "$EXT"
  ok "已编译并放好 $EXT"
fi

# ---- 6. 模型权重(约 130 MB;本项目不分发,从第三方下)----
say "模型权重"
if [ -f models/mortal_298k.pth ] && [ "$(wc -c < models/mortal_298k.pth)" -gt 100000000 ]; then
  skip "权重已下载"
else
  mkdir -p models
  curl -fL --progress-bar -o models/mortal_298k.pth "$WEIGHTS_URL" \
    || die "权重下载失败。手动下 $WEIGHTS_URL 放到 models/mortal_298k.pth。"
  ok "已下载权重"
fi

# ---- 自检 ----
say "自检"
export PYTHONPATH="src:vendor/Mortal/mortal:."
"$VENV_PY" -c 'import libriichi; assert libriichi.__profile__=="release"' \
  || die "libriichi 导入失败。"
ok "引擎可导入"

cat <<EOF

========================================================================
 装好了。以后每次用之前,先激活环境并设好 PYTHONPATH:

   source .venv/bin/activate
   export PYTHONPATH="src:vendor/Mortal/mortal:."

 然后:
   1) 按 README「取牌谱」用浏览器导出一份牌谱(需装 Tampermonkey)
   2) dareda decode-capture --capture majsoul-ws-*.json --out record.json
   3) dareda verify   --record record.json      # 必须全过
   4) dareda self-luck --record record.json --hero <你的座次 0-3> --trials 30
========================================================================
EOF
