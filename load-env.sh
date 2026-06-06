# Safe .env load when values contain $ (bash nounset treats $2 as a variable).
# Usage: source load-env.sh && load_env_file .env

load_env_file() {
  local file="${1:-.env}"
  set -a
  set +u
  # shellcheck disable=SC1090,SC1091
  source "${file}"
  set -u
  set +a
}
