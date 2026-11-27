#!/bin/zsh
set -eu
umask 077
export PATH="/Applications/Docker.app/Contents/Resources/bin:$HOME/.docker/bin:$PATH"
repo_dir="${0:A:h}/.."
cd "$repo_dir"

if ! docker info >/dev/null 2>&1; then
  print '请先打开 Docker Desktop，等引擎启动后再双击此文件。'
  exit 1
fi
project="memeretrieve-search-trial-p01"
state_dir="$HOME/Library/Application Support/MemeRetrieve/search-trial/$project"
mkdir -p "$state_dir"
password_file="$state_dir/postgres-password"
if [[ ! -e "$password_file" ]]; then
  (set -C; openssl rand -hex 24 > "$password_file") || {
    print '保存试用库凭据失败，请重新打开启动器。'
    exit 1
  }
fi
[[ -s "$password_file" ]] || { print '试用库凭据为空，启动已中止。'; exit 1; }
export POSTGRES_PASSWORD="$(<"$password_file")"
export PRIVATE_LIBRARY_ENABLED=true ACCOUNT_LOGIN_ENABLED=true API_BIND_HOST=127.0.0.1
export API_HOST_PORT=18101 POSTGRES_HOST_PORT=15431
export MEME50_DNS_MODE="${MEME50_DNS_MODE:-doh}"

clip_files=(config.json preprocessor_config.json model.safetensors vocab.json merges.txt tokenizer_config.json special_tokens_map.json)
clip_dir=data/models/clip-vit-base-patch32
use_local_model=true
for model_file in "${clip_files[@]}"; do
  [[ -s "$clip_dir/$model_file" ]] || use_local_model=false
done
if [[ "$use_local_model" == true ]]; then
  export COMPOSE_FILE=compose.yaml:compose.local-model.yaml
fi

url="http://localhost:$API_HOST_PORT/web/"
print '正在启动私人表情库，稍后会自动打开浏览器。'
docker compose -p "$project" up -d --wait api worker
if [[ "$use_local_model" == false ]] && ! docker compose -p "$project" exec -T worker sh -c '
  for file do test -s "/data/models/clip-vit-base-patch32/$file" || exit 1; done
' sh "${clip_files[@]}"; then
  print '联网找图需要 CLIP 模型。请在仓库目录运行 .venv/bin/python scripts/download_model.py，再双击此启动器。'
fi
setup="$(docker compose -p "$project" exec -T api python -m services.common.accounts)"
if [[ -n "$setup" ]]; then
  url="${url}sign-in#setup=$setup"
  print '首次绑定原有表情库，请在网页选择 Register；已有账号可选择 Sign in。'
fi
open "$url"
