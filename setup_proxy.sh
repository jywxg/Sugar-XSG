#!/bin/bash
# setup_proxy.sh - 多节点轮询解析与 sing-box 启动 (最终对齐版)[cite: 10]
export LC_ALL=C[cite: 10]
set -e[cite: 10]

export NODE_LINK=${NODE_LINK:-''}[cite: 10]

if [ -z "$NODE_LINK" ]; then
  echo "[INFO] 未配置代理，直连模式"[cite: 10]
  [ -n "$GITHUB_ENV" ] && echo "IS_PROXY=false" >> "$GITHUB_ENV"[cite: 10]
  exit 0[cite: 10]
fi[cite: 10]

if ! command -v jq &> /dev/null; then
  echo "[WARN] jq 未安装，正在安装..."[cite: 10]
  sudo apt-get update && sudo apt-get install -y jq[cite: 10]
fi[cite: 10]

command -v curl &>/dev/null && COMMAND="curl -so" || command -v wget &>/dev/null && COMMAND="wget -qO" || { echo "[ERROR] 既没有 curl 也没有 wget，请安装其中之一." >&2; exit 1; }[cite: 10]

echo "[INFO] 获取 sing-box 最新版本..."[cite: 10]
latest_version=""[cite: 10]

# 重试 3 次机制[cite: 10]
for i in {1..3}; do
  version_tag=$(curl -s "https://api.github.com/repos/SagerNet/sing-box/releases/latest" | jq -r '.tag_name // empty' 2>/dev/null || true)[cite: 10]
  
  if [ -n "$version_tag" ] && [ "$version_tag" != "null" ]; then
    latest_version="${version_tag#v}"[cite: 10]
    break
  fi
  
  echo "[WARN] 无法获取版本信息 (尝试 $i/3)，2秒后重试..."[cite: 10]
  sleep 2[cite: 10]
done

# 默认版本回退机制[cite: 10]
if [ -z "$latest_version" ]; then
  echo "[ERROR] 无法获取 sing-box 最新版本，将默认下载 v1.13.14"[cite: 10]
  export latest_version="1.13.14"[cite: 10]
fi

echo "[INFO] 最新稳定版本: v${latest_version}"[cite: 10]

ARCH_RAW=$(uname -m)[cite: 10]
case "${ARCH_RAW}" in
    'x86_64' | 'amd64')  ARCH='amd64' ;;[cite: 10]
    'x86' | 'i686' | 'i386') ARCH='386' ;;[cite: 10]
    'aarch64' | 'arm64') ARCH='arm64' ;;[cite: 10]
    'armv7l')  ARCH='armv7' ;;[cite: 10]
    's390x')   ARCH='s390x' ;;[cite: 10]
    *) echo "[ERROR] 不支持的架构: ${ARCH_RAW}"; exit 1 ;;[cite: 10]
esac

$COMMAND sing-box-${latest_version}-linux-${ARCH}.tar.gz "https://github.com/SagerNet/sing-box/releases/download/v${latest_version}/sing-box-${latest_version}-linux-${ARCH}.tar.gz"[cite: 10]
tar -xzf "sing-box-${latest_version}-linux-${ARCH}.tar.gz"[cite: 10]
mv "sing-box-${latest_version}-linux-${ARCH}/sing-box" ./[cite: 10]
rm -f "sing-box-${latest_version}-linux-${ARCH}.tar.gz"[cite: 10]
rm -rf "sing-box-${latest_version}-linux-${ARCH}"[cite: 10]
chmod +x sing-box[cite: 10]

# 辅助函数：URL 解码[cite: 10]
url_decode() {
  local encoded="$1"[cite: 10]
  printf '%b' "$(echo "$encoded" | sed 's/%/\x/g')"[cite: 10]
}

# 将 NODE_LINK 按行拆分为数组[cite: 10]
mapfile -t NODE_ARRAY <<< "$NODE_LINK"[cite: 10]

total_nodes=${#NODE_ARRAY[@]}[cite: 10]
echo "[INFO] 共检测到 $total_nodes 行配置，准备轮询测试..."[cite: 10]

node_idx=0[cite: 10]
for single_node in "${NODE_ARRAY[@]}"; do
  # 清除任何不可见的空格和回车符，防止解析错位[cite: 10]
  single_node=$(echo "$single_node" | tr -d '[:space:]')[cite: 10]
  [ -z "$single_node" ] && continue[cite: 10]
  
  node_idx=$((node_idx + 1))[cite: 10]
  echo "----------------------------------------"[cite: 10]
  echo "[INFO] 正在尝试节点 [$node_idx/$total_nodes] ..."[cite: 10]

  proto=$(echo "$single_node" | cut -d':' -f1)
  proto=$(echo "$proto" | tr '[:upper:]' '[:lower:]') # 👈 转换为小写，完美兼容大写 VLESS/VMESS/Trojan 等协议头[cite: 10]
  content="${single_node#*://}"[cite: 10]
  content="${content%%#*}"[cite: 10]

  # 重置节点变量[cite: 10]
  outbound_type=""[cite: 10]
  outbound_server=""[cite: 10]
  outbound_port=""[cite: 10]
  outbound_uuid=""[cite: 10]
  outbound_flow=""[cite: 10]
  outbound_transport_type="tcp"[cite: 10]
  outbound_path="/"[cite: 10]
  outbound_host=""[cite: 10]
  outbound_security="none"[cite: 10]
  outbound_sni=""[cite: 10]
  outbound_fingerprint="chrome"[cite: 10]
  outbound_reality_pbk=""[cite: 10]
  outbound_reality_sid=""[cite: 10]
  outbound_password=""[cite: 10]
  outbound_up_mbps=100[cite: 10]
  outbound_down_mbps=100[cite: 10]
  outbound_obfs_password=""[cite: 10]
  outbound_auth=""[cite: 10]
  outbound_congestion="bbr"[cite: 10]
  outbound_udp_over_stream="true"[cite: 10]
  outbound_zerortt="false"[cite: 10]
  outbound_username=""[cite: 10]
  outbound_password2=""[cite: 10]
  outbound_version="5"[cite: 10]
  outbound_insecure="false"[cite: 10]
  outbound_alpn=""[cite: 10]

  case "$proto" in
    vless)
      uuid_host="${content#*://}"[cite: 10]
      uuid="${uuid_host%%@*}"[cite: 10]
      rest="${uuid_host#*@}"[cite: 10]
      if [[ "$rest" == *"?"* ]]; then host_port="${rest%%\?*}"; query="${rest#*\?}"; else host_port="$rest"; query=""; fi[cite: 10]
      outbound_server="${host_port%:*}"[cite: 10]
      outbound_port="${host_port#*:}"[cite: 10]
      outbound_uuid="$uuid"[cite: 10]
      outbound_type="vless"[cite: 10]
      if [ -n "$query" ]; then
        flow=$(echo "$query" | grep -o 'flow=[^&]*' | cut -d= -f2); [ -n "$flow" ] && outbound_flow="$flow"[cite: 10]
        ttype=$(echo "$query" | grep -o 'type=[^&]*' | cut -d= -f2); [ -n "$ttype" ] && outbound_transport_type="$ttype"[cite: 10]
        path_raw=$(echo "$query" | grep -o 'path=[^&]*' | cut -d= -f2)[cite: 10]
        if [ -n "$path_raw" ]; then path_decoded=$(url_decode "$path_raw"); outbound_path="${path_decoded%%\?*}"; fi[cite: 10]
        host=$(echo "$query" | grep -o 'host=[^&]*' | cut -d= -f2); [ -n "$host" ] && outbound_host="$host"[cite: 10]
        sec=$(echo "$query" | grep -o 'security=[^&]*' | cut -d= -f2); [ -n "$sec" ] && outbound_security="$sec"[cite: 10]
        sni=$(echo "$query" | grep -o 'sni=[^&]*' | cut -d= -f2); [ -n "$sni" ] && outbound_sni="$sni"[cite: 10]
        fp=$(echo "$query" | grep -o 'fp=[^&]*' | cut -d= -f2); [ -n "$fp" ] && outbound_fingerprint="$fp"[cite: 10]
        pbk=$(echo "$query" | grep -o 'pbk=[^&]*' | cut -d= -f2); [ -n "$pbk" ] && outbound_reality_pbk="$pbk"[cite: 10]
        sid=$(echo "$query" | grep -o 'sid=[^&]*' | cut -d= -f2); [ -n "$sid" ] && outbound_reality_sid="$sid"[cite: 10]
        ins=$(echo "$query" | grep -o 'insecure=[^&]*' | cut -d= -f2); [ "$ins" = "1" ] || [ "$ins" = "true" ] && outbound_insecure="true"[cite: 10]
        alins=$(echo "$query" | grep -o 'allowInsecure=[^&]*' | cut -d= -f2); [ "$alins" = "1" ] || [ "$alins" = "true" ] && outbound_insecure="true"[cite: 10]
      fi
      [ -z "$outbound_host" ] && outbound_host="$outbound_server"[cite: 10]
      [ -z "$outbound_sni" ] && outbound_sni="$outbound_server"[cite: 10]
      # 👈 如果存在 pbk 且未指定 security，则自动设为 reality
      [ -n "$outbound_reality_pbk" ] && [ "$outbound_security" = "none" ] && outbound_security="reality"[cite: 10]
      ;;

    vmess)
      b64="${content}"[cite: 10]
      mod=$(( ${#b64} % 4 ))[cite: 10]
      if [ $mod -eq 2 ]; then b64="${b64}=="; elif [ $mod -eq 3 ]; then b64="${b64}="; fi[cite: 10]
      decoded=$(echo "$b64" | base64 -d 2>/dev/null || true)[cite: 10]
      if [ -z "$decoded" ]; then echo "[WARN] ❌ VMess 解码失败，跳过..."; continue; fi[cite: 10]
      add=$(echo "$decoded" | jq -r '.add // ""')[cite: 10]
      port=$(echo "$decoded" | jq -r '.port // 443')[cite: 10]
      id=$(echo "$decoded" | jq -r '.id // ""')[cite: 10]
      net=$(echo "$decoded" | jq -r '.net // "tcp"')[cite: 10]
      tls=$(echo "$decoded" | jq -r '.tls // ""')[cite: 10]
      sni=$(echo "$decoded" | jq -r '.sni // ""')[cite: 10]
      host=$(echo "$decoded" | jq -r '.host // ""')[cite: 10]
      path_raw=$(echo "$decoded" | jq -r '.path // "/"')[cite: 10]
      path_decoded=$(url_decode "$path_raw")[cite: 10]
      outbound_path="${path_decoded%%\?*}"[cite: 10]
      fp=$(echo "$decoded" | jq -r '.fp // "chrome"')[cite: 10]
      outbound_type="vmess"[cite: 10]
      outbound_server="$add"[cite: 10]
      outbound_port="$port"[cite: 10]
      outbound_uuid="$id"[cite: 10]
      outbound_transport_type="$net"[cite: 10]
      outbound_host="${host:-$add}"[cite: 10]
      outbound_sni="${sni:-$add}"[cite: 10]
      outbound_fingerprint="$fp"[cite: 10]
      outbound_security="$tls"[cite: 10]
      ;;

    trojan)
      pass_rest="${content#*://}"[cite: 10]
      password="${pass_rest%%@*}"[cite: 10]
      rest="${pass_rest#*@}"[cite: 10]
      if [[ "$rest" == *"?"* ]]; then host_port="${rest%%\?*}"; query="${rest#*\?}"; else host_port="$rest"; query=""; fi[cite: 10]
      outbound_server="${host_port%:*}"[cite: 10]
      outbound_port="${host_port#*:}"[cite: 10]
      outbound_password="$password"[cite: 10]
      outbound_type="trojan"[cite: 10]
      if [ -n "$query" ]; then
        ttype=$(echo "$query" | grep -o 'type=[^&]*' | cut -d= -f2); [ -n "$ttype" ] && outbound_transport_type="$ttype"[cite: 10]
        path_raw=$(echo "$query" | grep -o 'path=[^&]*' | cut -d= -f2)[cite: 10]
        if [ -n "$path_raw" ]; then path_decoded=$(url_decode "$path_raw"); outbound_path="${path_decoded%%\?*}"; fi[cite: 10]
        host=$(echo "$query" | grep -o 'host=[^&]*' | cut -d= -f2); [ -n "$host" ] && outbound_host="$host"[cite: 10]
        sni=$(echo "$query" | grep -o 'sni=[^&]*' | cut -d= -f2); [ -n "$sni" ] && outbound_sni="$sni"[cite: 10]
        fp=$(echo "$query" | grep -o 'fp=[^&]*' | cut -d= -f2); [ -n "$fp" ] && outbound_fingerprint="$fp"[cite: 10]
        ins=$(echo "$query" | grep -o 'insecure=[^&]*' | cut -d= -f2); [ "$ins" = "1" ] || [ "$ins" = "true" ] && outbound_insecure="true"[cite: 10]
        alins=$(echo "$query" | grep -o 'allowInsecure=[^&]*' | cut -d= -f2); [ "$alins" = "1" ] || [ "$alins" = "true" ] && outbound_insecure="true"[cite: 10]
      fi
      [ -z "$outbound_host" ] && outbound_host="$outbound_server"[cite: 10]
      [ -z "$outbound_sni" ] && outbound_sni="$outbound_server"[cite: 10]
      ;;

    hysteria2|hy2)
      if [[ "$content" == *"@"* ]]; then auth="${content%%@*}"; host_port="${content#*@}"; else host_port="$content"; fi[cite: 10]
      if [[ "$host_port" == *"?"* ]]; then hp="${host_port%%\?*}"; query="${host_port#*\?}"; else hp="$host_port"; query=""; fi[cite: 10]
      hp="${hp%/}"[cite: 10]
      outbound_server="${hp%:*}"[cite: 10]
      outbound_port="${hp#*:}"[cite: 10]
      outbound_type="hysteria2"[cite: 10]
      outbound_auth="$auth"[cite: 10]
      if [ -n "$query" ]; then
        obfs=$(echo "$query" | grep -o 'obfs=[^&]*' | cut -d= -f2); [ -n "$obfs" ] && outbound_obfs_password="$obfs"[cite: 10]
        sni=$(echo "$query" | grep -o 'sni=[^&]*' | cut -d= -f2); [ -n "$sni" ] && outbound_sni="$sni"[cite: 10]
        fp=$(echo "$query" | grep -o 'fp=[^&]*' | cut -d= -f2); [ -n "$fp" ] && outbound_fingerprint="$fp"[cite: 10]
        ins=$(echo "$query" | grep -o 'insecure=[^&]*' | cut -d= -f2); [ "$ins" = "1" ] || [ "$ins" = "true" ] && outbound_insecure="true"[cite: 10]
        alins=$(echo "$query" | grep -o 'allowInsecure=[^&]*' | cut -d= -f2); [ "$alins" = "1" ] || [ "$alins" = "true" ] && outbound_insecure="true"[cite: 10]
      fi
      [ -z "$outbound_sni" ] && outbound_sni="$outbound_server"[cite: 10]
      ;;

    tuic)
      uuid_pass="${content%%@*}"[cite: 10]
      rest="${content#*@}"[cite: 10]
      uuid_pass_clean=$(echo "$uuid_pass" | sed 's/%3A/:/g')[cite: 10]
      if [[ "$uuid_pass_clean" == *":"* ]]; then outbound_uuid="${uuid_pass_clean%:*}"; outbound_password2="${uuid_pass_clean#*:}"; else outbound_uuid="$uuid_pass_clean"; outbound_password2=""; fi[cite: 10]
      if [[ "$rest" == *"?"* ]]; then host_port="${rest%%\?*}"; query="${rest#*\?}"; else host_port="$rest"; query=""; fi[cite: 10]
      outbound_server="${host_port%:*}"[cite: 10]
      outbound_port="${host_port#*:}"[cite: 10]
      outbound_type="tuic"[cite: 10]
      if [ -n "$query" ]; then
        sni=$(echo "$query" | grep -o 'sni=[^&]*' | cut -d= -f2); [ -n "$sni" ] && outbound_sni="$sni"[cite: 10]
        fp=$(echo "$query" | grep -o 'fp=[^&]*' | cut -d= -f2); [ -n "$fp" ] && outbound_fingerprint="$fp"[cite: 10]
        ins=$(echo "$query" | grep -o 'insecure=[^&]*' | cut -d= -f2); [ "$ins" = "1" ] || [ "$ins" = "true" ] && outbound_insecure="true"[cite: 10]
        alins=$(echo "$query" | grep -o 'allowInsecure=[^&]*' | cut -d= -f2); [ "$alins" = "1" ] || [ "$alins" = "true" ] && outbound_insecure="true"[cite: 10]
        cc=$(echo "$query" | grep -o 'congestion_control=[^&]*' | cut -d= -f2); [ -n "$cc" ] && outbound_congestion="$cc"[cite: 10]
        alpn=$(echo "$query" | grep -o 'alpn=[^&]*' | cut -d= -f2); [ -n "$alpn" ] && outbound_alpn="$alpn"[cite: 10]
      fi
      [ -z "$outbound_sni" ] && outbound_sni="$outbound_server"[cite: 10]
      ;;
      
    anytls)
      password="${content%%@*}"[cite: 10]
      rest="${content#*@}"[cite: 10]
      if [[ "$rest" == *"?"* ]]; then host_port="${rest%%\?*}"; query="${rest#*\?}"; else host_port="$rest"; query=""; fi[cite: 10]
      outbound_server="${host_port%:*}"[cite: 10]
      outbound_port="${host_port#*:}"[cite: 10]
      outbound_password="$password"[cite: 10]
      outbound_type="anytls"[cite: 10]
      if [ -n "$query" ]; then
        sni=$(echo "$query" | grep -o 'sni=[^&]*' | cut -d= -f2); [ -n "$sni" ] && outbound_sni="$sni"[cite: 10]
        fp=$(echo "$query" | grep -o 'fp=[^&]*' | cut -d= -f2); [ -n "$fp" ] && outbound_fingerprint="$fp"[cite: 10]
        ins=$(echo "$query" | grep -o 'insecure=[^&]*' | cut -d= -f2); [ "$ins" = "1" ] || [ "$ins" = "true" ] && outbound_insecure="true"[cite: 10]
        alins=$(echo "$query" | grep -o 'allowInsecure=[^&]*' | cut -d= -f2); [ "$alins" = "1" ] || [ "$alins" = "true" ] && outbound_insecure="true"[cite: 10]
      fi
      [ -z "$outbound_sni" ] && outbound_sni="$outbound_server"[cite: 10]
      ;;

    socks5|socks)
      if [[ "$content" == *"@"* ]]; then
        user_pass="${content%%@*}"[cite: 10]
        host_port="${content#*@}"[cite: 10]
        decoded=$(echo "$user_pass" | base64 -d 2>/dev/null || true)[cite: 10]
        if [ -n "$decoded" ] && [[ "$decoded" == *":"* ]]; then
          outbound_username="${decoded%:*}"[cite: 10]
          outbound_password2="${decoded#*:}"[cite: 10]
        else
          if [[ "$user_pass" == *":"* ]]; then
            outbound_username="${user_pass%:*}"[cite: 10]
            outbound_password2="${user_pass#*:}"[cite: 10]
          else
            outbound_username="$user_pass"[cite: 10]
            outbound_password2=""[cite: 10]
          fi
        fi
      else
        host_port="$content"[cite: 10]
      fi
      outbound_server="${host_port%:*}"[cite: 10]
      outbound_port="${host_port#*:}"[cite: 10]
      outbound_type="socks"[cite: 10]
      ;;

    *)
      echo "[WARN] ❌ 不支持的协议类型: $proto，跳过..."[cite: 10]
      continue
      ;;
  esac

  if [ -z "$outbound_server" ] || [ -z "$outbound_port" ]; then
    echo "[WARN] ❌ 无法解析服务器地址或端口，跳过..."[cite: 10]
    continue
  fi

  # 构建 outbound 对象[cite: 10]
  jq_outbound="{\"type\":\"$outbound_type\",\"tag\":\"proxy\",\"server\":\"$outbound_server\",\"server_port\":$outbound_port"[cite: 10]
  case "$outbound_type" in
    vless)
      jq_outbound="$jq_outbound,\"uuid\":\"$outbound_uuid\""[cite: 10]
      [ -n "$outbound_flow" ] && jq_outbound="$jq_outbound,\"flow\":\"$outbound_flow\""[cite: 10]
      if [ "$outbound_transport_type" != "tcp" ]; then jq_outbound="$jq_outbound,\"transport\":{\"type\":\"$outbound_transport_type\",\"path\":\"$outbound_path\",\"headers\":{\"Host\":\"$outbound_host\"}}"; fi[cite: 10]
      tls_enabled="false"; [ "$outbound_security" = "tls" ] || [ "$outbound_security" = "reality" ] && tls_enabled="true"[cite: 10]
      tls_json="{\"enabled\":$tls_enabled,\"server_name\":\"$outbound_sni\",\"insecure\":$outbound_insecure,\"utls\":{\"enabled\":true,\"fingerprint\":\"$outbound_fingerprint\"}"[cite: 10]
      [ "$outbound_security" = "reality" ] && tls_json="$tls_json,\"reality\":{\"enabled\":true,\"public_key\":\"$outbound_reality_pbk\",\"short_id\":\"$outbound_reality_sid\"}"[cite: 10]
      tls_json="$tls_json}"[cite: 10]
      jq_outbound="$jq_outbound,\"tls\":$tls_json"[cite: 10]
      ;;
    vmess)
      jq_outbound="$jq_outbound,\"uuid\":\"$outbound_uuid\",\"security\":\"auto\""[cite: 10]
      jq_outbound="$jq_outbound,\"transport\":{\"type\":\"$outbound_transport_type\",\"path\":\"$outbound_path\",\"headers\":{\"Host\":\"$outbound_host\"}}"[cite: 10]
      tls_enabled="false"; [ "$outbound_security" = "tls" ] && tls_enabled="true"[cite: 10]
      jq_outbound="$jq_outbound,\"tls\":{\"enabled\":$tls_enabled,\"server_name\":\"$outbound_sni\",\"insecure\":$outbound_insecure,\"utls\":{\"enabled\":true,\"fingerprint\":\"$outbound_fingerprint\"}}"[cite: 10]
      ;;
    trojan)
      jq_outbound="$jq_outbound,\"password\":\"$outbound_password\""[cite: 10]
      jq_outbound="$jq_outbound,\"transport\":{\"type\":\"$outbound_transport_type\",\"path\":\"$outbound_path\",\"headers\":{\"Host\":\"$outbound_host\"}}"[cite: 10]
      jq_outbound="$jq_outbound,\"tls\":{\"enabled\":true,\"server_name\":\"$outbound_sni\",\"insecure\":$outbound_insecure,\"utls\":{\"enabled\":true,\"fingerprint\":\"$outbound_fingerprint\"}}"[cite: 10]
      ;;
    hysteria2)
      jq_outbound="$jq_outbound,\"up_mbps\":$outbound_up_mbps,\"down_mbps\":$outbound_down_mbps"[cite: 10]
      [ -n "$outbound_obfs_password" ] && jq_outbound="$jq_outbound,\"obfs\":{\"type\":\"salamander\",\"password\":\"$outbound_obfs_password\"}"[cite: 10]
      [ -n "$outbound_auth" ] && jq_outbound="$jq_outbound,\"password\":\"$outbound_auth\""[cite: 10]
      jq_outbound="$jq_outbound,\"tls\":{\"enabled\":true,\"server_name\":\"$outbound_sni\",\"insecure\":$outbound_insecure}"[cite: 10]
      ;;
    tuic)
      jq_outbound="$jq_outbound,\"uuid\":\"$outbound_uuid\""[cite: 10]
      [ -n "$outbound_password2" ] && jq_outbound="$jq_outbound,\"password\":\"$outbound_password2\""[cite: 10]
      jq_outbound="$jq_outbound,\"congestion_control\":\"$outbound_congestion\",\"udp_over_stream\":$outbound_udp_over_stream,\"zero_rtt_handshake\":$outbound_zerortt"[cite: 10]
      tls_json="{\"enabled\":true,\"server_name\":\"$outbound_sni\",\"insecure\":$outbound_insecure"[cite: 10]
      [ -n "$outbound_alpn" ] && tls_json="$tls_json,\"alpn\":[\"$outbound_alpn\"]"[cite: 10]
      tls_json="$tls_json}"[cite: 10]
      jq_outbound="$jq_outbound,\"tls\":$tls_json"[cite: 10]
      ;;
    anytls)
      jq_outbound="$jq_outbound,\"password\":\"$outbound_password\""[cite: 10]
      jq_outbound="$jq_outbound,\"tls\":{\"enabled\":true,\"server_name\":\"$outbound_sni\",\"insecure\":$outbound_insecure,\"utls\":{\"enabled\":true,\"fingerprint\":\"$outbound_fingerprint\"}}"[cite: 10]
      ;;
    socks)
      [ -n "$outbound_username" ] && jq_outbound="$jq_outbound,\"username\":\"$outbound_username\""[cite: 10]
      [ -n "$outbound_password2" ] && jq_outbound="$jq_outbound,\"password\":\"$outbound_password2\""[cite: 10]
      jq_outbound="$jq_outbound,\"version\":\"$outbound_version\""[cite: 10]
      ;;
  esac
  jq_outbound="$jq_outbound}"[cite: 10]

  cat << EOF > sing-box-config.json
{
  "log": {"level": "warn"},
  "inbounds": [
    {"type": "socks", "tag": "socks-in", "listen": "127.0.0.1", "listen_port": 1080},
    {"type": "http", "tag": "http-in", "listen": "127.0.0.1", "listen_port": 1081}
  ],
  "outbounds": [$jq_outbound]
}
EOF

  if ! jq empty sing-box-config.json 2>/dev/null; then
    echo "[WARN] ❌ 节点 [$node_idx] 配置存在 JSON 语法错误，已跳过！"[cite: 10]
    continue
  fi

  pkill -f sing-box 2>/dev/null || true[cite: 10]
  sleep 1[cite: 10]

  ./sing-box run -c sing-box-config.json > sing-box.log 2>&1 &[cite: 10]
  sleep 2[cite: 10]

  if ! pgrep -f sing-box > /dev/null; then
    echo "[WARN] ❌ 节点 [$node_idx] 启动失败(进程崩溃)，可能是节点配置或协议不支持，查看日志前三行："[cite: 10]
    head -n 3 sing-box.log[cite: 10]
    continue
  fi

  echo "[INFO] 启动成功，测试节点连通性..."[cite: 10]
  ip_info=$(curl -x socks5://127.0.0.1:1080 -s --max-time 10 https://ipinfo.io/json || true)[cite: 10]

  if [ -n "$ip_info" ] && echo "$ip_info" | jq -e '.ip' > /dev/null 2>&1; then
    ip_addr=$(echo "$ip_info" | jq -r '.ip // "Unknown"')[cite: 10]
    country=$(echo "$ip_info" | jq -r '.country // "Unknown"')[cite: 10]

    echo "[INFO] ✅ 节点 [$node_idx] 连接成功！ | 📍 IP: $ip_addr | 🌍 国家: $country"[cite: 10]
    
    if [ -n "$GITHUB_ENV" ]; then
      echo "IS_PROXY=true" >> "$GITHUB_ENV"[cite: 10]
      echo "PROXY_SERVER=socks5://127.0.0.1:1080" >> "$GITHUB_ENV"[cite: 10]
    fi
    exit 0
  else
    echo "[WARN] ❌ 节点 [$node_idx] 无法连接或请求超时，尝试下一个..."[cite: 10]
  fi
done

echo "[ERROR] ❌ 所有配置的代理节点均测试失败！"[cite: 10]
exit 1[cite: 10]
